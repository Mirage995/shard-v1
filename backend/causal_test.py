"""causal_test.py -- Test A: real strategy vs fake strategy (same length, zero information).

Hypothesis: if real strategy wins at attempt 1 but fake strategy does NOT,
the content matters -- not just prompt richness.

If both win at attempt 1, it's the richer prompt that helps, not the strategy content.

Conditions:
  A - baseline  : no strategy signal at all
  B - real       : real strategy content (idempotency guard)
  C - fake       : same structure + same length, but semantically empty
  D - forced_real: strategy forced into slot 1 (real content)

Run:
  cd backend && python causal_test.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TASK = Path(__file__).resolve().parent.parent / "benchmark" / "task_02_ghost_bug"
MAX_ATTEMPTS = 5
RUNS_PER_CONDITION = 3   # 3 runs per condition to reduce variance


# ── Fake strategy content (same structure as compiled real strategy) ──────────

FAKE_STRATEGY = """\
[STRATEGY - HIGH CONFIDENCE]

You MUST apply this approach to fix the failing test(s):

Focus on: `validate_readings()`

1. Consider using a standard formatting approach for the output values
Ensure that the return type matches the expected interface specifications
Apply consistent naming conventions throughout the implementation

FAILURE CONDITION:
If this approach is not applied, the failing tests will not pass.\
"""


def _patch_fake(signal_gate_module):
    """Replace build_strategy_signal to return fake content at same confidence."""
    original = signal_gate_module.build_strategy_signal

    def fake_build(strategies):
        real = original(strategies)
        if real is None:
            return None
        from signal_gate import Signal
        return Signal(
            content=FAKE_STRATEGY,
            confidence=real.confidence,   # same confidence score
            type=real.type,
            source=f"FAKE (same conf as real: {real.confidence:.3f})",
        )

    signal_gate_module.build_strategy_signal = fake_build
    return original   # return so we can restore


def _restore(signal_gate_module, original):
    signal_gate_module.build_strategy_signal = original


async def run_condition(label, strategy_mode, fake=False):
    import signal_gate as sg
    from benchmark_loop import run_benchmark_loop

    original = None
    if fake:
        original = _patch_fake(sg)

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

    if fake and original:
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
    print("CAUSAL TEST A -- Real strategy vs Fake strategy")
    print(f"Task: {TASK.name} | {RUNS_PER_CONDITION} runs per condition")
    print("=" * 60)
    print()

    print(f"Content length -- real: ~430 chars | fake: {len(FAKE_STRATEGY)} chars")
    print()

    # Run all 4 conditions sequentially (order matters for strategy DB accumulation)
    conditions = [
        ("A-baseline",    "baseline", False),
        ("B-real",        "normal",   False),
        ("C-fake",        "normal",   True),
        ("D-forced_real", "forced",   False),
    ]

    summary = []
    for label, mode, fake in conditions:
        print(f"\n{'='*40}")
        print(f"CONDITION: {label}")
        print(f"{'='*40}")
        res = await run_condition(label, mode, fake)
        summary.append(res)

    # Results table
    print("\n\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"{'Condition':<20} {'Wins@1':>8} {'Avg att':>10} {'Verdict'}")
    print("-" * 60)
    for r in summary:
        wins = r["wins_at_1"]
        avg  = r["avg_attempts"]
        if r["label"] == "A-baseline":
            verdict = "(baseline)"
        elif wins == RUNS_PER_CONDITION:
            verdict = "ALWAYS 1att -- content helped"
        elif wins == 0:
            verdict = "NEVER 1att -- content did NOT help"
        else:
            verdict = f"MIXED ({wins}/{RUNS_PER_CONDITION} at 1att)"
        print(f"{r['label']:<20} {wins:>6}/{RUNS_PER_CONDITION}  {avg:>8}att  {verdict}")

    print()
    print("INTERPRETATION:")
    b = next(r for r in summary if r["label"] == "B-real")
    c = next(r for r in summary if r["label"] == "C-fake")

    if b["wins_at_1"] > c["wins_at_1"]:
        print("  B > C: real strategy content causes the improvement.")
        print("  NOT a prompt-richness artefact. Content matters.")
    elif b["wins_at_1"] == c["wins_at_1"]:
        print("  B == C: both win equally.")
        print("  The richer prompt helps -- content is NOT the deciding factor.")
        print("  The behavior is likely an LLM artefact, not system intelligence.")
    else:
        print("  C > B: unexpected. Check if fake content accidentally helps.")


if __name__ == "__main__":
    asyncio.run(main())
