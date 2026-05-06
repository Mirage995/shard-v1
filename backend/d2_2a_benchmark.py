"""d2_2a_benchmark.py -- D2.2A micro operational validation.

D2.2A is the small, pre-registered follow-up to D2.1E. It keeps the
validated D2.1A/D2.1E cached-source harness and expands from one sequence
to two sequences with two replicas each:

    2 topic sequences x 2 reps x 2 arms = 8 subprocesses

This is not D2.2 full and not a general performance claim. The benchmark
only produces clean run artifacts for an analyzer to test whether the weak
D2.1E behavioral signal repeats outside the OOP -> asyncio sequence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

CACHE_DIR = _ROOT / "shard_workspace" / "d2_cached_sources"
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_2a_runs"
MOOD_HISTORY = _ROOT / "shard_memory" / "mood_history.jsonl"

PLANNING_COMMIT = "4be493d8b8764a49e7f8f01aad56d1ac7c144920"

TOPIC_SEQUENCES = [
    {
        "id": "seq_01_oop_to_asyncio",
        "stress_topic": "python OOP design patterns",
        "observer_topic": "asyncio advanced patterns",
    },
    {
        "id": "seq_02_sql_to_error_handling",
        "stress_topic": "sql injection prevention python",
        "observer_topic": "python error handling patterns",
    },
]

REPLICAS = [1, 2]

ARMS = [
    {"name": "ARM_OFF", "no_l3": True},
    {"name": "ARM_ON", "no_l3": False},
]

SUBPROCESS_TIMEOUT = 2400


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _topic_sequence(sequence: dict) -> list[str]:
    return [sequence["stress_topic"], sequence["observer_topic"]]


def _cache_path(topic: str) -> Path:
    return CACHE_DIR / f"{_slug(topic)}.json"


def _count_markers(text: str) -> dict:
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
        "stress_injection_count": len(re.findall(r"\[D2_STRESS\]", text)),
        "force_topic_seq_count": len(re.findall(r"\[FORCE-TOPIC-SEQUENCE\]", text)),
        "retry_attempt_count": len(re.findall(r"attempt \d+/\d+", text, re.I)),
        "gwt_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\]", text)),
        "tensions_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\].*tensions", text)),
    }


def _archive_mood_history(target: Path, run_id: str) -> int:
    if not MOOD_HISTORY.exists():
        target.write_text("", encoding="utf-8")
        return 0

    samples = []
    for line in MOOD_HISTORY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        obj["run_id"] = run_id
        samples.append(obj)

    target.write_text(
        "\n".join(json.dumps(s, ensure_ascii=True) for s in samples) + ("\n" if samples else ""),
        encoding="utf-8",
    )
    return len(samples)


def _reset_mood_history() -> None:
    if MOOD_HISTORY.exists():
        MOOD_HISTORY.unlink()


def _cache_hashes_for_sequence(sequence: dict) -> dict:
    hashes = {}
    for topic in _topic_sequence(sequence):
        path = _cache_path(topic)
        if not path.exists():
            raise FileNotFoundError(f"missing cache for {topic!r}: {path}")
        hashes[topic] = json.loads(path.read_text(encoding="utf-8")).get("hash", "?")
    return hashes


def _preflight_cache_hashes() -> dict:
    hashes = {}
    missing = []
    for sequence in TOPIC_SEQUENCES:
        for topic in _topic_sequence(sequence):
            path = _cache_path(topic)
            if not path.exists():
                missing.append((topic, path))
                continue
            hashes[topic] = json.loads(path.read_text(encoding="utf-8")).get("hash", "?")

    if missing:
        lines = ["[D2.2A] missing cached source files; benchmark will not start."]
        for topic, path in missing:
            lines.append(f"  - {topic!r}: {path}")
        lines.append("")
        lines.append("Prefetch missing cache in a separate tracked step, for example:")
        for topic, _path in missing:
            lines.append(f"  python backend/d2_1a_cache_sources.py --topic \"{topic}\"")
        raise SystemExit("\n".join(lines))
    return hashes


def _run_one(sequence: dict, rep: int, arm: dict, run_dir: Path, run_id: str, run_index_global: int) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    manifest_path = run_dir / "manifest.json"
    mood_path = run_dir / "mood_samples.jsonl"
    topic_sequence = _topic_sequence(sequence)

    _reset_mood_history()
    started = time.time()
    started_iso = datetime.now().isoformat()
    print(
        f"\n[{run_id}] starting D2.2A subprocess "
        f"(sequence={sequence['id']}, rep={rep}, arm={arm['name']}, no_l3={arm['no_l3']})..."
    )

    env = os.environ.copy()
    env["D2_CACHED_SOURCES_DIR"] = str(CACHE_DIR)
    env["D2_STRESS_MODE"] = "1"
    env["D2_STRESS_PROFILE"] = "controlled_validation_failure"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("D2_CACHED_SOURCES_PATH", None)

    cmd = [
        sys.executable,
        str(_ROOT / "backend" / "night_runner.py"),
        "--cycles",
        "2",
        "--timeout",
        "60",
        "--pause",
        "0",
        "--api-limit",
        "400",
        "--topic-budget",
        "30",
        "--force-topic-sequence",
        "|".join(topic_sequence),
    ]
    if arm["no_l3"]:
        cmd.append("--no-l3")

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
        out, err = cp.stdout, cp.stderr
        timeout_hit = False
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        out = exc.stdout or ""
        err = (exc.stderr or "") + f"\n[D2.2A] subprocess TIMEOUT after {SUBPROCESS_TIMEOUT}s"
        timeout_hit = True

    finished = time.time()
    finished_iso = datetime.now().isoformat()

    stdout_log.write_text(out, encoding="utf-8")
    stderr_log.write_text(err, encoding="utf-8")
    markers = _count_markers(out + "\n" + err)
    mood_count = _archive_mood_history(mood_path, run_id)

    contaminated = (
        markers["ddgs_call_count"] > 0
        or markers["brave_call_count"] > 0
        or markers["playwright_call_count"] > 0
    )
    abort_reason = None
    if contaminated:
        abort_reason = "LIVE_SEARCH_IN_CACHED_MODE"
    elif timeout_hit:
        abort_reason = "SUBPROCESS_TIMEOUT"
    elif exit_code != 0:
        abort_reason = f"NONZERO_EXIT_{exit_code}"
    elif markers["fallback_count"] > 10:
        abort_reason = "FALLBACK_THRESHOLD_EXCEEDED"
        contaminated = True
    elif markers["http_error_count"] > 3:
        abort_reason = "HTTP_ERROR_THRESHOLD_EXCEEDED"
        contaminated = True
    elif markers["force_topic_seq_count"] < 2:
        abort_reason = "FORCE_TOPIC_SEQUENCE_NOT_OBSERVED_TWICE"
    elif markers["stress_injection_count"] == 0:
        abort_reason = "STRESS_INJECTION_NOT_OBSERVED"
    elif markers["cache_hit_map"] < 2:
        abort_reason = "CACHE_MAP_HOOK_NOT_FIRED_BOTH_CYCLES"
    elif markers["cache_hit_aggregate"] < 2:
        abort_reason = "CACHE_AGGREGATE_HOOK_NOT_FIRED_BOTH_CYCLES"
    elif mood_count == 0:
        abort_reason = "MISSING_MOOD_SAMPLES"

    manifest = {
        "d2_version": "D2.2A",
        "planning_commit": PLANNING_COMMIT,
        "run_id": run_id,
        "run_index_global": run_index_global,
        "sequence_id": sequence["id"],
        "rep": rep,
        "arm": arm["name"],
        "arm_no_l3": arm["no_l3"],
        "topic_sequence": topic_sequence,
        "stress_topic": sequence["stress_topic"],
        "observer_topic": sequence["observer_topic"],
        "relative_run_dir": str(run_dir.relative_to(RUNS_ROOT)).replace("\\", "/"),
        "source_mode": "cached_per_topic",
        "cache_dir": str(CACHE_DIR.relative_to(_ROOT)).replace("\\", "/"),
        "cache_hashes": _cache_hashes_for_sequence(sequence),
        "experimental_patch": {
            "file": "backend/cognition/mood_workspace_coupling.py",
            "winner": "tensions",
            "valence_delta": -0.05,
            "arousal_delta": 0.15,
        },
        "stress_mode": True,
        "stress_profile": "controlled_validation_failure",
        "stress_injection_observed": markers["stress_injection_count"] > 0,
        "force_topic_seq_observed": markers["force_topic_seq_count"] >= 2,
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
        f"seq_obs={manifest['force_topic_seq_observed']} "
        f"stress_obs={manifest['stress_injection_observed']} "
        f"cache_hits=({markers['cache_hit_map']},{markers['cache_hit_aggregate']}) "
        f"mood_n={mood_count} tensions_traces={markers['tensions_bid_trace_count']} "
        f"contam={contaminated} abort={abort_reason}"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abort-on-contam", action="store_true")
    args = parser.parse_args()

    all_cache_hashes = _preflight_cache_hashes()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    expected_runs = len(TOPIC_SEQUENCES) * len(REPLICAS) * len(ARMS)
    print("=" * 70)
    print("D2.2A MICRO OPERATIONAL VALIDATION")
    print("=" * 70)
    print(f"Run root:       {run_root}")
    print(f"Planning commit: {PLANNING_COMMIT}")
    print(f"Sequences:      {[s['id'] for s in TOPIC_SEQUENCES]}")
    print(f"Replicas:       {REPLICAS}")
    print(f"Expected runs:  {expected_runs}")
    print("Scope: micro validation only, not D2.2 full")
    print("=" * 70)

    manifests = []
    aborted = False
    run_index = 0
    for sequence in TOPIC_SEQUENCES:
        for rep in REPLICAS:
            for arm in ARMS:
                run_index += 1
                run_id = f"d2_2a_{sequence['id']}_rep{rep:02d}_{arm['name'].lower()}"
                run_dir = run_root / sequence["id"] / f"rep_{rep:02d}" / arm["name"].lower()
                manifest = _run_one(sequence, rep, arm, run_dir, run_id, run_index)
                manifests.append(manifest)
                if args.abort_on_contam and (manifest["contaminated"] or manifest["abort_reason"]):
                    print(f"[D2.2A] ABORT: run failed sanity ({manifest['abort_reason']})")
                    aborted = True
                    break
            if aborted:
                break
        if aborted:
            break

    summary = {
        "d2_version": "D2.2A",
        "planning_commit": PLANNING_COMMIT,
        "started_at": manifests[0]["started_at"] if manifests else None,
        "finished_at": manifests[-1]["finished_at"] if manifests else None,
        "topic_sequences": TOPIC_SEQUENCES,
        "replicas": REPLICAS,
        "arms": [a["name"] for a in ARMS],
        "expected_subprocesses": expected_runs,
        "actual_subprocesses": len(manifests),
        "all_cache_hashes": all_cache_hashes,
        "stress_mode": True,
        "experimental_patch": {
            "file": "backend/cognition/mood_workspace_coupling.py",
            "winner": "tensions",
            "valence_delta": -0.05,
            "arousal_delta": 0.15,
        },
        "aborted": aborted,
        "manifests": manifests,
    }
    summary_path = run_root / "d2_2a_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print()
    print("=" * 70)
    print(f"Total runs:   {len(manifests)} / {expected_runs}")
    print(f"Contaminated: {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Abort reasons: {[m['abort_reason'] for m in manifests if m['abort_reason']]}")
    print(f"Summary:      {summary_path}")
    print(f"Next: python backend/d2_2a_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
