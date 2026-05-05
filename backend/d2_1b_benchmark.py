"""d2_1b_benchmark.py -- D2.1B Stress Validation orchestrator.

Goal:
    With the harness validated by D2.1A (PASS), test whether the
    cognitive layer (GWT + MoodWorkspaceCoupling) actually changes
    behavior when stress is induced at the cognitive layer.

    Question:
        "Under controlled first-attempt validation failure, does
         ARM_ON (GWT enabled) exhibit different recovery dynamics
         vs ARM_OFF (GWT disabled)?"

Protocol:
    Reuses the D2.1A harness verbatim:
      - cached sources (D2_CACHED_SOURCES_PATH)
      - subprocess isolation (subprocess.run from Python)
      - per-run manifest with structural metrics
      - mood_history.jsonl archived per (topic, arm) with run_id

    What is new in D2.1B:
      - arms differ: ARM_OFF (no_l3=True) vs ARM_ON (no_l3=False)
      - stress injection at the cognitive layer:
          D2_STRESS_MODE=1
          D2_STRESS_PROFILE=controlled_validation_failure
        -> CertifyRetryGroup caps the score on attempt 1, forcing
           the agent into retry/recovery. No I/O failure, no fake
           exception -- pure cognitive pressure.

Topics:
    asyncio advanced patterns       (tactical positive control)
    python OOP design patterns      (realistic stress topic)

Manifest extends D2.1A's with:
    arm_kind                  ("ARM_OFF" / "ARM_ON")
    stress_mode               True
    stress_profile            "controlled_validation_failure"
    stress_injection_observed (True if [D2_STRESS] log marker found)

The verdict (PRESENT / ABSENT / INCONCLUSIVE / CONTAMINATED) is
produced by d2_1b_analyze.py.
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
RUNS_ROOT     = _ROOT / "shard_workspace" / "d2_1b_runs"
MOOD_HISTORY  = _ROOT / "shard_memory" / "mood_history.jsonl"

D2_TOPICS = [
    "asyncio advanced patterns",
    "python OOP design patterns",
]

# Two arms: GWT off vs GWT on. Stress injection applied to BOTH.
ARMS = [
    {"name": "ARM_OFF", "no_l3": True},
    {"name": "ARM_ON",  "no_l3": False},
]

SUBPROCESS_TIMEOUT = 1500   # 25 min per arm


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


def _run_one(topic: str, cache_path: Path, arm: dict, run_dir: Path,
             run_id: str, run_index_global: int, topic_index: int) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log    = run_dir / "stdout.log"
    stderr_log    = run_dir / "stderr.log"
    manifest_path = run_dir / "manifest.json"
    mood_path     = run_dir / "mood_samples.jsonl"

    cache       = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_hash  = cache.get("hash", "?")

    _reset_mood_history()
    started = time.time()
    started_iso = datetime.now().isoformat()
    print(f"\n[{run_id}] starting subprocess (arm={arm['name']}, no_l3={arm['no_l3']}, stress=ON)...")

    env = os.environ.copy()
    env["D2_CACHED_SOURCES_PATH"] = str(cache_path)
    env["D2_STRESS_MODE"]         = "1"
    env["D2_STRESS_PROFILE"]      = "controlled_validation_failure"
    env["PYTHONIOENCODING"]       = "utf-8"

    cmd = [
        sys.executable,
        str(_ROOT / "backend" / "night_runner.py"),
        "--cycles",        "1",
        "--timeout",       "30",
        "--pause",         "0",
        "--api-limit",     "200",
        "--topic-budget",  "30",
        "--force-topic",   topic,
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
        err = (exc.stderr or "") + f"\n[D2.1B] subprocess TIMEOUT after {SUBPROCESS_TIMEOUT}s"
        timeout_hit = True

    finished = time.time()
    finished_iso = datetime.now().isoformat()

    stdout_log.write_text(out, encoding="utf-8")
    stderr_log.write_text(err, encoding="utf-8")

    markers   = _count_markers(out + "\n" + err)
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
    elif markers["stress_injection_count"] == 0:
        abort_reason = "STRESS_INJECTION_NOT_OBSERVED"

    manifest = {
        "d2_version":               "D2.1B",
        "run_id":                   run_id,
        "run_index_global":         run_index_global,
        "topic_index":              topic_index,
        "arm":                      arm["name"],
        "arm_no_l3":                arm["no_l3"],
        "topic":                    topic,
        "source_mode":              "cached",
        "cache_path":               str(cache_path.relative_to(_ROOT)).replace("\\", "/"),
        "cache_hash":               cache_hash,
        "stress_mode":              True,
        "stress_profile":           "controlled_validation_failure",
        "stress_injection_observed": markers["stress_injection_count"] > 0,
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
          f"stress_obs={manifest['stress_injection_observed']}  retries={markers['retry_attempt_count']}  "
          f"contam={contaminated}")
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--abort-on-contam", action="store_true")
    args = p.parse_args()

    missing = []
    cache_files = {}
    for t in D2_TOPICS:
        f = CACHE_DIR / f"{_slug(t)}.json"
        if not f.exists():
            missing.append(str(f))
        else:
            cache_files[t] = f
    if missing:
        print("[D2.1B] Missing cache files:")
        for m in missing:
            print(f"  - {m}")
        print("[D2.1B] Run: python backend/d2_1a_cache_sources.py")
        sys.exit(2)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("D2.1B STRESS VALIDATION")
    print("=" * 70)
    print(f"Run root:        {run_root}")
    print(f"Topics:          {D2_TOPICS}")
    print(f"Arms:            {[a['name'] for a in ARMS]}  (ARM_OFF no_l3=True, ARM_ON no_l3=False)")
    print(f"Stress mode:     ON  profile=controlled_validation_failure")
    print(f"Subprocess timeout: {SUBPROCESS_TIMEOUT}s")
    print("=" * 70)

    manifests = []
    run_index_global = 0
    aborted = False

    for topic_index, topic in enumerate(D2_TOPICS, start=1):
        topic_dir = run_root / _slug(topic)
        for arm in ARMS:
            run_index_global += 1
            run_id = f"d2_1b_{_slug(topic)}_{arm['name'].lower()}_{run_index_global:03d}"
            arm_dir = topic_dir / arm["name"].lower()
            m = _run_one(
                topic=topic,
                cache_path=cache_files[topic],
                arm=arm,
                run_dir=arm_dir,
                run_id=run_id,
                run_index_global=run_index_global,
                topic_index=topic_index,
            )
            manifests.append(m)
            if args.abort_on_contam and m["contaminated"]:
                print(f"[D2.1B] ABORT: contaminated run ({m['abort_reason']})")
                aborted = True
                break
        if aborted:
            break

    summary = {
        "d2_version":   "D2.1B",
        "started_at":   manifests[0]["started_at"]  if manifests else None,
        "finished_at":  manifests[-1]["finished_at"] if manifests else None,
        "topics":       D2_TOPICS,
        "arms":         [a["name"] for a in ARMS],
        "stress_mode":  True,
        "stress_profile": "controlled_validation_failure",
        "aborted":      aborted,
        "manifests":    manifests,
    }
    (run_root / "d2_1b_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print(f"Total runs: {len(manifests)} / {len(D2_TOPICS) * len(ARMS)}")
    print(f"Contaminated: {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Stress observed: {sum(1 for m in manifests if m['stress_injection_observed'])} / {len(manifests)}")
    print(f"Summary: {run_root / 'd2_1b_summary.json'}")
    print(f"Next: python backend/d2_1b_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
