"""d3_0b_benchmark.py -- D3.0B memory/strategy instrumentation diagnostic.

D3.0B reuses the D3.0A longitudinal protocol and adds structured
observability around memory and strategy persistence. It does not change
SHARD behavior: all metrics are derived from before/after storage snapshots
and existing log markers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = _ROOT / "shard_workspace" / "d2_cached_sources"
RUNS_ROOT = _ROOT / "shard_workspace" / "d3_0b_runs"
SHARD_MEMORY = _ROOT / "shard_memory"
MOOD_HISTORY = SHARD_MEMORY / "mood_history.jsonl"

PLANNING_COMMIT = "00c97a9"
TOPIC_FAMILY = "Python async / error handling / retry/backoff patterns"
SESSION_TOPICS = [
    "python error handling patterns",
    "async retry/backoff patterns",
    "asyncio advanced patterns",
    "python OOP design patterns",
    "resilient python service design",
]
ARMS = [
    {"name": "ARM_OFF", "no_l3": True},
    {"name": "ARM_ON", "no_l3": False},
]

SUBPROCESS_TIMEOUT = 2400
MISSING = "MISSING"
UNAVAILABLE = "UNAVAILABLE"
CERT_RANK = {"FAILED": 0, "NEAR_MISS": 1, "CERTIFIED": 2}


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _safe_relative(path: Path, root: Path = _ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    if not (_is_within(path, _ROOT) or _is_within(path, RUNS_ROOT)):
        raise RuntimeError(f"refusing to remove path outside workspace: {path}")
    shutil.rmtree(path)


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        _remove_tree(dst)
    shutil.copytree(src, dst)


def _snapshot_memory(snapshot_dir: Path) -> dict[str, Any]:
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    if SHARD_MEMORY.exists():
        _copy_tree(SHARD_MEMORY, snapshot_dir)
        source_exists = True
    else:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        source_exists = False
    return {
        "source": _safe_relative(SHARD_MEMORY),
        "snapshot": _safe_relative(snapshot_dir),
        "source_exists": source_exists,
        "method": "filesystem_copytree",
    }


def _restore_memory(snapshot_dir: Path) -> None:
    if SHARD_MEMORY.exists():
        _remove_tree(SHARD_MEMORY)
    if snapshot_dir.exists():
        _copy_tree(snapshot_dir, SHARD_MEMORY)
    else:
        SHARD_MEMORY.mkdir(parents=True, exist_ok=True)


def _cache_path(topic: str) -> Path:
    return CACHE_DIR / f"{_slug(topic)}.json"


def _read_cache(topic: str) -> dict[str, Any]:
    path = _cache_path(topic)
    if not path.exists():
        raise FileNotFoundError(f"missing cache for {topic!r}: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = data.get("sources") or []
    all_text = data.get("all_text") or ""
    if not data.get("hash") or not sources or not all_text:
        raise ValueError(f"invalid cache for {topic!r}: {path}")
    return {
        "topic": topic,
        "file": _safe_relative(path),
        "hash": data.get("hash"),
        "source_count": len(sources),
        "all_text_length": len(all_text),
    }


def _preflight_cache() -> dict[str, dict[str, Any]]:
    cache = {}
    errors = []
    for topic in SESSION_TOPICS:
        try:
            cache[topic] = _read_cache(topic)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        raise SystemExit("[D3.0B] cache preflight failed:\n" + "\n".join(f"  - {e}" for e in errors))
    return cache


def _sqlite_count(db_path: Path, table: str) -> int | str:
    if not db_path.exists():
        return UNAVAILABLE
    try:
        con = sqlite3.connect(db_path)
        try:
            return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        finally:
            con.close()
    except Exception:
        return UNAVAILABLE


def _file_line_count(path: Path) -> int | str:
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    except Exception:
        return UNAVAILABLE


def _storage_state() -> dict[str, Any]:
    shard_db = SHARD_MEMORY / "shard.db"
    semantic_db = SHARD_MEMORY / "chromadb" / "chroma.sqlite3"
    strategy_db = SHARD_MEMORY / "strategy_db" / "chroma.sqlite3"
    return {
        "experiments_count": _sqlite_count(shard_db, "experiments"),
        "memories_count": _sqlite_count(shard_db, "memories"),
        "memory_links_count": _sqlite_count(shard_db, "memory_links"),
        "failed_cache_count": _sqlite_count(shard_db, "failed_cache"),
        "semantic_embedding_count": _sqlite_count(semantic_db, "embeddings"),
        "strategy_embedding_count": _sqlite_count(strategy_db, "embeddings"),
        "session_snapshots_count": _file_line_count(SHARD_MEMORY / "session_snapshots.jsonl"),
        "challenge_events_count": _file_line_count(SHARD_MEMORY / "challenge_events.jsonl"),
    }


def _delta(after: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, after_value in after.items():
        before_value = before.get(key)
        if isinstance(after_value, int) and isinstance(before_value, int):
            out[f"{key}_delta"] = after_value - before_value
        else:
            out[f"{key}_delta"] = UNAVAILABLE
    return out


def _reset_mood_history() -> None:
    try:
        MOOD_HISTORY.unlink(missing_ok=True)
    except OSError:
        pass


def _load_mood_samples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    samples = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            if line.strip():
                samples.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return samples


def _archive_mood_history(target: Path) -> int:
    samples = _load_mood_samples(MOOD_HISTORY)
    with target.open("w", encoding="utf-8") as fh:
        for sample in samples:
            fh.write(json.dumps(sample, ensure_ascii=True) + "\n")
    return len(samples)


def _count_markers(text: str) -> dict[str, int]:
    return {
        "ddgs_call_count": len(re.findall(r"ddgs\.text|\[MAP\] Smart queries", text)),
        "brave_call_count": len(re.findall(r"search\.brave\.com", text)),
        "playwright_call_count": len(re.findall(r"\[AGGREGATE\] Scraping|page\.goto", text)),
        "cache_hit_map": len(re.findall(r"\[D2_CACHE_HIT_MAP\]", text)),
        "cache_hit_aggregate": len(re.findall(r"\[D2_CACHE_HIT_AGGREGATE\]", text)),
        "force_topic_count": len(re.findall(r"\[FORCE-TOPIC\]", text)),
        "strategy_query_count": len(re.findall(r"\[STRATEGY\] (Reusing strategy|No existing strategy found)", text)),
        "strategy_reuse_log_count": len(re.findall(r"\[STRATEGY\] Reusing strategy", text)),
        "strategy_store_log_count": len(re.findall(r"\[STRATEGY\].*(Stored|Stored Strategy object|Updated stats)", text)),
        "episodic_store_log_count": len(re.findall(r"\[EPISODIC\] Episode stored", text)),
        "semantic_add_log_count": len(re.findall(r"\[semantic_memory\]|add_error_pattern|add_knowledge|add_episode", text, re.I)),
        "memory_extract_log_count": len(re.findall(r"\[MEMORY\] Extracted|\[MEMORY_FAIL\] Stored", text)),
        "failure_reuse_log_count": len(re.findall(r"\[FAIL-REUSE\]|Past experience|previous attempt|prior failure", text, re.I)),
        "gwt_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\]", text)),
    }


def _mood_metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {
            "available": False,
            "mood_min": MISSING,
            "mood_recovery_delta": MISSING,
            "workspace_bias_present": False,
            "workspace_bias_traj": [],
        }
    scores = [float(s["mood_score"]) for s in samples if "mood_score" in s]
    wb = [float(s.get("components", {}).get("workspace_bias", 0.0)) for s in samples]
    if not scores:
        return {
            "available": False,
            "mood_min": MISSING,
            "mood_recovery_delta": MISSING,
            "workspace_bias_present": any(abs(x) > 0.01 for x in wb),
            "workspace_bias_traj": wb,
        }
    return {
        "available": True,
        "mood_min": round(min(scores), 3),
        "mood_recovery_delta": round(scores[-1] - min(scores), 3),
        "workspace_bias_present": any(abs(x) > 0.01 for x in wb),
        "workspace_bias_traj": wb,
    }


def _behavior_metrics(text: str) -> dict[str, Any]:
    cert_matches = re.findall(
        r"\[CERTIFY\].*?(CERTIFIED|FAILED).*?score\s+([0-9]+(?:\.[0-9]+)?)",
        text,
        flags=re.I,
    )
    if cert_matches:
        certification_verdict = cert_matches[-1][0].upper()
        certification_rank: int | str = CERT_RANK.get(certification_verdict, MISSING)
        final_score: float | str = round(float(cert_matches[-1][1]), 3)
    else:
        certification_verdict = MISSING
        certification_rank = MISSING
        final_score = MISSING
    retries_count = len(re.findall(r"Regenerating code \(attempt \d+/\d+", text, flags=re.I))
    strategy_bits = [
        re.sub(r"\s+", " ", m.lower()).strip()[:180]
        for m in re.findall(r"Focus:\s*(.+)", text, flags=re.I)
    ]
    strategy_bits += [
        re.sub(r"\s+", " ", m.lower()).strip()[:180]
        for m in re.findall(r"gaps:\s*(\[[^\]]+\])", text, flags=re.I)
    ]
    repeated_strategy_count = max(0, len(strategy_bits) - len(set(strategy_bits)))
    if certification_verdict == MISSING and final_score == MISSING:
        recovery_success: bool | str = MISSING
        loop_risk_proxy: int | str = UNAVAILABLE
    else:
        recovery_success = certification_verdict == "CERTIFIED" or (
            isinstance(final_score, float) and final_score >= 7.5
        )
        loop_risk_proxy = retries_count + repeated_strategy_count + (0 if recovery_success else 1)
    return {
        "final_score": final_score,
        "certification_verdict": certification_verdict,
        "certification_rank": certification_rank,
        "recovery_success": recovery_success,
        "retries_count": retries_count,
        "loop_risk_proxy": loop_risk_proxy,
        "repeated_strategy_count": repeated_strategy_count,
    }


def _memory_strategy_metrics(markers: dict[str, int], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    deltas = _delta(after, before)
    memory_write_count = sum(
        v for v in (
            deltas.get("experiments_count_delta"),
            deltas.get("memories_count_delta"),
            deltas.get("semantic_embedding_count_delta"),
            deltas.get("session_snapshots_count_delta"),
        )
        if isinstance(v, int) and v > 0
    )
    strategy_update_count = 0
    strategy_delta = deltas.get("strategy_embedding_count_delta")
    if isinstance(strategy_delta, int) and strategy_delta > 0:
        strategy_update_count += strategy_delta
    strategy_update_count += markers["strategy_store_log_count"]
    return {
        "storage_before": before,
        "storage_after": after,
        "storage_deltas": deltas,
        "memory_write_count": memory_write_count,
        "memory_recall_count": markers["failure_reuse_log_count"],
        "memory_items_retrieved": markers["failure_reuse_log_count"] if markers["failure_reuse_log_count"] else 0,
        "memory_recall_relevance_status": UNAVAILABLE,
        "failure_memory_reused": markers["failure_reuse_log_count"] > 0,
        "prior_failure_referenced": markers["failure_reuse_log_count"] > 0,
        "avoided_previous_failure": UNAVAILABLE,
        "strategy_read_count": markers["strategy_query_count"],
        "strategy_update_count": strategy_update_count,
        "strategy_reuse_count": markers["strategy_reuse_log_count"],
        "strategy_success_attribution_count": markers["strategy_store_log_count"],
        "strategy_failure_attribution_count": markers["memory_extract_log_count"],
        "cross_session_strategy_delta": deltas.get("strategy_embedding_count_delta"),
        "session_to_session_learning_event": memory_write_count > 0 or strategy_update_count > 0 or markers["strategy_reuse_log_count"] > 0,
        "metrics_source": "structured_storage_delta_plus_log_markers",
    }


def _run_session(arm: dict[str, Any], session_index: int, topic: str, run_root: Path, cache_meta: dict[str, Any]) -> dict[str, Any]:
    run_id = f"d3_0b_{arm['name'].lower()}_session_{session_index:02d}_{_slug(topic)}"
    run_dir = run_root / arm["name"].lower() / f"session_{session_index:02d}_{_slug(topic)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    mood_path = run_dir / "mood_samples.jsonl"
    manifest_path = run_dir / "manifest.json"

    prior_state = _storage_state()
    _reset_mood_history()
    env = os.environ.copy()
    env["D2_CACHED_SOURCES_DIR"] = str(CACHE_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("D2_CACHED_SOURCES_PATH", None)
    env.pop("D2_STRESS_MODE", None)
    env.pop("D2_STRESS_PROFILE", None)
    cmd = [
        sys.executable,
        str(_ROOT / "backend" / "night_runner.py"),
        "--cycles",
        "1",
        "--timeout",
        "60",
        "--pause",
        "0",
        "--api-limit",
        "400",
        "--topic-budget",
        "30",
        "--force-topic",
        topic,
    ]
    if arm["no_l3"]:
        cmd.append("--no-l3")

    started = time.time()
    started_iso = datetime.now().isoformat()
    print(f"[{run_id}] starting topic={topic!r} arm={arm['name']} no_l3={arm['no_l3']}")
    try:
        cp = subprocess.run(
            cmd,
            env=env,
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SUBPROCESS_TIMEOUT,
        )
        exit_code = cp.returncode
        stdout = cp.stdout
        stderr = cp.stderr
        timeout_hit = False
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\n[D3.0B] subprocess TIMEOUT after {SUBPROCESS_TIMEOUT}s"
        timeout_hit = True
    finished = time.time()
    finished_iso = datetime.now().isoformat()
    post_state = _storage_state()

    stdout_log.write_text(stdout, encoding="utf-8")
    stderr_log.write_text(stderr, encoding="utf-8")
    combined = stdout + "\n" + stderr
    markers = _count_markers(combined)
    mood_count = _archive_mood_history(mood_path)
    mood_metrics = _mood_metrics(_load_mood_samples(mood_path))
    memory_strategy_metrics = _memory_strategy_metrics(markers, prior_state, post_state)

    contaminated = markers["ddgs_call_count"] > 0 or markers["brave_call_count"] > 0 or markers["playwright_call_count"] > 0
    abort_reason = None
    if contaminated:
        abort_reason = "LIVE_PROVIDER_CALL_IN_BENCHMARK"
    elif timeout_hit:
        abort_reason = "SUBPROCESS_TIMEOUT"
    elif exit_code != 0:
        abort_reason = f"NONZERO_EXIT_{exit_code}"
    elif markers["force_topic_count"] < 1:
        abort_reason = "FORCE_TOPIC_NOT_OBSERVED"
    elif markers["cache_hit_map"] < 1:
        abort_reason = "CACHE_MAP_HOOK_NOT_FIRED"
    elif markers["cache_hit_aggregate"] < 1:
        abort_reason = "CACHE_AGGREGATE_HOOK_NOT_FIRED"
    elif mood_count == 0:
        abort_reason = "MISSING_MOOD_SAMPLES"

    manifest = {
        "d3_version": "D3.0B",
        "planning_commit": PLANNING_COMMIT,
        "run_id": run_id,
        "session_metrics": {
            "session_id": run_id,
            "arm": arm["name"],
            "topic": topic,
            "topic_family": TOPIC_FAMILY,
            "session_index": session_index,
            "prior_session_available": session_index > 1,
            "persistence_enabled": True,
            "arm_isolation_method": "shard_memory_snapshot_restore_between_arms",
        },
        "arm": arm["name"],
        "arm_no_l3": arm["no_l3"],
        "session_index": session_index,
        "topic": topic,
        "topic_family": TOPIC_FAMILY,
        "relative_run_dir": _safe_relative(run_dir, RUNS_ROOT),
        "source_mode": "cached_per_topic",
        "cache": cache_meta[topic],
        "behavior_metrics": _behavior_metrics(combined),
        "memory_metrics": {
            k: memory_strategy_metrics[k]
            for k in (
                "memory_write_count",
                "memory_recall_count",
                "memory_items_retrieved",
                "memory_recall_relevance_status",
                "failure_memory_reused",
                "prior_failure_referenced",
                "avoided_previous_failure",
            )
        },
        "strategy_metrics": {
            k: memory_strategy_metrics[k]
            for k in (
                "strategy_read_count",
                "strategy_update_count",
                "strategy_reuse_count",
                "strategy_success_attribution_count",
                "strategy_failure_attribution_count",
                "cross_session_strategy_delta",
                "session_to_session_learning_event",
            )
        },
        "storage_instrumentation": memory_strategy_metrics,
        "mood_metrics": mood_metrics,
        "subprocess_exit_code": exit_code,
        "started_at": started_iso,
        "finished_at": finished_iso,
        "duration_seconds": round(finished - started, 1),
        "mood_sample_count": mood_count,
        "contaminated": contaminated,
        "abort_reason": abort_reason,
        **markers,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    print(
        f"[{run_id}] exit={exit_code} score={manifest['behavior_metrics']['final_score']} "
        f"mem_writes={manifest['memory_metrics']['memory_write_count']} "
        f"strat_reads={manifest['strategy_metrics']['strategy_read_count']} "
        f"strat_updates={manifest['strategy_metrics']['strategy_update_count']} "
        f"cache_hits=({markers['cache_hit_map']},{markers['cache_hit_aggregate']}) "
        f"contam={contaminated} abort={abort_reason}"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abort-on-contam", action="store_true")
    args = parser.parse_args()
    cache_meta = _preflight_cache()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    baseline_snapshot = run_root / "_memory_baseline_before_d3_0b"
    original_snapshot = run_root / "_memory_original_restore_point"
    original_snapshot_info = _snapshot_memory(original_snapshot)
    _copy_tree(original_snapshot, baseline_snapshot)

    expected_sessions = len(ARMS) * len(SESSION_TOPICS)
    manifests: list[dict[str, Any]] = []
    aborted = False
    started_at = datetime.now().isoformat()
    print("=" * 70)
    print("D3.0B MEMORY/STRATEGY INSTRUMENTATION DIAGNOSTIC")
    print("=" * 70)
    print(f"Run root:        {run_root}")
    print(f"Planning commit: {PLANNING_COMMIT}")
    print(f"Expected runs:   {expected_sessions}")
    print("Live providers:  forbidden during benchmark")
    print("=" * 70)
    try:
        for arm in ARMS:
            print(f"\n[D3.0B] Restoring baseline memory before {arm['name']}...")
            _restore_memory(baseline_snapshot)
            for session_index, topic in enumerate(SESSION_TOPICS, start=1):
                manifest = _run_session(arm, session_index, topic, run_root, cache_meta)
                manifests.append(manifest)
                if args.abort_on_contam and (manifest["contaminated"] or manifest["abort_reason"]):
                    aborted = True
                    break
            if aborted:
                break
    finally:
        print("\n[D3.0B] Restoring original shard_memory state...")
        _restore_memory(original_snapshot)
    finished_at = datetime.now().isoformat()
    summary = {
        "d3_version": "D3.0B",
        "planning_commit": PLANNING_COMMIT,
        "started_at": started_at,
        "finished_at": finished_at,
        "topic_family": TOPIC_FAMILY,
        "session_topics": SESSION_TOPICS,
        "arms": [a["name"] for a in ARMS],
        "expected_sessions": expected_sessions,
        "actual_sessions": len(manifests),
        "cache_meta": cache_meta,
        "memory_isolation": {
            "method": "shard_memory_snapshot_restore_between_arms",
            "persistence_within_arm": True,
            "baseline_snapshot": _safe_relative(baseline_snapshot),
            "original_restore_point": _safe_relative(original_snapshot),
            "original_snapshot_info": original_snapshot_info,
            "core_namespace_support": False,
        },
        "instrumentation_map": [
            {
                "event_type": "memory writes",
                "file_function": "backend/study_phases.py::PostStudyPhase / MemoryExtractor / SemanticMemory",
                "currently_observable": True,
                "structured_field_available": "storage_deltas + memory_metrics.memory_write_count",
                "instrumentation_added": "before/after shard.db and semantic Chroma counts",
            },
            {
                "event_type": "memory reads/retrieval",
                "file_function": "backend/episodic_memory.py::retrieve_context, backend/semantic_memory.py::query",
                "currently_observable": "partial",
                "structured_field_available": "memory_metrics.memory_recall_count",
                "instrumentation_added": "existing log markers only; relevance remains unavailable",
            },
            {
                "event_type": "strategy reads/reuse",
                "file_function": "backend/strategy_memory.py::query, backend/night_runner.py cycle setup",
                "currently_observable": True,
                "structured_field_available": "strategy_metrics.strategy_read_count / strategy_reuse_count",
                "instrumentation_added": "existing [STRATEGY] log marker counts",
            },
            {
                "event_type": "strategy writes",
                "file_function": "backend/strategy_memory.py::store_strategy*, backend/study_phases.py::PostStudyPhase",
                "currently_observable": True,
                "structured_field_available": "strategy_metrics.strategy_update_count",
                "instrumentation_added": "strategy Chroma embedding delta + existing store markers",
            },
            {
                "event_type": "session boundaries / arm isolation",
                "file_function": "backend/d3_0b_benchmark.py",
                "currently_observable": True,
                "structured_field_available": "session_metrics + summary.memory_isolation",
                "instrumentation_added": "snapshot/restore metadata",
            },
        ],
        "aborted": aborted,
        "manifests": manifests,
    }
    summary_path = run_root / "d3_0b_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    print()
    print("=" * 70)
    print(f"Total sessions: {len(manifests)} / {expected_sessions}")
    print(f"Contaminated:   {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Abort reasons:  {[m['abort_reason'] for m in manifests if m['abort_reason']]}")
    print(f"Summary:        {summary_path}")
    print(f"Next: python backend/d3_0b_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
