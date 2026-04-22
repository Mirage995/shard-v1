"""lobotomy_full_benchmark.py — A/B test: FULL brain vs LOBOTOMY on benchmark tasks.

FULL:     relational_context() returns all layers (Identity, Experience, Knowledge, Tensions, ...)
LOBOTOMY: relational_context() returns only Anchor + Executive (Layer 0+1)

For each task we run FULL first, then reset episodic state, then run LOBOTOMY.
Results saved to shard_workspace/lobotomy_results.json.

Usage:
    python backend/lobotomy_full_benchmark.py
    python backend/lobotomy_full_benchmark.py --tasks task_01 task_06 task_10
    python backend/lobotomy_full_benchmark.py --n 14
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

RESULTS_PATH = _ROOT / "shard_workspace" / "lobotomy_results.json"

# Default task list (14 tasks)
DEFAULT_TASKS = [
    "task_01_html_trap",
    "task_02_ghost_bug",
    "task_03_dirty_data",
    "task_04_race_condition",
    "task_05_state_mutation",
    "task_06_ttl_cache",
    "task_07_metrics_bleed",
    "task_08_multi_file_labyrinth",
    "task_09_ghost_mutation",
    "task_10_template_parser",
    "task_11_stream_decoder",
    "task_12_note_tag",
    "task_13_config_parser",
    "task_14_boundary_check",
]

BENCHMARK_DIR = _ROOT / "benchmark"


def _build_consciousness():
    """Build a minimal CognitionCore for injection into benchmark_loop."""
    try:
        from cognition.cognition_core import CognitionCore
        return CognitionCore()
    except Exception as exc:
        print(f"[LOBOTOMY] WARNING: could not build CognitionCore: {exc}")
        return None


def _reset_episodic_cache(consciousness, task_name: str) -> None:
    """Clear episodic memory for task_name so RUN B starts cold."""
    try:
        if consciousness and consciousness._episodic_memory is not None:
            mem = consciousness._episodic_memory
            if hasattr(mem, "clear_topic"):
                mem.clear_topic(task_name)
                print(f"  [episodic] cleared cache for '{task_name}'")
    except Exception as exc:
        print(f"  [episodic] cache reset failed (non-fatal): {exc}")


async def _run_one(task_dir: Path, consciousness, condition: str, max_attempts: int = 3) -> dict:
    """Run a single task in the given condition. Returns result dict."""
    from benchmark_loop import run_benchmark_loop, set_consciousness

    strategy_mode = "baseline" if condition == "LOBOTOMY" else "normal"
    set_consciousness(consciousness)

    t0 = time.time()
    result = await run_benchmark_loop(
        task_dir=task_dir,
        max_attempts=max_attempts,
        use_episodic_memory=(condition == "FULL"),
        strategy_mode=strategy_mode,
    )
    elapsed = round(time.time() - t0, 1)

    return {
        "condition": condition,
        "success": result.success,
        "score": result.score if hasattr(result, "score") else (10.0 if result.success else 0.0),
        "attempts": result.attempts if hasattr(result, "attempts") else None,
        "elapsed_s": elapsed,
    }


async def run_ab(task_names: list[str], max_attempts: int = 3) -> list[dict]:
    consciousness = _build_consciousness()

    results = []
    for task_name in task_names:
        task_dir = BENCHMARK_DIR / task_name
        if not task_dir.exists():
            print(f"[LOBOTOMY] SKIP {task_name} — directory not found")
            continue

        print(f"\n{'='*60}")
        print(f"[LOBOTOMY] Task: {task_name}")

        # RUN A — FULL brain
        print(f"\n  --- RUN A: FULL ---")
        if consciousness:
            consciousness.set_lobotomy(False)
        run_a = await _run_one(task_dir, consciousness, "FULL", max_attempts)
        print(f"  [A] success={run_a['success']} score={run_a['score']} ({run_a['elapsed_s']}s)")

        # Reset episodic cache between conditions
        _reset_episodic_cache(consciousness, task_name)

        # RUN B — LOBOTOMY
        print(f"\n  --- RUN B: LOBOTOMY ---")
        if consciousness:
            consciousness.set_lobotomy(True)
        run_b = await _run_one(task_dir, consciousness, "LOBOTOMY", max_attempts)
        print(f"  [B] success={run_b['success']} score={run_b['score']} ({run_b['elapsed_s']}s)")

        # Restore to FULL after task
        if consciousness:
            consciousness.set_lobotomy(False)

        delta = round(run_a["score"] - run_b["score"], 2)
        print(f"\n  [DELTA] FULL={run_a['score']} LOBOTOMY={run_b['score']} delta={delta:+.2f}")

        results.append({
            "task": task_name,
            "full":     run_a,
            "lobotomy": run_b,
            "delta_score": delta,
            "full_wins": run_a["score"] > run_b["score"],
        })

    return results


def _summary(results: list[dict]) -> dict:
    if not results:
        return {}
    full_scores = [r["full"]["score"] for r in results]
    lob_scores  = [r["lobotomy"]["score"] for r in results]
    full_wins   = sum(1 for r in results if r["full_wins"])
    n = len(results)
    avg_full = round(sum(full_scores) / n, 3)
    avg_lob  = round(sum(lob_scores) / n, 3)
    avg_delta = round(avg_full - avg_lob, 3)

    return {
        "n_tasks":        n,
        "full_wins":      full_wins,
        "lobotomy_wins":  n - full_wins,
        "avg_score_full": avg_full,
        "avg_score_lob":  avg_lob,
        "avg_delta":      avg_delta,
        "verdict": (
            "FULL BRAIN WINS" if avg_delta > 0.3 else
            "NO SIGNIFICANT DIFFERENCE" if abs(avg_delta) <= 0.3 else
            "LOBOTOMY WINS (unexpected)"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Lobotomy A/B benchmark")
    parser.add_argument("--tasks", nargs="+", help="Task names to run (default: all 14)")
    parser.add_argument("--n", type=int, default=None, help="Run first N default tasks")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    if args.tasks:
        task_names = args.tasks
    elif args.n:
        task_names = DEFAULT_TASKS[: args.n]
    else:
        task_names = DEFAULT_TASKS

    print(f"[LOBOTOMY] Running A/B test on {len(task_names)} tasks")
    print(f"[LOBOTOMY] Tasks: {task_names}")

    results = asyncio.run(run_ab(task_names, max_attempts=args.max_attempts))
    summary = _summary(results)

    output = {
        "run_at": __import__("datetime").datetime.now().isoformat(),
        "summary": summary,
        "tasks": results,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"[LOBOTOMY] SUMMARY")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n[LOBOTOMY] Results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
