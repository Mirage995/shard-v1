"""d2_1c_benchmark.py -- D2.1C Sequential Multi-Topic protocol.

Goal:
    Test whether MoodWorkspaceCoupling's accumulated bias becomes
    observable when a SECOND topic runs in the same subprocess after
    a stress-induced first topic has produced workspace winners.

    D2.1B FAIL was structural: the coupling is inter-topic / next-cycle
    by design. D2.1C moves the observation window one cycle forward.

Protocol:
    For each arm in [ARM_OFF, ARM_ON]:
        Spawn ONE subprocess running night_runner.py --cycles 2
        with --force-topic-sequence "TOPIC_1|TOPIC_2".

        Cycle 1: TOPIC_1 (stress inducer) -- python OOP design patterns
                 with D2_STRESS_MODE=1.
                 Workspace winners accumulate, drain_session_winners
                 calls on_workspace_result -> bias mutates.
        Cycle 2: TOPIC_2 (bias observer) -- asyncio advanced patterns.
                 mood.compute reads accumulated workspace_bias FIRST.
                 If GWT/Mood coupling is real and ARM is ON,
                 workspace_bias should be non-zero in the early
                 mood samples of cycle 2.

    The whole sequence is in ONE subprocess so the in-memory
    MoodWorkspaceCoupling instance survives between cycles.

Verdict produced by d2_1c_analyze.py:
    PASS_STRONG    ARM_ON cycle-2 workspace_bias != 0,
                   ARM_OFF cycle-2 workspace_bias near-zero,
                   harness clean.
    PASS_WEAK      ARM_ON has non-zero bias somewhere in cycle 2
                   but no behavioral metric difference.
    FAIL           ARM_ON cycle-2 workspace_bias still zero.
    CONTAMINATED   live calls / cache mismatch / subprocess error /
                   stress not observed / wrong topic order.
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

CACHE_DIR     = _ROOT / "shard_workspace" / "d2_cached_sources"
RUNS_ROOT     = _ROOT / "shard_workspace" / "d2_1c_runs"
MOOD_HISTORY  = _ROOT / "shard_memory" / "mood_history.jsonl"

# Sequence: stress inducer first, bias observer second.
TOPIC_SEQUENCE = [
    "python OOP design patterns",   # stress inducer (cycle 1)
    "asyncio advanced patterns",    # bias observer  (cycle 2)
]

ARMS = [
    {"name": "ARM_OFF", "no_l3": True},
    {"name": "ARM_ON",  "no_l3": False},
]

SUBPROCESS_TIMEOUT = 2400   # 40 min per arm (2 cycles)


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _count_markers(text: str) -> dict:
    return {
        "ddgs_call_count":           len(re.findall(r"ddgs\.text|\[MAP\] Smart queries", text)),
        "brave_call_count":          len(re.findall(r"search\.brave\.com", text)),
        "playwright_call_count":     len(re.findall(r"\[AGGREGATE\] Scraping|page\.goto", text)),
        "fallback_count":            len(re.findall(r"\bfallback\b(?!\s+su\s+simulazione)", text, re.I)),
        "http_error_count":          len(re.findall(r"\b(429|500|502|503)\b", text)),
        "cache_hit_map":             len(re.findall(r"\[D2_CACHE_HIT_MAP\]", text)),
        "cache_hit_aggregate":       len(re.findall(r"\[D2_CACHE_HIT_AGGREGATE\]", text)),
        "stress_injection_count":    len(re.findall(r"\[D2_STRESS\]", text)),
        "force_topic_seq_count":     len(re.findall(r"\[FORCE-TOPIC-SEQUENCE\]", text)),
        "retry_attempt_count":       len(re.findall(r"attempt \d+/\d+", text, re.I)),
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
        "\n".join(json.dumps(s, ensure_ascii=False) for s in samples) + ("\n" if samples else ""),
        encoding="utf-8",
    )
    return len(samples)


def _reset_mood_history():
    if MOOD_HISTORY.exists():
        MOOD_HISTORY.unlink()


def _run_one(arm: dict, run_dir: Path, run_id: str, run_index_global: int) -> dict:
    """One subprocess running cycles=2 with the topic sequence forced."""
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log    = run_dir / "stdout.log"
    stderr_log    = run_dir / "stderr.log"
    manifest_path = run_dir / "manifest.json"
    mood_path     = run_dir / "mood_samples.jsonl"

    # Both topics must resolve through the cached-source directory. The
    # study_agent D2 hook uses D2_CACHED_SOURCES_DIR to select the cache file
    # by current topic slug inside the same two-cycle subprocess.
    cache_paths = {t: CACHE_DIR / f"{_slug(t)}.json" for t in TOPIC_SEQUENCE}
    cache_hashes = {}
    for t, p in cache_paths.items():
        if not p.exists():
            raise SystemExit(f"[D2.1C] missing cache for {t!r}: {p}")
        cache_hashes[t] = json.loads(p.read_text(encoding="utf-8")).get("hash", "?")

    _reset_mood_history()
    started = time.time()
    started_iso = datetime.now().isoformat()
    print(f"\n[{run_id}] starting subprocess (arm={arm['name']}, no_l3={arm['no_l3']}, cycles=2 sequence)...")

    env = os.environ.copy()
    env["D2_CACHED_SOURCES_DIR"]  = str(CACHE_DIR)        # per-topic resolution
    env["D2_STRESS_MODE"]         = "1"
    env["D2_STRESS_PROFILE"]      = "controlled_validation_failure"
    env["PYTHONIOENCODING"]       = "utf-8"
    # Make sure the single-cache env var is unset so the loader falls
    # through to the per-cycle directory resolver.
    env.pop("D2_CACHED_SOURCES_PATH", None)

    cmd = [
        sys.executable,
        str(_ROOT / "backend" / "night_runner.py"),
        "--cycles",                 "2",
        "--timeout",                "60",
        "--pause",                  "0",
        "--api-limit",              "400",
        "--topic-budget",           "30",
        "--force-topic-sequence",   "|".join(TOPIC_SEQUENCE),
    ]
    if arm["no_l3"]:
        cmd.append("--no-l3")

    try:
        cp = subprocess.run(
            cmd, env=env, cwd=str(_ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=SUBPROCESS_TIMEOUT,
        )
        exit_code = cp.returncode
        out, err = cp.stdout, cp.stderr
        timeout_hit = False
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        out = (exc.stdout or "")
        err = (exc.stderr or "") + f"\n[D2.1C] subprocess TIMEOUT after {SUBPROCESS_TIMEOUT}s"
        timeout_hit = True

    finished = time.time()
    finished_iso = datetime.now().isoformat()

    stdout_log.write_text(out, encoding="utf-8")
    stderr_log.write_text(err, encoding="utf-8")

    markers = _count_markers(out + "\n" + err)
    mood_count = _archive_mood_history(mood_path, run_id)

    contaminated = (
        markers["ddgs_call_count"]       > 0
        or markers["brave_call_count"]      > 0
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
        abort_reason = "FALLBACK_THRESHOLD_EXCEEDED"; contaminated = True
    elif markers["http_error_count"] > 3:
        abort_reason = "HTTP_ERROR_THRESHOLD_EXCEEDED"; contaminated = True
    elif markers["force_topic_seq_count"] < 2:
        abort_reason = "FORCE_TOPIC_SEQUENCE_NOT_OBSERVED_TWICE"
    elif markers["stress_injection_count"] == 0:
        abort_reason = "STRESS_INJECTION_NOT_OBSERVED"
    elif markers["cache_hit_map"] < 2:
        abort_reason = "CACHE_MAP_HOOK_NOT_FIRED_BOTH_CYCLES"

    manifest = {
        "d2_version":               "D2.1C",
        "run_id":                   run_id,
        "run_index_global":         run_index_global,
        "arm":                      arm["name"],
        "arm_no_l3":                arm["no_l3"],
        "topic_sequence":           TOPIC_SEQUENCE,
        "source_mode":              "cached_per_topic",
        "cache_dir":                str(CACHE_DIR.relative_to(_ROOT)).replace("\\", "/"),
        "cache_hashes":             cache_hashes,
        "stress_mode":              True,
        "stress_profile":           "controlled_validation_failure",
        "stress_injection_observed": markers["stress_injection_count"] > 0,
        "force_topic_seq_observed": markers["force_topic_seq_count"] >= 2,
        "subprocess_exit_code":     exit_code,
        "started_at":               started_iso,
        "finished_at":              finished_iso,
        "duration_seconds":         round(finished - started, 1),
        "mood_sample_count":        mood_count,
        "contaminated":             contaminated,
        "abort_reason":             abort_reason,
        **markers,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[{run_id}] exit={exit_code}  duration={manifest['duration_seconds']}s  "
          f"seq_obs={manifest['force_topic_seq_observed']}  stress_obs={manifest['stress_injection_observed']}  "
          f"cache_hits=({markers['cache_hit_map']},{markers['cache_hit_aggregate']})  "
          f"contam={contaminated}")
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--abort-on-contam", action="store_true")
    args = p.parse_args()

    # Verify caches for both sequence topics
    for t in TOPIC_SEQUENCE:
        f = CACHE_DIR / f"{_slug(t)}.json"
        if not f.exists():
            print(f"[D2.1C] missing cache: {f}")
            print("[D2.1C] Run: python backend/d2_1a_cache_sources.py")
            sys.exit(2)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("D2.1C SEQUENTIAL MULTI-TOPIC STRESS VALIDATION")
    print("=" * 70)
    print(f"Run root:           {run_root}")
    print(f"Topic sequence:     {TOPIC_SEQUENCE}")
    print(f"Arms:               {[a['name'] for a in ARMS]}")
    print(f"Stress mode:        ON  profile=controlled_validation_failure  (applies attempt 1 of EACH cycle)")
    print(f"Subprocess timeout: {SUBPROCESS_TIMEOUT}s per arm")
    print("=" * 70)

    manifests = []
    run_index_global = 0
    aborted = False

    for arm in ARMS:
        run_index_global += 1
        run_id = f"d2_1c_{arm['name'].lower()}_{run_index_global:03d}"
        arm_dir = run_root / arm["name"].lower()
        m = _run_one(arm=arm, run_dir=arm_dir, run_id=run_id, run_index_global=run_index_global)
        manifests.append(m)
        if args.abort_on_contam and m["contaminated"]:
            print(f"[D2.1C] ABORT: contaminated run ({m['abort_reason']})")
            aborted = True
            break

    summary = {
        "d2_version":     "D2.1C",
        "started_at":     manifests[0]["started_at"]  if manifests else None,
        "finished_at":    manifests[-1]["finished_at"] if manifests else None,
        "topic_sequence": TOPIC_SEQUENCE,
        "arms":           [a["name"] for a in ARMS],
        "stress_mode":    True,
        "aborted":        aborted,
        "manifests":      manifests,
    }
    (run_root / "d2_1c_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print(f"Total runs: {len(manifests)} / {len(ARMS)}")
    print(f"Contaminated: {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Stress observed: {sum(1 for m in manifests if m['stress_injection_observed'])} / {len(manifests)}")
    print(f"Sequence observed: {sum(1 for m in manifests if m['force_topic_seq_observed'])} / {len(manifests)}")
    print(f"Summary: {run_root / 'd2_1c_summary.json'}")
    print(f"Next: python backend/d2_1c_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
