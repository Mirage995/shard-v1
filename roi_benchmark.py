"""roi_benchmark.py — Architecture ROI: Naked LLM vs SHARD Full Pipeline.

Runs each benchmark task in two modes and measures the delta in success rate.

Mode A — Naked LLM:
  - Provider: Gemini Flash
  - 1 attempt, no feedback loop
  - No episodic memory, no swarm, no knowledge bridge

Mode B — SHARD Full:
  - All features ON: episodic memory + swarm engine + knowledge bridge
  - Up to 5 attempts with pytest feedback

Usage:
    python roi_benchmark.py                         # all 7 tasks
    python roi_benchmark.py --tasks task_01_html_trap task_04_race_condition
    python roi_benchmark.py --tasks task_01_html_trap --naked-only
    python roi_benchmark.py --tasks task_01_html_trap --shard-only
"""
import argparse
import asyncio
import io
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

# Force UTF-8 stdout on Windows to avoid cp1252 encoding errors
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Path setup ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
BENCHMARK_DIR = ROOT / "benchmark"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT))

from llm_router import llm_complete
from benchmark_loop import run_benchmark_loop, _run_pytest, _parse_pytest_output, _write_file

# ── Constants ───────────────────────────────────────────────────────────────────
NAKED_PROVIDERS = ["Gemini"]
PYTEST_TIMEOUT = 60

NAKED_SYSTEM = (
    "You are a precise Python bug-fixing and refactoring agent. "
    "Output ONLY valid Python source code. "
    "No markdown fences, no explanations, no commentary. "
    "Every function must be fully implemented — no ellipsis, no pass, no TODO."
)


# ── Result dataclasses ───────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    task: str
    mode: str           # "naked" or "shard"
    success: bool       # all tests passed
    passed: int
    failed: int
    total: int
    pass_rate: float    # passed / total
    elapsed: float      # seconds
    attempts: int       # 1 for naked, N for SHARD
    error: Optional[str] = None


# ── Naked LLM runner ─────────────────────────────────────────────────────────────

def _detect_output_filename(tests: str, source_name: str) -> str:
    """Mirror benchmark_loop's logic for detecting the expected output filename."""
    m = re.search(r'(\w+\.py)\s+not found', tests)
    if not m:
        m = re.search(r'"(\w+\.py)".*not found', tests)
    return m.group(1) if m else "fixed_" + source_name


def _extract_code(response: str) -> str:
    """Strip markdown fences from LLM response."""
    fence = re.search(r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    import ast
    try:
        ast.parse(response)
        return response.strip()
    except SyntaxError:
        pass
    lines = [l for l in response.strip().splitlines()
             if not l.startswith("```") and not l.startswith("Here")]
    return "\n".join(lines)


async def run_naked_llm(task_dir: Path) -> TaskResult:
    """Single LLM call, no feedback, no memory, no swarm."""
    t0 = time.time()
    task_name = task_dir.name

    # Load task files
    readme = (task_dir / "README.md").read_text(encoding="utf-8") \
        if (task_dir / "README.md").exists() else ""

    source_files = sorted(
        f for f in task_dir.glob("*.py")
        if not f.name.startswith("test_") and not f.name.startswith("__")
    )
    if not source_files:
        return TaskResult(task_name, "naked", False, 0, 0, 0, 0.0,
                          time.time() - t0, 1, "No source file found")

    test_files = sorted(task_dir.glob("test_task*.py")) or sorted(task_dir.glob("test_*.py"))
    if not test_files:
        return TaskResult(task_name, "naked", False, 0, 0, 0, 0.0,
                          time.time() - t0, 1, "No test file found")

    test_file = test_files[0]
    tests = test_file.read_text(encoding="utf-8")

    # Derive source_path from output filename (multi-file support)
    output_filename = _detect_output_filename(tests, source_files[0].name)
    primary_name = re.sub(r'^fixed_', '', output_filename)
    primary_candidate = task_dir / primary_name
    source_path = primary_candidate if primary_candidate in source_files else source_files[0]
    output_path = task_dir / output_filename

    # Multi-file: concatenate all source files with TARGET/CONTEXT labels
    context_files = [f for f in source_files if f != source_path]
    if context_files:
        parts = []
        for f in context_files:
            parts.append(
                f"# === {f.name} [CONTEXT — read only, do not output this file] ===\n"
                + f.read_text(encoding="utf-8")
            )
        parts.append(
            f"# === {source_path.name} [TARGET — fix this file, output as {output_filename}] ===\n"
            + source_path.read_text(encoding="utf-8")
        )
        source = "\n\n".join(parts)
    else:
        source = source_path.read_text(encoding="utf-8")

    # Clean previous output
    if output_path.exists():
        output_path.unlink()

    # Single LLM call — no memory, no swarm, no KB
    prompt = (
        f"=== TASK DESCRIPTION ===\n{readme}\n\n"
        f"=== SOURCE CODE ===\n{source}\n\n"
        f"Write the COMPLETE {output_filename}. Raw Python only."
    )

    try:
        raw = await llm_complete(
            prompt=prompt,
            system=NAKED_SYSTEM,
            max_tokens=8192,
            temperature=0.05,
            providers=NAKED_PROVIDERS,
        )
        code = _extract_code(raw)
        if not code.strip():
            return TaskResult(task_name, "naked", False, 0, 0, 0, 0.0,
                              time.time() - t0, 1, "LLM returned empty code")
    except Exception as e:
        return TaskResult(task_name, "naked", False, 0, 0, 0, 0.0,
                          time.time() - t0, 1, f"LLM error: {e}")

    # Write output
    try:
        _write_file(output_path, code)
    except Exception as e:
        return TaskResult(task_name, "naked", False, 0, 0, 0, 0.0,
                          time.time() - t0, 1, f"Write error: {e}")

    # Run pytest once
    all_passed, raw_pytest = _run_pytest(task_dir, test_file.name)
    passed, failed, _ = _parse_pytest_output(raw_pytest)
    total = len(passed) + len(failed)
    pass_rate = len(passed) / total if total > 0 else 0.0
    elapsed = time.time() - t0

    return TaskResult(
        task=task_name,
        mode="naked",
        success=all_passed,
        passed=len(passed),
        failed=len(failed),
        total=total,
        pass_rate=pass_rate,
        elapsed=elapsed,
        attempts=1,
    )


# ── SHARD full runner ────────────────────────────────────────────────────────────

async def run_shard_full(task_dir: Path, max_attempts: int = 5) -> TaskResult:
    """Full SHARD pipeline: memory + swarm + KB + feedback loop."""
    t0 = time.time()
    task_name = task_dir.name

    try:
        result = await run_benchmark_loop(
            task_dir=task_dir,
            max_attempts=max_attempts,
            use_episodic_memory=True,
            use_swarm=True,
            use_concurrency_sim=True,
        )
    except Exception as e:
        return TaskResult(task_name, "shard", False, 0, 0, 0, 0.0,
                          time.time() - t0, 0, f"SHARD error: {e}")

    # Count tests from the best attempt
    best = max(result.attempts, key=lambda a: len(a.tests_passed)) if result.attempts else None
    passed = len(best.tests_passed) if best else 0
    failed = len(best.tests_failed) if best else 0
    total = passed + failed
    pass_rate = passed / total if total > 0 else 0.0

    return TaskResult(
        task=task_name,
        mode="shard",
        success=result.success,
        passed=passed,
        failed=failed,
        total=total,
        pass_rate=pass_rate,
        elapsed=result.elapsed_total,
        attempts=result.total_attempts,
    )


# ── Output formatting ────────────────────────────────────────────────────────────

def _bar(rate: float, width: int = 20) -> str:
    filled = int(rate * width)
    return "#" * filled + "." * (width - filled)


def print_comparison_table(pairs: list):
    """Print side-by-side comparison table."""
    print()
    print("=" * 90)
    print("  SHARD Architecture ROI Benchmark")
    print("  Naked Gemini Flash (1 attempt)  vs  SHARD Full Pipeline (up to 5 attempts)")
    print("=" * 90)
    print(f"  {'Task':<30} {'Naked':^22} {'SHARD':^22} {'Delta':>8}")
    print(f"  {'-'*30} {'-'*22} {'-'*22} {'-'*8}")

    total_naked_pass = 0
    total_shard_pass = 0
    total_tasks = 0

    for naked, shard in pairs:
        if naked is None or shard is None:
            continue
        task = naked.task.replace("task_0", "T").replace("task_", "T")
        naked_str = f"{_bar(naked.pass_rate, 12)} {naked.pass_rate*100:5.1f}%"
        shard_str = f"{_bar(shard.pass_rate, 12)} {shard.pass_rate*100:5.1f}%"
        delta = shard.pass_rate - naked.pass_rate
        delta_str = f"+{delta*100:.1f}%" if delta >= 0 else f"{delta*100:.1f}%"
        flag = "OK" if shard.success else "--"
        print(f"  {task:<30} {naked_str}   {shard_str}   {delta_str:>7}  {flag}")
        total_naked_pass += naked.pass_rate
        total_shard_pass += shard.pass_rate
        total_tasks += 1

    if total_tasks:
        avg_naked = total_naked_pass / total_tasks
        avg_shard = total_shard_pass / total_tasks
        avg_delta = avg_shard - avg_naked
        print(f"  {'-'*85}")
        print(f"  {'AVERAGE':<30} {'':>4}{avg_naked*100:5.1f}%{'':>13}{avg_shard*100:5.1f}%{'':>9}+{avg_delta*100:.1f}%")

    print("=" * 90)
    print()

    # Summary stats
    naked_wins = sum(1 for n, s in pairs if n and s and n.success)
    shard_wins = sum(1 for n, s in pairs if n and s and s.success)
    print(f"  Tasks solved (all tests pass):")
    print(f"    Naked LLM : {naked_wins}/{total_tasks}")
    print(f"    SHARD     : {shard_wins}/{total_tasks}")
    print(f"    ROI uplift: +{shard_wins - naked_wins} tasks fully solved")
    print()

    # Timing
    print(f"  Timing:")
    for naked, shard in pairs:
        if naked and shard:
            task = naked.task
            print(f"    {task}: naked={naked.elapsed:.1f}s  shard={shard.elapsed:.1f}s "
                  f"(attempts: {shard.attempts})")
    print()


def save_results(pairs: list, output_path: Path):
    """Save full results to JSON."""
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": [
            {
                "task": n.task if n else s.task,
                "naked": asdict(n) if n else None,
                "shard": asdict(s) if s else None,
                "delta_pass_rate": (s.pass_rate - n.pass_rate) if (n and s) else None,
            }
            for n, s in pairs
        ],
    }
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Results saved to: {output_path}")


def generate_markdown_report(pairs: list, output_path: Path):
    """Generate a human-readable Markdown report of the benchmark results."""
    ts = time.strftime("%Y-%m-%d %H:%M")
    valid = [(n, s) for n, s in pairs if n and s]
    total = len(valid)

    naked_wins = sum(1 for n, s in valid if n.success)
    shard_wins = sum(1 for n, s in valid if s.success)
    avg_naked = sum(n.pass_rate for n, s in valid) / total if total else 0
    avg_shard = sum(s.pass_rate for n, s in valid) / total if total else 0
    avg_delta = avg_shard - avg_naked

    lines = [
        f"# SHARD Architecture ROI Benchmark",
        f"",
        f"**Date:** {ts}  ",
        f"**Tasks:** {total}  ",
        f"**Modes:** Naked Gemini Flash (1 attempt, no memory, no swarm) vs SHARD Full Pipeline",
        f"",
        f"---",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Naked LLM | SHARD Full | Delta |",
        f"|--------|-----------|------------|-------|",
        f"| Avg pass rate | {avg_naked*100:.1f}% | {avg_shard*100:.1f}% | **+{avg_delta*100:.1f} pp** |",
        f"| Tasks fully solved | {naked_wins}/{total} | {shard_wins}/{total} | **+{shard_wins-naked_wins} tasks** |",
        f"",
        f"---",
        f"",
        f"## Per-Task Results",
        f"",
        f"| Task | Naked pass rate | SHARD pass rate | Delta | SHARD solved? | SHARD attempts |",
        f"|------|----------------|----------------|-------|---------------|----------------|",
    ]

    for n, s in valid:
        delta = s.pass_rate - n.pass_rate
        delta_str = f"+{delta*100:.1f}%" if delta >= 0 else f"{delta*100:.1f}%"
        solved = "YES" if s.success else "no"
        naked_str = f"{n.pass_rate*100:.1f}% ({n.passed}/{n.total})"
        shard_str = f"{s.pass_rate*100:.1f}% ({s.passed}/{s.total})"
        lines.append(
            f"| {n.task} | {naked_str} | {shard_str} | **{delta_str}** | {solved} | {s.attempts} |"
        )

    lines += [
        f"",
        f"---",
        f"",
        f"## Timing",
        f"",
        f"| Task | Naked time | SHARD time | SHARD attempts |",
        f"|------|-----------|-----------|----------------|",
    ]
    for n, s in valid:
        lines.append(f"| {n.task} | {n.elapsed:.1f}s | {s.elapsed:.1f}s | {s.attempts} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Key Findings",
        f"",
    ]

    # Auto-generate findings based on data
    best_delta = max(valid, key=lambda x: x[1].pass_rate - x[0].pass_rate)
    n, s = best_delta
    lines.append(
        f"**Highest delta task:** `{n.task}` — "
        f"Naked {n.pass_rate*100:.1f}% vs SHARD {s.pass_rate*100:.1f}% "
        f"(+{(s.pass_rate-n.pass_rate)*100:.1f} pp)"
    )
    lines.append("")

    naked_failures = [(n, s) for n, s in valid if not n.success and s.success]
    if naked_failures:
        lines.append(
            f"**Tasks where Naked LLM failed but SHARD succeeded ({len(naked_failures)}):**"
        )
        for n, s in naked_failures:
            lines.append(f"- `{n.task}`: naked {n.passed}/{n.total} tests, SHARD {s.passed}/{s.total} tests")
        lines.append("")

    swarm_regressions = [(n, s) for n, s in valid if s.pass_rate < n.pass_rate]
    if swarm_regressions:
        lines.append(f"**Tasks where SHARD underperformed naked LLM ({len(swarm_regressions)}):**")
        for n, s in swarm_regressions:
            delta = (s.pass_rate - n.pass_rate) * 100
            lines.append(
                f"- `{n.task}`: naked {n.pass_rate*100:.1f}% vs SHARD {s.pass_rate*100:.1f}% "
                f"({delta:.1f} pp) — potential swarm over-engineering"
            )
        lines.append("")

    first_attempt_wins = [(n, s) for n, s in valid if s.success and s.attempts == 1]
    if first_attempt_wins:
        lines.append(
            f"**Tasks SHARD solved on the first attempt ({len(first_attempt_wins)}):** "
            + ", ".join(f"`{n.task}`" for n, s in first_attempt_wins)
        )
        lines.append("")

    lines += [
        f"---",
        f"",
        f"## Architecture Components Active in SHARD Mode",
        f"",
        f"- **Episodic memory**: past session history injected into Attempt 1 prompt",
        f"- **Knowledge bridge**: GraphRAG context from NightRunner study sessions",
        f"- **Concurrency simulator**: auto-detects threading tasks, probes race conditions before LLM call",
        f"- **Swarm engine**: Architect + Coder + parallel specialized reviewers (Concurrency, Security, EdgeCases, Performance, DataIntegrity)",
        f"- **Feedback loop**: up to 5 attempts with pytest output parsed and fed back to LLM",
        f"",
        f"---",
        f"",
        f"*Generated by roi_benchmark.py — SHARD v1*",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Markdown report saved to: {output_path}")


# ── Main ─────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Architecture ROI Benchmark: Naked LLM vs SHARD")
    parser.add_argument(
        "--tasks", nargs="*",
        help="Task directories to run (default: all). E.g. --tasks task_01_html_trap task_04_race_condition"
    )
    parser.add_argument("--naked-only", action="store_true", help="Run only naked LLM mode")
    parser.add_argument("--shard-only", action="store_true", help="Run only SHARD mode")
    parser.add_argument("--max-attempts", type=int, default=5, help="Max attempts for SHARD mode")
    parser.add_argument("--output", type=str, default="roi_results.json",
                        help="Output JSON file path")
    args = parser.parse_args()

    # Discover tasks
    if args.tasks:
        task_dirs = [BENCHMARK_DIR / t for t in args.tasks]
    else:
        task_dirs = sorted(BENCHMARK_DIR.glob("task_*"))

    task_dirs = [d for d in task_dirs if d.is_dir()]
    if not task_dirs:
        print("No task directories found.")
        sys.exit(1)

    print(f"\nRunning ROI benchmark on {len(task_dirs)} task(s)...")
    print(f"Tasks: {[d.name for d in task_dirs]}\n")

    pairs = []

    for task_dir in task_dirs:
        naked_result = None
        shard_result = None

        print(f"{'-'*60}")
        print(f"  Task: {task_dir.name}")

        if not args.shard_only:
            print(f"  [NAKED] Running single Gemini Flash call...")
            naked_result = await run_naked_llm(task_dir)
            status = "✓ PASS" if naked_result.success else f"✗ {naked_result.passed}/{naked_result.total} tests"
            print(f"  [NAKED] {status}  ({naked_result.elapsed:.1f}s)")
            if naked_result.error:
                print(f"  [NAKED] Error: {naked_result.error}")

        if not args.naked_only:
            print(f"  [SHARD] Running full pipeline (max {args.max_attempts} attempts)...")
            shard_result = await run_shard_full(task_dir, args.max_attempts)
            status = "✓ PASS" if shard_result.success else f"✗ {shard_result.passed}/{shard_result.total} tests"
            print(f"  [SHARD] {status}  ({shard_result.elapsed:.1f}s, {shard_result.attempts} attempts)")
            if shard_result.error:
                print(f"  [SHARD] Error: {shard_result.error}")

        pairs.append((naked_result, shard_result))

    # Print comparison table
    if not args.naked_only and not args.shard_only:
        print_comparison_table(pairs)

    # Save results
    json_path = ROOT / args.output
    save_results(pairs, json_path)

    # Generate Markdown report
    md_path = json_path.with_suffix(".md")
    generate_markdown_report(pairs, md_path)


if __name__ == "__main__":
    asyncio.run(main())
