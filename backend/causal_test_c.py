"""causal_test_c.py -- Test C: Does the SYSTEM learn, or is it the LLM?

Hypothesis: a strategy learned from task_02 (idempotency guard) transfers
to a structurally similar but domain-different task (task_05_state_mutation).
The LLM has zero memory of previous sessions -- if B > C, it is the SYSTEM.

Conditions (run on task_05, not task_02):
  A - baseline  : task_05, no strategy at all
  B - transfer  : task_05 + idempotency strategy from task_02 (forced)
  C - fake      : task_05 + fake strategy (same length, generic content)

Interpretation:
  B > C  -> pattern generalization works -- SHARD learned, not LLM memory
  B == C -> pattern too specific, doesn't transfer
  B < C  -> strategy from task_02 actively interferes with task_05

Run:
  cd backend && python causal_test_c.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TASK = Path(__file__).resolve().parent.parent / "benchmark" / "task_09_ghost_mutation"
MAX_ATTEMPTS = 5
RUNS_PER_CONDITION = 3

# The real strategy extracted from task_02 -- injected manually into task_05
TRANSFER_STRATEGY = """\
[STRATEGY - HIGH CONFIDENCE]

You MUST apply this approach to fix the failing test(s) -- apply ONLY if relevant to the current bug pattern:

Focus on: state mutation and transformation guards

1. Add idempotency guard: check a flag before applying a transformation, skip if already done
2. Ensure state is not mutated more than once across multiple calls
3. Use a boolean flag (e.g. `_applied`, `_processed`) initialized to False, set to True after first application

FAILURE CONDITION:
If this approach is not applied, the failing tests will not pass.\
"""

FAKE_STRATEGY = """\
[STRATEGY - HIGH CONFIDENCE]

You MUST apply this approach to fix the failing test(s) -- apply ONLY if relevant to the current bug pattern:

Focus on: `process_data()`

1. Consider using a standard formatting approach for the output values
Ensure that the return type matches the expected interface specifications
Apply consistent naming conventions throughout the implementation

FAILURE CONDITION:
If this approach is not applied, the failing tests will not pass.\
"""


def _patch_strategy(signal_gate_module, content, label):
    original = signal_gate_module.build_strategy_signal

    def forced_build(strategies):
        real = original(strategies)
        conf = real.confidence if real else 1.07
        from signal_gate import Signal
        return Signal(
            content=content,
            confidence=conf,
            type="strategy",
            source=label,
        )

    signal_gate_module.build_strategy_signal = forced_build
    return original


def _restore(signal_gate_module, original):
    signal_gate_module.build_strategy_signal = original


async def run_condition(label, strategy_mode, patch_content=None, patch_label=None):
    import signal_gate as sg
    from benchmark_loop import run_benchmark_loop

    original = None
    if patch_content:
        original = _patch_strategy(sg, patch_content, patch_label or label)

    results = []
    for i in range(RUNS_PER_CONDITION):
        print(f"  [{label}] run {i+1}/{RUNS_PER_CONDITION}...")
        r = await run_benchmark_loop(
            task_dir=TASK,
            max_attempts=MAX_ATTEMPTS,
            use_episodic_memory=True,
            strategy_mode=strategy_mode,
        )
        results.append({
            "success": r.success,
            "attempts": r.total_attempts,
            "strategy_activated": r.strategy_activated,
        })
        print(f"    -> {'PASS' if r.success else 'FAIL'} in {r.total_attempts} att | strategy={r.strategy_activated}")

    if original:
        _restore(sg, original)

    wins_at_1 = sum(1 for r in results if r["success"] and r["attempts"] == 1)
    avg_att   = sum(r["attempts"] for r in results) / len(results)
    return {
        "label": label,
        "wins_at_1": wins_at_1,
        "avg_attempts": round(avg_att, 2),
        "all_results": results,
    }


async def main():
    print("=" * 60)
    print("CAUSAL TEST C -- Does the SYSTEM learn, or is it the LLM?")
    print(f"Task: {TASK.name} | {RUNS_PER_CONDITION} runs per condition")
    print(f"Transfer strategy: task_02 idempotency guard -> task_05")
    print("=" * 60)
    print()

    conditions = [
        ("A-baseline", "baseline", None,              None),
        ("B-transfer", "forced",   TRANSFER_STRATEGY, "TRANSFER from task_02 idempotency"),
        ("C-fake",     "forced",   FAKE_STRATEGY,     "FAKE (same length, generic)"),
    ]

    summary = []
    for label, mode, patch_content, patch_label in conditions:
        print(f"\n{'='*40}")
        print(f"CONDITION: {label}")
        print(f"{'='*40}")
        res = await run_condition(label, mode, patch_content, patch_label)
        summary.append(res)

    print("\n\n" + "=" * 60)
    print("RESULTS  [task_05_state_mutation | provider: Gemini]")
    print("=" * 60)
    print(f"{'Condition':<22} {'Wins@1':>8} {'Avg att':>10}  Verdict")
    print("-" * 60)
    for r in summary:
        wins = r["wins_at_1"]
        avg  = r["avg_attempts"]
        if r["label"] == "A-baseline":
            verdict = "(baseline)"
        elif wins == RUNS_PER_CONDITION:
            verdict = "ALWAYS 1att -- pattern transferred"
        elif wins == 0:
            verdict = "NEVER 1att -- no transfer"
        else:
            verdict = f"MIXED ({wins}/{RUNS_PER_CONDITION} at 1att)"
        print(f"{r['label']:<22} {wins:>6}/{RUNS_PER_CONDITION}  {avg:>8}att  {verdict}")

    print()
    print("INTERPRETATION:")
    b = next(r for r in summary if r["label"] == "B-transfer")
    c = next(r for r in summary if r["label"] == "C-fake")

    if b["wins_at_1"] > c["wins_at_1"]:
        print("  B > C: idempotency pattern from task_02 generalized to task_05.")
        print("  The SYSTEM transferred knowledge -- not LLM memory.")
        print("  -> Pattern generalization confirmed.")
    elif b["wins_at_1"] == c["wins_at_1"]:
        if b["avg_attempts"] < c["avg_attempts"]:
            print("  B == C at 1att, but B has lower avg attempts.")
            print("  Partial transfer: strategy helps but doesn't fully anticipate the fix.")
        else:
            print("  B == C: pattern from task_02 does not transfer to task_05.")
            print("  Strategy too specific. Needs better abstraction in extract_from_diff.")
    else:
        print("  C > B: transfer strategy actively interfered with task_05 solution.")
        print("  Strategy content was misleading in this domain.")

    print()
    print("Compare with Test A (same task, same strategy):")
    print("  Test A B-real:     3/3 @ 1att (strategy on task_02)")
    b_str = f"{b['wins_at_1']}/3 @ 1att"
    print(f"  Test C B-transfer: {b_str} (strategy from task_02 on task_05)")


if __name__ == "__main__":
    asyncio.run(main())
