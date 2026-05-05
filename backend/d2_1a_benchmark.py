"""d2_1a_benchmark.py -- D2.1A Harness Validation orchestrator.

Goal:
    Validate the benchmark harness only. Do NOT test GWT, do NOT
    interpret cognitive layer. Answer one question:

        "Does single-pair + subprocess isolation + cached sources
         produce isolated, reproducible, uncontaminated runs?"

Protocol (Opzione X — replica check):
    For each topic in D2_TOPICS:
        For arm in [run_a, run_b]:                    # IDENTICAL config
            spawn fresh subprocess (subprocess.run)
            inject D2_CACHED_SOURCES_PATH env var
            capture stdout/stderr/exit_code
            write manifest.json with structural metrics

Layout:
    shard_workspace/d2_1a_runs/<TIMESTAMP>/
      <topic_slug>/
        run_a/
          stdout.log
          stderr.log
          manifest.json
          mood_samples.jsonl    (copy of shard_memory/mood_history.jsonl
                                 with run_id added per line)
        run_b/
          ...
      d2_1a_summary.json

Manifest fields (structural, NOT cognitive):
    d2_version, run_id, run_index_global, topic_index, arm,
    topic, source_mode, cache_path, cache_hash,
    subprocess_exit_code, started_at, finished_at, duration_seconds,
    ddgs_call_count, brave_call_count, playwright_call_count,
    fallback_count, http_error_count, mood_sample_count,
    contaminated, abort_reason

Contamination rule (per GPT-5.5):
    source_mode == 'cached' AND any of {ddgs, brave, playwright}
    call_count > 0  ->  contaminated = true

Verdict produced by d2_1a_analyze.py (separate file).
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

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

CACHE_DIR     = _ROOT / "shard_workspace" / "d2_cached_sources"
RUNS_ROOT     = _ROOT / "shard_workspace" / "d2_1a_runs"
MOOD_HISTORY  = _ROOT / "shard_memory" / "mood_history.jsonl"

D2_TOPICS = [
    "sql injection prevention python",
    "asyncio advanced patterns",
]

ARMS = ["run_a", "run_b"]   # identical config — replica check

# Per-subprocess timeout (seconds). Topic budget should fit comfortably.
SUBPROCESS_TIMEOUT = 1500   # 25 min hard ceiling


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _count_markers(text: str) -> dict:
    """Parse stdout for live-call markers + anomalous events.

    Convention from existing logs:
      - DDGS:        '[MAP] Smart queries' or 'ddgs.text' in trace
      - Playwright:  '[AGGREGATE] Scraping' or 'page.goto' in trace
      - Brave HTTP:  'search.brave.com'
      - Fallback:    plain '\\bfallback\\b' (excludes quantum_soul fallback)
      - HTTP err:    '\\b(429|500|502|503)\\b'
    Cache-hit markers ('[D2_CACHE_HIT_MAP]', '[D2_CACHE_HIT_AGGREGATE]')
    are recorded separately for sanity.
    """
    return {
        "ddgs_call_count":       len(re.findall(r"ddgs\.text|\[MAP\] Smart queries", text)),
        "brave_call_count":      len(re.findall(r"search\.brave\.com", text)),
        "playwright_call_count": len(re.findall(r"\[AGGREGATE\] Scraping|page\.goto", text)),
        "fallback_count":        len(re.findall(r"\bfallback\b(?!\s+su\s+simulazione)", text, re.I)),
        "http_error_count":      len(re.findall(r"\b(429|500|502|503)\b", text)),
        "cache_hit_map":         len(re.findall(r"\[D2_CACHE_HIT_MAP\]", text)),
        "cache_hit_aggregate":   len(re.findall(r"\[D2_CACHE_HIT_AGGREGATE\]", text)),
    }


def _archive_mood_history(target: Path, run_id: str) -> int:
    """Copy mood_history.jsonl to target with run_id embedded per line.

    Returns number of mood samples found. If history is missing, writes
    an empty file (PARTIAL flag is detected later by analyzer).
    """
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
    """Delete mood_history.jsonl so each subprocess writes its own clean trail."""
    if MOOD_HISTORY.exists():
        MOOD_HISTORY.unlink()


def _run_one(topic: str, cache_path: Path, run_dir: Path,
             run_id: str, run_index_global: int, topic_index: int, arm: str) -> dict:
    """Spawn a subprocess that runs night_runner on the topic with cached sources.

    Returns the populated manifest dict.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    manifest_path = run_dir / "manifest.json"
    mood_path     = run_dir / "mood_samples.jsonl"

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_hash = cache.get("hash", "?")

    _reset_mood_history()
    started = time.time()
    started_iso = datetime.now().isoformat()
    print(f"\n[{run_id}] starting subprocess (timeout={SUBPROCESS_TIMEOUT}s)...")

    env = os.environ.copy()
    env["D2_CACHED_SOURCES_PATH"] = str(cache_path)
    env["PYTHONIOENCODING"] = "utf-8"

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
        out = cp.stdout
        err = cp.stderr
        timeout_hit = False
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        out = (exc.stdout or "")
        err = (exc.stderr or "") + f"\n[D2.1A] subprocess TIMEOUT after {SUBPROCESS_TIMEOUT}s"
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
        abort_reason = "FALLBACK_THRESHOLD_EXCEEDED"
        contaminated = True
    elif markers["http_error_count"] > 3:
        abort_reason = "HTTP_ERROR_THRESHOLD_EXCEEDED"
        contaminated = True

    manifest = {
        "d2_version":             "D2.1A",
        "run_id":                 run_id,
        "run_index_global":       run_index_global,
        "topic_index":            topic_index,
        "arm":                    arm,
        "topic":                  topic,
        "source_mode":            "cached",
        "cache_path":             str(cache_path.relative_to(_ROOT)).replace("\\", "/"),
        "cache_hash":             cache_hash,
        "subprocess_exit_code":   exit_code,
        "started_at":             started_iso,
        "finished_at":            finished_iso,
        "duration_seconds":       round(finished - started, 1),
        "mood_sample_count":      mood_count,
        "contaminated":           contaminated,
        "abort_reason":           abort_reason,
        **markers,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[{run_id}] exit={exit_code}  duration={manifest['duration_seconds']}s  "
          f"cache_hits=({markers['cache_hit_map']},{markers['cache_hit_aggregate']})  "
          f"contaminated={contaminated}")
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--abort-on-contam", action="store_true",
                   help="stop the run as soon as a contaminated arm is detected")
    args = p.parse_args()

    # Verify cache exists for every topic before starting
    missing = []
    cache_files = {}
    for t in D2_TOPICS:
        f = CACHE_DIR / f"{_slug(t)}.json"
        if not f.exists():
            missing.append(str(f))
        else:
            cache_files[t] = f
    if missing:
        print("[D2.1A] Missing cache files:")
        for m in missing:
            print(f"  - {m}")
        print("[D2.1A] Run: python backend/d2_1a_cache_sources.py")
        sys.exit(2)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("D2.1A HARNESS VALIDATION")
    print("=" * 70)
    print(f"Run root:   {run_root}")
    print(f"Topics:     {D2_TOPICS}")
    print(f"Arms:       {ARMS}  (identical config — replica check)")
    print(f"Subprocess timeout: {SUBPROCESS_TIMEOUT}s")
    print("=" * 70)

    manifests = []
    run_index_global = 0
    aborted = False

    for topic_index, topic in enumerate(D2_TOPICS, start=1):
        topic_dir = run_root / _slug(topic)
        for arm in ARMS:
            run_index_global += 1
            run_id = f"d2_1a_{_slug(topic)}_{arm}_{run_index_global:03d}"
            run_dir = topic_dir / arm
            m = _run_one(
                topic=topic,
                cache_path=cache_files[topic],
                run_dir=run_dir,
                run_id=run_id,
                run_index_global=run_index_global,
                topic_index=topic_index,
                arm=arm,
            )
            manifests.append(m)
            if args.abort_on_contam and m["contaminated"]:
                print(f"[D2.1A] ABORT: contaminated run detected ({m['abort_reason']})")
                aborted = True
                break
        if aborted:
            break

    summary = {
        "d2_version":   "D2.1A",
        "started_at":   manifests[0]["started_at"]  if manifests else None,
        "finished_at":  manifests[-1]["finished_at"] if manifests else None,
        "topics":       D2_TOPICS,
        "arms":         ARMS,
        "aborted":      aborted,
        "manifests":    manifests,
    }
    (run_root / "d2_1a_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print(f"Total runs: {len(manifests)} / {len(D2_TOPICS) * len(ARMS)}")
    print(f"Contaminated runs: {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Summary: {run_root / 'd2_1a_summary.json'}")
    print(f"Next: python backend/d2_1a_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
