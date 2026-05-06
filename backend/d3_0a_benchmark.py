"""d3_0a_benchmark.py -- D3.0A learning curve probe.

D3.0A is the first small longitudinal probe after D2. It tests whether
ARM_ON improves across repeated sessions relative to ARM_OFF, with
memory/strategy persistence intentionally enabled within each arm.

The benchmark never performs live MAP/AGG calls. All topics must have a
validated cache in shard_workspace/d2_cached_sources before the run starts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = _ROOT / "shard_workspace" / "d2_cached_sources"
RUNS_ROOT = _ROOT / "shard_workspace" / "d3_0a_runs"
SHARD_MEMORY = _ROOT / "shard_memory"
MOOD_HISTORY = SHARD_MEMORY / "mood_history.jsonl"

PLANNING_COMMIT = "326cc7f"
PREFETCH_REPORT = "docs/experiments/d3_0a_cache_prefetch.md"

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

CERT_RANK = {
    "FAILED": 0,
    "NEAR_MISS": 1,
    "CERTIFIED": 2,
}


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _cache_path(topic: str) -> Path:
    return CACHE_DIR / f"{_slug(topic)}.json"


def _safe_relative(path: Path, root: Path = _ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


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
    missing = []
    invalid = []
    for topic in SESSION_TOPICS:
        try:
            cache[topic] = _read_cache(topic)
        except FileNotFoundError as exc:
            missing.append(str(exc))
        except ValueError as exc:
            invalid.append(str(exc))

    if missing or invalid:
        lines = ["[D3.0A] cached source preflight failed; benchmark will not start."]
        if missing:
            lines.append("Missing:")
            lines.extend(f"  - {item}" for item in missing)
        if invalid:
            lines.append("Invalid:")
            lines.extend(f"  - {item}" for item in invalid)
        lines.append("")
        lines.append("Prefetch missing/invalid caches in a separate tracked step.")
        raise SystemExit("\n".join(lines))
    return cache


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        _remove_tree(dst)
    shutil.copytree(src, dst)


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    allowed_roots = [_ROOT, RUNS_ROOT]
    if not any(_is_within(path, root) or path.resolve() == root.resolve() for root in allowed_roots):
        raise RuntimeError(f"refusing to remove path outside workspace: {path}")
    shutil.rmtree(path)


def _snapshot_memory(snapshot_dir: Path) -> dict[str, Any]:
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    if SHARD_MEMORY.exists():
        _copy_tree(SHARD_MEMORY, snapshot_dir)
        exists = True
    else:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        exists = False
    return {
        "source": _safe_relative(SHARD_MEMORY),
        "snapshot": _safe_relative(snapshot_dir),
        "source_exists": exists,
        "method": "filesystem_copytree",
    }


def _restore_memory(snapshot_dir: Path) -> None:
    if SHARD_MEMORY.exists():
        _remove_tree(SHARD_MEMORY)
    if snapshot_dir.exists():
        _copy_tree(snapshot_dir, SHARD_MEMORY)
    else:
        SHARD_MEMORY.mkdir(parents=True, exist_ok=True)


def _reset_mood_history() -> None:
    try:
        MOOD_HISTORY.unlink(missing_ok=True)
    except OSError:
        pass


def _load_mood_samples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    samples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return samples


def _archive_mood_history(target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    samples = _load_mood_samples(MOOD_HISTORY)
    with target.open("w", encoding="utf-8") as fh:
        for sample in samples:
            fh.write(json.dumps(sample, ensure_ascii=True) + "\n")
    return len(samples)


def _count_markers(text: str) -> dict[str, int]:
    http_error_pattern = (
        r"HTTP/(?:1\.1|2)\s+(?:429|500|502|503)\b"
        r"|\b(?:429|500|502|503)\s+"
        r"(?:Too Many Requests|Internal Server Error|Bad Gateway|Service Unavailable)\b"
    )
    return {
        "ddgs_call_count": len(re.findall(r"ddgs\.text|\[MAP\] Smart queries", text)),
        "brave_call_count": len(re.findall(r"search\.brave\.com", text)),
        "playwright_call_count": len(re.findall(r"\[AGGREGATE\] Scraping|page\.goto", text)),
        "fallback_count": len(re.findall(r"\bfallback\b(?!\s+su\s+simulazione)", text, re.I)),
        "http_error_count": len(re.findall(http_error_pattern, text, flags=re.I)),
        "cache_hit_map": len(re.findall(r"\[D2_CACHE_HIT_MAP\]", text)),
        "cache_hit_aggregate": len(re.findall(r"\[D2_CACHE_HIT_AGGREGATE\]", text)),
        "force_topic_count": len(re.findall(r"\[FORCE-TOPIC\]", text)),
        "retry_attempt_count": len(re.findall(r"Regenerating code \(attempt \d+/\d+", text, re.I)),
        "gwt_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\]", text)),
        "tensions_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\].*tensions", text)),
    }


def _mood_metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {
            "available": False,
            "mood_traj": [],
            "workspace_bias_traj": [],
            "mood_min": MISSING,
            "mood_recovery_delta": MISSING,
            "workspace_bias_present": False,
        }
    scores = [float(s["mood_score"]) for s in samples if "mood_score" in s]
    wb = [float(s.get("components", {}).get("workspace_bias", 0.0)) for s in samples]
    if not scores:
        return {
            "available": False,
            "mood_traj": [],
            "workspace_bias_traj": wb,
            "mood_min": MISSING,
            "mood_recovery_delta": MISSING,
            "workspace_bias_present": any(abs(x) > 0.01 for x in wb),
        }
    return {
        "available": True,
        "mood_traj": scores,
        "workspace_bias_traj": wb,
        "mood_min": round(min(scores), 3),
        "mood_recovery_delta": round(scores[-1] - min(scores), 3),
        "workspace_bias_present": any(abs(x) > 0.01 for x in wb),
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

    strategy_bits = []
    for match in re.findall(r"Focus:\s*(.+)", text, flags=re.I):
        strategy_bits.append(re.sub(r"\s+", " ", match.lower()).strip()[:180])
    for match in re.findall(r"gaps:\s*(\[[^\]]+\])", text, flags=re.I):
        strategy_bits.append(re.sub(r"\s+", " ", match.lower()).strip()[:180])
    repeated_strategy_count = max(0, len(strategy_bits) - len(set(strategy_bits)))

    if certification_verdict == MISSING and final_score == MISSING:
        recovery_success: bool | str = MISSING
    else:
        recovery_success = (
            certification_verdict == "CERTIFIED"
            or (isinstance(final_score, float) and final_score >= 7.5)
        )

    if recovery_success == MISSING:
        loop_risk_proxy: int | str = UNAVAILABLE
    else:
        loop_risk_proxy = retries_count + repeated_strategy_count + (0 if recovery_success else 1)

    benchmark_matches = re.findall(
        r"\[BENCHMARK_RUN\].*?:\s+(\d+)/(\d+)\s+passed.*?pass_rate=([0-9]+)%",
        text,
        flags=re.I,
    )
    if benchmark_matches:
        _passed, total, pass_rate = benchmark_matches[-1]
        benchmark_score: float | None = None if int(total) == 0 else round(float(pass_rate) / 100.0, 3)
        benchmark_score_status = "UNAVAILABLE" if benchmark_score is None else "AVAILABLE"
    else:
        benchmark_score = None
        benchmark_score_status = UNAVAILABLE

    return {
        "final_score": final_score,
        "certification_verdict": certification_verdict,
        "certification_rank": certification_rank,
        "recovery_success": recovery_success,
        "retries_count": retries_count,
        "loop_risk_proxy": loop_risk_proxy,
        "repeated_strategy_count": repeated_strategy_count,
        "benchmark_score": benchmark_score,
        "benchmark_score_status": benchmark_score_status,
    }


def _memory_strategy_metrics(text: str) -> dict[str, Any]:
    memory_recall_count = len(re.findall(
        r"\b(memory|experience|episodic|semantic memory|retrieved)\b",
        text,
        flags=re.I,
    ))
    strategy_reuse_count = len(re.findall(
        r"\[STUDY\] Using past strategy|strateg(?:y|ies).*reus",
        text,
        flags=re.I,
    ))
    strategy_update_count = len(re.findall(
        r"strateg(?:y|ies).*(?:stored|saved|updated|learned)|\[STRATEGY\].*(?:stored|saved|updated)",
        text,
        flags=re.I,
    ))
    failure_attribution_present = bool(re.search(
        r"failure attribution|why it failed|failed strategy|root cause|failure mode",
        text,
        flags=re.I,
    ))
    return {
        "memory_recall_count": memory_recall_count,
        "memory_recall_relevance": UNAVAILABLE,
        "memory_recall_source": "log_proxy",
        "strategy_update_count": strategy_update_count,
        "strategy_reuse_count": strategy_reuse_count,
        "failure_attribution_present": failure_attribution_present,
        "limitations": [
            "memory/strategy metrics are log-derived proxies unless structured fields are emitted by core pipeline"
        ],
    }


def _run_session(
    arm: dict[str, Any],
    session_index: int,
    topic: str,
    run_root: Path,
    cache_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    run_id = f"d3_0a_{arm['name'].lower()}_session_{session_index:02d}_{_slug(topic)}"
    run_dir = run_root / arm["name"].lower() / f"session_{session_index:02d}_{_slug(topic)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    mood_path = run_dir / "mood_samples.jsonl"
    manifest_path = run_dir / "manifest.json"

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
        stderr = (exc.stderr or "") + f"\n[D3.0A] subprocess TIMEOUT after {SUBPROCESS_TIMEOUT}s"
        timeout_hit = True

    finished = time.time()
    finished_iso = datetime.now().isoformat()
    stdout_log.write_text(stdout, encoding="utf-8")
    stderr_log.write_text(stderr, encoding="utf-8")
    combined = stdout + "\n" + stderr
    markers = _count_markers(combined)
    mood_count = _archive_mood_history(mood_path)
    mood_metrics = _mood_metrics(_load_mood_samples(mood_path))

    contaminated = (
        markers["ddgs_call_count"] > 0
        or markers["brave_call_count"] > 0
        or markers["playwright_call_count"] > 0
    )
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
        "d3_version": "D3.0A",
        "planning_commit": PLANNING_COMMIT,
        "prefetch_report": PREFETCH_REPORT,
        "run_id": run_id,
        "arm": arm["name"],
        "arm_no_l3": arm["no_l3"],
        "session_index": session_index,
        "topic": topic,
        "topic_family": TOPIC_FAMILY,
        "relative_run_dir": _safe_relative(run_dir, RUNS_ROOT),
        "source_mode": "cached_per_topic",
        "cache": cache_meta[topic],
        "memory_persistence": {
            "enabled_within_arm": True,
            "reset_between_sessions_same_arm": False,
            "arm_isolation_method": "shard_memory_snapshot_restore_between_arms",
        },
        "behavior_metrics": _behavior_metrics(combined),
        "memory_strategy_metrics": _memory_strategy_metrics(combined),
        "mood_metrics": mood_metrics,
        "signal_metrics": {
            "gwt_bid_trace_count": markers["gwt_bid_trace_count"],
            "tensions_trace_count": markers["tensions_bid_trace_count"],
            "workspace_bias_present": mood_metrics["workspace_bias_present"],
        },
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
        f"[{run_id}] exit={exit_code} duration={manifest['duration_seconds']}s "
        f"cache_hits=({markers['cache_hit_map']},{markers['cache_hit_aggregate']}) "
        f"score={manifest['behavior_metrics']['final_score']} mood_min={mood_metrics['mood_min']} "
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

    baseline_snapshot = run_root / "_memory_baseline_before_d3_0a"
    original_snapshot = run_root / "_memory_original_restore_point"
    memory_snapshot_info = _snapshot_memory(original_snapshot)
    _copy_tree(original_snapshot, baseline_snapshot)

    expected_sessions = len(ARMS) * len(SESSION_TOPICS)
    manifests: list[dict[str, Any]] = []
    aborted = False

    print("=" * 70)
    print("D3.0A LEARNING CURVE PROBE")
    print("=" * 70)
    print(f"Run root:        {run_root}")
    print(f"Planning commit: {PLANNING_COMMIT}")
    print(f"Topic family:    {TOPIC_FAMILY}")
    print(f"Sessions/arm:    {len(SESSION_TOPICS)}")
    print(f"Expected runs:   {expected_sessions}")
    print("Memory:          persistent within arm, snapshot-restored between arms")
    print("Live providers:  forbidden during benchmark")
    print("=" * 70)

    started_at = datetime.now().isoformat()
    try:
        for arm in ARMS:
            print(f"\n[D3.0A] Restoring baseline memory before {arm['name']}...")
            _restore_memory(baseline_snapshot)
            for session_index, topic in enumerate(SESSION_TOPICS, start=1):
                manifest = _run_session(arm, session_index, topic, run_root, cache_meta)
                manifests.append(manifest)
                if args.abort_on_contam and (manifest["contaminated"] or manifest["abort_reason"]):
                    print(f"[D3.0A] ABORT: session failed sanity ({manifest['abort_reason']})")
                    aborted = True
                    break
            if aborted:
                break
    finally:
        print("\n[D3.0A] Restoring original shard_memory state...")
        _restore_memory(original_snapshot)

    finished_at = datetime.now().isoformat()
    summary = {
        "d3_version": "D3.0A",
        "planning_commit": PLANNING_COMMIT,
        "prefetch_report": PREFETCH_REPORT,
        "started_at": started_at,
        "finished_at": finished_at,
        "topic_family": TOPIC_FAMILY,
        "session_topics": SESSION_TOPICS,
        "arms": [arm["name"] for arm in ARMS],
        "expected_sessions": expected_sessions,
        "actual_sessions": len(manifests),
        "cache_meta": cache_meta,
        "memory_isolation": {
            "method": "shard_memory_snapshot_restore_between_arms",
            "persistence_within_arm": True,
            "baseline_snapshot": _safe_relative(baseline_snapshot),
            "original_restore_point": _safe_relative(original_snapshot),
            "original_snapshot_info": memory_snapshot_info,
            "arm_leakage_risk": "reduced_by_restoring_same_baseline_before_each_arm",
            "core_namespace_support": False,
        },
        "aborted": aborted,
        "manifests": manifests,
    }
    summary_path = run_root / "d3_0a_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print()
    print("=" * 70)
    print(f"Total sessions: {len(manifests)} / {expected_sessions}")
    print(f"Contaminated:   {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Abort reasons:  {[m['abort_reason'] for m in manifests if m['abort_reason']]}")
    print(f"Summary:        {summary_path}")
    print(f"Next: python backend/d3_0a_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
