"""validation_protocol.py -- Empirical validation: does SHARD study improve benchmark?

Protocol:
  1. BASELINE  -- run task N times without prior study
  2. STUDY     -- SHARD studies the relevant topic
  3. POST      -- run same task N times after study
  4. COMPARE   -- statistical comparison of attempts-to-solve

Usage:
    cd backend
    python ../benchmark/validation_protocol.py --task task_03_dirty_data --runs 3

Output:
    benchmark/experiments/validation_<task>_<timestamp>.json
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

BENCHMARK_DIR = Path(__file__).parent
EXPERIMENTS_DIR = BENCHMARK_DIR / "experiments"
EXPERIMENTS_DIR.mkdir(exist_ok=True)

BENCHMARK_LOOP = Path(__file__).parent.parent / "backend" / "benchmark_loop.py"


def run_benchmark_once(task_dir: Path, run_id: int) -> dict:
    """Run benchmark_loop.py on task_dir, return result dict."""
    # Reset the output file to force a fresh attempt
    task_name = task_dir.name
    source_file, output_file = _get_task_files(task_dir)

    if output_file and output_file.exists():
        output_file.unlink()
        print(f"    Cleared {output_file.name}")

    t0 = time.time()
    result = subprocess.run(
        [sys.executable, str(BENCHMARK_LOOP), str(task_dir), "--max-attempts", "5"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent.parent / "backend"),
        timeout=300,
    )
    elapsed = time.time() - t0

    output = result.stdout + result.stderr

    # Parse result
    victory = "VICTORY" in output
    attempts = _parse_attempts(output)
    tests_passed = _parse_tests_passed(output)

    print(f"    Run {run_id}: {'PASS' if victory else 'FAIL'} | attempts={attempts} | tests={tests_passed} | {elapsed:.1f}s")

    return {
        "run_id": run_id,
        "victory": victory,
        "attempts": attempts,
        "tests_passed": tests_passed,
        "elapsed_sec": round(elapsed, 1),
        "raw_output": output[-2000:],  # last 2000 chars
    }


def _get_task_files(task_dir: Path):
    """Find (source_file, output_file) for a task."""
    readme = (task_dir / "README.md").read_text(encoding="utf-8", errors="ignore")
    import re
    # Look for "source -> output" pattern
    m = re.search(r"Source:\s*(\S+)\s*->\s*(\S+)", readme)
    if m:
        return task_dir / m.group(1), task_dir / m.group(2)
    # Fallback: find fixed_*.py
    fixed = list(task_dir.glob("fixed_*.py")) + list(task_dir.glob("optimized_*.py")) + list(task_dir.glob("refactored_*.py"))
    if fixed:
        return None, fixed[0]
    return None, None


def _parse_attempts(output: str) -> int:
    import re
    m = re.search(r"VICTORY on attempt (\d+)/", output)
    if m:
        return int(m.group(1))
    m = re.search(r"Attempt (\d+)/\d+", output)
    if m:
        # find last attempt number mentioned
        all_attempts = re.findall(r"Attempt (\d+)/\d+", output)
        return int(all_attempts[-1]) if all_attempts else 5
    return 5  # assume max if can't parse


def _parse_tests_passed(output: str) -> int:
    import re
    m = re.search(r"Tests passed: (\d+)", output)
    if m:
        return int(m.group(1))
    m = re.search(r"ALL PASSED \((\d+) tests\)", output)
    if m:
        return int(m.group(1))
    return 0


def build_task_context(task_dir: Path) -> str:
    """Read README + legacy/source code + test file and build a compact context string.

    This is the authoritative signal SHARD uses to study — not random web pages.
    """
    parts = []

    # README
    readme = task_dir / "README.md"
    if readme.exists():
        parts.append("=== TASK README ===\n" + readme.read_text(encoding="utf-8", errors="ignore"))

    # Legacy / source code (the file to fix/optimize)
    for pattern in ["legacy_*.py", "buggy_*.py", "cache.py", "*.py"]:
        candidates = [
            f for f in task_dir.glob(pattern)
            if not f.name.startswith("fixed_")
            and not f.name.startswith("optimized_")
            and not f.name.startswith("refactored_")
            and not f.name.startswith("test_")
        ]
        if candidates:
            src = candidates[0]
            parts.append(f"=== SOURCE CODE ({src.name}) ===\n" + src.read_text(encoding="utf-8", errors="ignore"))
            break

    # Test file
    tests = list(task_dir.glob("test_*.py"))
    if tests:
        parts.append(f"=== TEST FILE ({tests[0].name}) ===\n" + tests[0].read_text(encoding="utf-8", errors="ignore"))

    context = "\n\n".join(parts)
    # Cap at 12k chars to stay within LLM context budget
    if len(context) > 12000:
        context = context[:12000] + "\n...[truncated]"
    return context


async def run_study(topic: str, task_dir: Path) -> dict:
    """Run SHARD study on topic with task context injected, return result summary."""
    print(f"\n  Studying topic: '{topic}'...")
    from study_agent import StudyAgent

    task_context = build_task_context(task_dir)
    if task_context:
        print(f"  Task context: {len(task_context)} chars injected")

    agent = StudyAgent()
    t0 = time.time()

    result = await agent.study_topic(
        topic=topic,
        tier=1,
        on_progress=None,
        task_context=task_context,
    )
    elapsed = time.time() - t0

    score = result.get("score", 0) if isinstance(result, dict) else 0
    certified = result.get("certified", False) if isinstance(result, dict) else False
    bench = result.get("benchmark_result") if isinstance(result, dict) else None

    cert_symbol = "CERTIFIED" if certified else "NOT CERTIFIED"
    bench_str = ""
    if bench:
        bench_str = f" | bench={bench.get('passed',0)}/{bench.get('total',0)} ({bench.get('pass_rate',0):.0%})"
    print(f"  Study complete: score={score}/10 {cert_symbol}{bench_str} ({elapsed:.1f}s)")

    return {
        "topic":            topic,
        "score":            score,
        "certified":        certified,
        "elapsed_sec":      round(elapsed, 1),
        "benchmark_result": bench,
    }


def cert_quality_report(study_result: dict) -> dict:
    """Evaluate certification quality from the study phase directly.

    Replaces the external benchmark_loop comparison for topics where the loop
    always resolves at attempt 1 (cached strategies → NO_CHANGE every time).
    Measures what the study phase actually produced:
      - score & certified flag
      - post-certify benchmark pass_rate (real code execution in Docker)
    """
    score     = study_result.get("score", 0.0)
    certified = study_result.get("certified", False)
    bench     = study_result.get("benchmark_result") or {}

    pass_rate = bench.get("pass_rate", None)
    passed    = bench.get("passed", 0)
    total     = bench.get("total", 0)
    bench_available = total > 0

    # Quality verdict
    if not certified:
        verdict = "FAIL_NO_CERT"
    elif not bench_available:
        verdict = "CERT_NO_BENCH"        # certified but no benchmark ran (Docker unavailable)
    elif pass_rate >= 0.8:
        verdict = "CERT_HIGH_QUALITY"    # certified + ≥80% benchmark tests pass
    elif pass_rate >= 0.4:
        verdict = "CERT_PARTIAL"         # certified + 40-79% pass
    else:
        verdict = "CERT_LOW_BENCH"       # certified but benchmark mostly fails

    return {
        "score":           score,
        "certified":       certified,
        "bench_pass_rate": pass_rate,
        "bench_passed":    passed,
        "bench_total":     total,
        "bench_available": bench_available,
        "verdict":         verdict,
    }


def compare_results(baseline_runs: list, post_runs: list) -> dict:
    """Statistical comparison of baseline vs post-study runs."""
    def stats(runs):
        attempts = [r["attempts"] for r in runs]
        victories = sum(1 for r in runs if r["victory"])
        return {
            "n": len(runs),
            "victories": victories,
            "win_rate": round(victories / len(runs), 2) if runs else 0,
            "mean_attempts": round(sum(attempts) / len(attempts), 2) if attempts else 0,
            "attempts_list": attempts,
        }

    base = stats(baseline_runs)
    post = stats(post_runs)

    delta_win_rate = post["win_rate"] - base["win_rate"]
    delta_attempts = base["mean_attempts"] - post["mean_attempts"]  # positive = improvement

    verdict = "INCONCLUSIVE"
    if delta_win_rate > 0 and delta_attempts > 0:
        verdict = "IMPROVEMENT"
    elif delta_win_rate < 0 or delta_attempts < -0.5:
        verdict = "REGRESSION"
    elif abs(delta_win_rate) < 0.1 and abs(delta_attempts) < 0.3:
        verdict = "NO_CHANGE"

    return {
        "baseline": base,
        "post_study": post,
        "delta_win_rate": round(delta_win_rate, 2),
        "delta_attempts": round(delta_attempts, 2),
        "verdict": verdict,
        "interpretation": _interpret(verdict, delta_win_rate, delta_attempts),
    }


def _interpret(verdict: str, delta_wr: float, delta_att: float) -> str:
    if verdict == "IMPROVEMENT":
        return (
            f"SHARD study improved performance: "
            f"win rate {'+' if delta_wr >= 0 else ''}{delta_wr*100:.0f}pp, "
            f"attempts {'+' if delta_att >= 0 else ''}{delta_att:.1f} fewer."
        )
    elif verdict == "REGRESSION":
        return "Post-study performance WORSE than baseline. Possible prompt pollution or noise."
    elif verdict == "NO_CHANGE":
        return "No measurable difference. Topic may not be directly relevant to task mechanics."
    else:
        return "Mixed signals. More runs needed for statistical significance."


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, help="Task dir name, e.g. task_03_dirty_data")
    parser.add_argument("--topic", default=None, help="Study topic (default: inferred from task)")
    parser.add_argument("--runs", type=int, default=3, help="Runs per phase (default: 3)")
    parser.add_argument("--skip-study", action="store_true", help="Skip study phase (baseline only)")
    parser.add_argument("--cert-only",  action="store_true", help="Only run study + cert quality report (no benchmark_loop runs)")
    args = parser.parse_args()

    task_dir = BENCHMARK_DIR / args.task
    if not task_dir.exists():
        print(f"ERROR: {task_dir} not found")
        sys.exit(1)

    # Infer topic from task if not provided
    topic = args.topic or _infer_topic(args.task)
    print(f"\n{'='*60}")
    print(f"  SHARD Validation Protocol")
    print(f"  Task:   {args.task}")
    print(f"  Topic:  {topic}")
    print(f"  Runs:   {args.runs} per phase")
    print(f"{'='*60}")

    experiment = {
        "task": args.task,
        "topic": topic,
        "runs_per_phase": args.runs,
        "started_at": datetime.now().isoformat(),
        "baseline_runs": [],
        "study_result": None,
        "post_study_runs": [],
        "comparison": None,
    }

    if args.cert_only:
        # Fast path: just study + cert quality report (no benchmark_loop runs)
        print(f"\n[CERT-ONLY MODE] Skipping benchmark_loop runs")
        print(f"\n[PHASE 1/1] SHARD STUDY — '{topic}'")
        study = await run_study(topic, task_dir)
        experiment["study_result"] = study

        cert_report = cert_quality_report(study)
        experiment["cert_quality"] = cert_report
        experiment["finished_at"] = datetime.now().isoformat()
        _save(experiment, args.task)

        print(f"\n{'='*60}")
        print(f"  CERT QUALITY REPORT")
        print(f"{'='*60}")
        print(f"  Score:      {cert_report['score']}/10")
        print(f"  Certified:  {cert_report['certified']}")
        if cert_report["bench_available"]:
            print(f"  Benchmark:  {cert_report['bench_passed']}/{cert_report['bench_total']} passed ({cert_report['bench_pass_rate']:.0%})")
        else:
            print(f"  Benchmark:  not available (Docker may be offline)")
        print(f"  VERDICT: {cert_report['verdict']}")
        print(f"{'='*60}")
        return

    # Phase 1: Baseline
    print(f"\n[PHASE 1/3] BASELINE ({args.runs} runs, no study)")
    for i in range(1, args.runs + 1):
        run = run_benchmark_once(task_dir, i)
        experiment["baseline_runs"].append(run)
        _save(experiment, args.task)

    # Phase 2: Study
    if not args.skip_study:
        print(f"\n[PHASE 2/3] SHARD STUDY — '{topic}'")
        study = await run_study(topic, task_dir)
        experiment["study_result"] = study

        # Also compute cert quality report (even in full mode)
        experiment["cert_quality"] = cert_quality_report(study)
        _save(experiment, args.task)
    else:
        print("\n[PHASE 2/3] STUDY SKIPPED")

    # Phase 3: Post-study
    print(f"\n[PHASE 3/3] POST-STUDY ({args.runs} runs)")
    for i in range(1, args.runs + 1):
        run = run_benchmark_once(task_dir, i)
        experiment["post_study_runs"].append(run)
        _save(experiment, args.task)

    # Compare
    comparison = compare_results(experiment["baseline_runs"], experiment["post_study_runs"])
    experiment["comparison"] = comparison
    experiment["finished_at"] = datetime.now().isoformat()
    _save(experiment, args.task)

    # Print verdict
    cert_q = experiment.get("cert_quality", {})
    print(f"\n{'='*60}")
    print(f"  VALIDATION RESULT")
    print(f"{'='*60}")
    print(f"  Baseline:   win={comparison['baseline']['win_rate']*100:.0f}%  avg_attempts={comparison['baseline']['mean_attempts']}")
    print(f"  Post-study: win={comparison['post_study']['win_rate']*100:.0f}%  avg_attempts={comparison['post_study']['mean_attempts']}")
    print(f"  Delta win rate: {comparison['delta_win_rate']:+.0%}")
    print(f"  Delta attempts: {comparison['delta_attempts']:+.1f}")
    print(f"  VERDICT: {comparison['verdict']}")
    print(f"  {comparison['interpretation']}")
    if cert_q:
        print(f"\n  CERT QUALITY: score={cert_q.get('score')}/10 | certified={cert_q.get('certified')} | bench={cert_q.get('bench_passed',0)}/{cert_q.get('bench_total',0)} | {cert_q.get('verdict','N/A')}")
    print(f"{'='*60}")


def _infer_topic(task_name: str) -> str:
    topics = {
        "task_01_html_trap":        "Python HTML parsing BeautifulSoup traps",
        "task_02_ghost_bug":        "Python pipeline bug detection calibration",
        "task_03_dirty_data":       "Python defaultdict Counter comprehension optimization",
        "task_04_race_condition":   "Python threading race conditions locks",
        "task_05_state_mutation":   "Python mutable state side effects",
        "task_06_ttl_cache":        "Python TTL cache expiration implementation",
        "task_07_metrics_bleed":    "Python metrics isolation test independence",
        "task_09_ghost_mutation":   "Python ghost mutation data processor",
        "task_10_template_parser":  "Python string template substitution regex custom delimiters",
        "task_13_config_parser":    "Python config parser edge cases",
    }
    return topics.get(task_name, task_name.replace("_", " "))


def _save(experiment: dict, task_name: str):
    ts = experiment["started_at"][:19].replace(":", "-")
    path = EXPERIMENTS_DIR / f"validation_{task_name}_{ts}.json"
    path.write_text(json.dumps(experiment, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
