"""ab_test_runner.py -- A/B/C test for strategy signal causal contribution.

Runs each task under 3 conditions:
  A -- baseline : strategy excluded entirely
  B -- normal   : strategy competes in gate (current default)
  C -- forced   : strategy always gets slot 1, top-2 others fill slots 2-3

Metrics collected per condition per task:
  - success          : bool
  - attempts         : int (total attempts used)
  - strategy_activated: bool (was strategy signal in top-3?)
  - strategy_score   : float (gate score of strategy signal)
  - final_code_hash  : md5 of final produced code (to detect output differences)

Outputs:
  - Console table with per-task per-condition results
  - ab_results.json in shard_workspace/
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

# Add backend to path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_loop import run_benchmark_loop

_RESULTS_FILE = _ROOT / "shard_workspace" / "ab_results.json"

CONDITIONS = ["baseline", "normal", "forced"]

logger = logging.getLogger("shard.ab_test")


def _hash(code: str) -> str:
    return hashlib.md5(code.encode()).hexdigest()[:8]


async def run_condition(task_dir: Path, condition: str, max_attempts: int) -> dict:
    """Run one task under one condition. Returns metrics dict."""
    t0 = time.time()
    try:
        result = await run_benchmark_loop(
            task_dir,
            max_attempts=max_attempts,
            strategy_mode=condition,
        )
        return {
            "condition": condition,
            "task": task_dir.name,
            "success": result.success,
            "attempts": result.total_attempts,
            "strategy_activated": result.strategy_activated,
            "strategy_score": round(result.strategy_score, 3),
            "strategy_text": result.strategy_text,
            "final_code_hash": _hash(result.final_code),
            "elapsed": round(time.time() - t0, 1),
        }
    except Exception as e:
        logger.error("[ab] %s/%s failed: %s", task_dir.name, condition, e)
        return {
            "condition": condition,
            "task": task_dir.name,
            "success": False,
            "attempts": -1,
            "strategy_activated": False,
            "strategy_score": 0.0,
            "final_code_hash": "error",
            "elapsed": round(time.time() - t0, 1),
            "error": str(e),
        }


def _print_table(results: list[dict]) -> None:
    tasks = sorted(set(r["task"] for r in results))
    # Header
    print()
    print(f"{'TASK':<32}  {'A-baseline':^14}  {'B-normal':^14}  {'C-forced':^14}  DIFF")
    print("-" * 100)
    for task in tasks:
        row = {r["condition"]: r for r in results if r["task"] == task}
        cells = []
        hashes = []
        for cond in CONDITIONS:
            r = row.get(cond)
            if not r:
                cells.append(f"{'--':^14}")
                hashes.append("?")
                continue
            mark = "PASS" if r["success"] else "FAIL"
            att  = r["attempts"] if r["attempts"] > 0 else "err"
            act  = "S+" if r["strategy_activated"] else "S-"
            cells.append(f"{mark} {att}att {act}".center(14))
            hashes.append(r["final_code_hash"])
        # Output diff: how many hashes differ
        unique_hashes = len(set(h for h in hashes if h not in ("?", "error")))
        diff_tag = f"{unique_hashes} unique outputs" if unique_hashes > 1 else "same output"
        print(f"{task:<32}  {'  '.join(cells)}  {diff_tag}")
    # Print strategy_text for tasks where output differs (diagnostic insight)
    tasks_with_diff = [
        task for task in tasks
        if len(set(
            r["final_code_hash"] for r in results
            if r["task"] == task and r["final_code_hash"] not in ("?", "error")
        )) > 1
    ]
    if tasks_with_diff:
        print("--- Strategy text (tasks with output diff) ---")
        for task in tasks_with_diff:
            for cond in ["normal", "forced"]:
                r = next((r for r in results if r["task"] == task and r["condition"] == cond), None)
                if r and r.get("strategy_text"):
                    print(f"\n  [{task} / {cond}]")
                    print(f"  {r['strategy_text'][:300].strip()}")
        print()

    print()
    # Summary
    for cond in CONDITIONS:
        cond_results = [r for r in results if r["condition"] == cond]
        wins = sum(1 for r in cond_results if r["success"])
        avg_att = sum(r["attempts"] for r in cond_results if r["attempts"] > 0) / max(1, len([r for r in cond_results if r["attempts"] > 0]))
        act_rate = sum(1 for r in cond_results if r["strategy_activated"]) / max(1, len(cond_results))
        print(f"  {cond:<10}: {wins}/{len(cond_results)} wins  avg_attempts={avg_att:.1f}  strategy_activation={act_rate:.0%}")
    print()


async def main_async(task_dirs: list[Path], max_attempts: int, conditions: list[str]) -> None:
    all_results: list[dict] = []

    for task_dir in task_dirs:
        print(f"\n{'='*68}")
        print(f"A/B TEST: {task_dir.name}")
        print(f"{'='*68}")
        for cond in conditions:
            print(f"\n--- Condition: {cond.upper()} ---")
            r = await run_condition(task_dir, cond, max_attempts)
            all_results.append(r)
            mark = "PASS" if r["success"] else "FAIL"
            print(f"  >> {mark} in {r['attempts']} attempts | strategy={'ON' if r['strategy_activated'] else 'OFF'} score={r['strategy_score']:.3f} | hash={r['final_code_hash']}")

    # Save results
    _RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if _RESULTS_FILE.exists():
        try:
            existing = json.loads(_RESULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.extend(all_results)
    _RESULTS_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results saved -> {_RESULTS_FILE}")

    _print_table(all_results)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A/B/C causal test for strategy signal in SHARD"
    )
    parser.add_argument(
        "tasks", nargs="*",
        help="Task directory names or paths (default: all 12 tasks)"
    )
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument(
        "--conditions", nargs="+",
        choices=CONDITIONS, default=CONDITIONS,
        help="Conditions to run (default: all three)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv(_ROOT / ".env")
    except ImportError:
        pass

    benchmark_root = _ROOT / "benchmark"

    if args.tasks:
        task_dirs = []
        for t in args.tasks:
            p = Path(t)
            if not p.is_absolute():
                p = benchmark_root / t
            if not p.exists():
                print(f"[ab] Task not found: {p}", file=sys.stderr)
                sys.exit(1)
            task_dirs.append(p.resolve())
    else:
        task_dirs = sorted(
            d for d in benchmark_root.iterdir()
            if d.is_dir() and d.name.startswith("task_")
        )

    if not task_dirs:
        print("[ab] No tasks found.", file=sys.stderr)
        sys.exit(1)

    print(f"[ab] Running {len(args.conditions)} conditions × {len(task_dirs)} tasks")
    asyncio.run(main_async(task_dirs, args.max_attempts, args.conditions))


if __name__ == "__main__":
    main()
