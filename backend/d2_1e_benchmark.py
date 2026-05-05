"""d2_1e_benchmark.py -- D2.1E behavioral effect probe.

D2.1E is a small follow-up to D2.1D. It keeps the same clean sequential
two-topic harness and asks whether the calibrated internal GWT/Mood signal
is associated with observable behavior in the observer cycle.

This is not D2.2 and not a broad performance validation.
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
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_1e_runs"
MOOD_HISTORY = _ROOT / "shard_memory" / "mood_history.jsonl"

TOPIC_SEQUENCE = [
    "python OOP design patterns",
    "asyncio advanced patterns",
]

ARMS = [
    {"name": "ARM_OFF", "no_l3": True},
    {"name": "ARM_ON", "no_l3": False},
]

SUBPROCESS_TIMEOUT = 2400


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _count_markers(text: str) -> dict:
    return {
        "ddgs_call_count": len(re.findall(r"ddgs\.text|\[MAP\] Smart queries", text)),
        "brave_call_count": len(re.findall(r"search\.brave\.com", text)),
        "playwright_call_count": len(re.findall(r"\[AGGREGATE\] Scraping|page\.goto", text)),
        "fallback_count": len(re.findall(r"\bfallback\b(?!\s+su\s+simulazione)", text, re.I)),
        "http_error_count": len(re.findall(r"\b(429|500|502|503)\b", text)),
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


def _cache_hashes() -> dict:
    hashes = {}
    for topic in TOPIC_SEQUENCE:
        path = CACHE_DIR / f"{_slug(topic)}.json"
        if not path.exists():
            raise SystemExit(f"[D2.1E] missing cache for {topic!r}: {path}")
        hashes[topic] = json.loads(path.read_text(encoding="utf-8")).get("hash", "?")
    return hashes


def _run_one(arm: dict, run_dir: Path, run_id: str, run_index_global: int) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    manifest_path = run_dir / "manifest.json"
    mood_path = run_dir / "mood_samples.jsonl"

    _reset_mood_history()
    started = time.time()
    started_iso = datetime.now().isoformat()
    print(f"\n[{run_id}] starting D2.1E subprocess (arm={arm['name']}, no_l3={arm['no_l3']})...")

    env = os.environ.copy()
    env["D2_CACHED_SOURCES_DIR"] = str(CACHE_DIR)
    env["D2_STRESS_MODE"] = "1"
    env["D2_STRESS_PROFILE"] = "controlled_validation_failure"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("D2_CACHED_SOURCES_PATH", None)

    cmd = [
        sys.executable,
        str(_ROOT / "backend" / "night_runner.py"),
        "--cycles", "2",
        "--timeout", "60",
        "--pause", "0",
        "--api-limit", "400",
        "--topic-budget", "30",
        "--force-topic-sequence", "|".join(TOPIC_SEQUENCE),
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
        err = (exc.stderr or "") + f"\n[D2.1E] subprocess TIMEOUT after {SUBPROCESS_TIMEOUT}s"
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

    manifest = {
        "d2_version": "D2.1E",
        "run_id": run_id,
        "run_index_global": run_index_global,
        "arm": arm["name"],
        "arm_no_l3": arm["no_l3"],
        "topic_sequence": TOPIC_SEQUENCE,
        "observer_topic": TOPIC_SEQUENCE[1],
        "source_mode": "cached_per_topic",
        "cache_dir": str(CACHE_DIR.relative_to(_ROOT)).replace("\\", "/"),
        "cache_hashes": _cache_hashes(),
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
        f"tensions_traces={markers['tensions_bid_trace_count']} contam={contaminated}"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abort-on-contam", action="store_true")
    args = parser.parse_args()

    _cache_hashes()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("D2.1E BEHAVIORAL EFFECT PROBE")
    print("=" * 70)
    print(f"Run root:       {run_root}")
    print(f"Topic sequence: {TOPIC_SEQUENCE}")
    print("Scope: behavioral probe only, not D2.2")
    print("=" * 70)

    manifests = []
    aborted = False
    for idx, arm in enumerate(ARMS, start=1):
        run_id = f"d2_1e_{arm['name'].lower()}_{idx:03d}"
        manifest = _run_one(arm, run_root / arm["name"].lower(), run_id, idx)
        manifests.append(manifest)
        if args.abort_on_contam and manifest["contaminated"]:
            print(f"[D2.1E] ABORT: contaminated run ({manifest['abort_reason']})")
            aborted = True
            break

    summary = {
        "d2_version": "D2.1E",
        "started_at": manifests[0]["started_at"] if manifests else None,
        "finished_at": manifests[-1]["finished_at"] if manifests else None,
        "topic_sequence": TOPIC_SEQUENCE,
        "observer_topic": TOPIC_SEQUENCE[1],
        "arms": [a["name"] for a in ARMS],
        "stress_mode": True,
        "aborted": aborted,
        "manifests": manifests,
    }
    summary_path = run_root / "d2_1e_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print()
    print("=" * 70)
    print(f"Total runs: {len(manifests)} / {len(ARMS)}")
    print(f"Contaminated: {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Summary: {summary_path}")
    print(f"Next: python backend/d2_1e_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
