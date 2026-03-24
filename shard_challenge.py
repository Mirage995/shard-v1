"""shard_challenge.py — Run SHARD on any buggy file + test, no setup needed.

Usage:
    python shard_challenge.py buggy.py test_buggy.py
    python shard_challenge.py buggy.py test_buggy.py --max-attempts 5
    python shard_challenge.py buggy.py test_buggy.py --install "requests boto3"

The script:
  1. Creates a temp benchmark task folder
  2. Copies the buggy file as processor.py
  3. Detects the output filename from the test (or defaults to fixed_<name>.py)
  4. Runs the SHARD benchmark loop
  5. Prints results + the winning fix
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT))


def _detect_output_filename(test_path: Path, buggy_stem: str) -> str:
    """Try to detect what filename the test expects as output."""
    src = test_path.read_text(encoding="utf-8")
    # Look for patterns like fixed_processor.py or fixed_bank.py
    import re
    m = re.search(r'fixed_[\w]+\.py', src)
    if m:
        return m.group(0)
    return f"fixed_{buggy_stem}.py"


def _pip_install(packages: str):
    print(f"  [setup] Installing: {packages}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install"] + packages.split(),
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  [setup] WARNING: pip install failed:\n{result.stderr[:300]}")


def main():
    parser = argparse.ArgumentParser(description="Run SHARD on any buggy Python file")
    parser.add_argument("buggy_file", help="Path to the buggy Python file")
    parser.add_argument("test_file", help="Path to the pytest test file")
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--install", default="", help="Extra pip packages to install first")
    parser.add_argument("--no-swarm", action="store_true", help="Disable swarm engine")
    args = parser.parse_args()

    buggy_path = Path(args.buggy_file).resolve()
    test_path = Path(args.test_file).resolve()

    if not buggy_path.exists():
        print(f"ERROR: buggy file not found: {buggy_path}")
        sys.exit(1)
    if not test_path.exists():
        print(f"ERROR: test file not found: {test_path}")
        sys.exit(1)

    if args.install:
        _pip_install(args.install)

    # Create temp task directory
    task_dir = Path(tempfile.mkdtemp(prefix="shard_challenge_"))
    print(f"\n{'='*60}")
    print(f"  SHARD Challenge Runner")
    print(f"  Buggy file : {buggy_path.name}")
    print(f"  Test file  : {test_path.name}")
    print(f"  Max attempts: {args.max_attempts}")
    print(f"{'='*60}\n")

    try:
        buggy_stem = buggy_path.stem
        output_filename = _detect_output_filename(test_path, buggy_stem)

        # Copy files into task dir
        shutil.copy(buggy_path, task_dir / "processor.py")
        shutil.copy(test_path, task_dir / test_path.name)

        # Copy any other .py files in the same dir as buggy (context files)
        # Skip test files, the buggy file itself, and any existing fixed_ files
        for f in buggy_path.parent.glob("*.py"):
            if f == buggy_path:
                continue
            if f.name == test_path.name:
                continue
            if f.name.startswith("fixed_"):
                continue
            if f.name.startswith("test_"):
                continue
            shutil.copy(f, task_dir / f.name)
            print(f"  [context] Copied: {f.name}")

        print(f"  [task] Output expected: {output_filename}")
        print(f"  [task] Working dir: {task_dir}\n")

        # Import and run benchmark loop
        import asyncio
        from benchmark_loop import run_benchmark_loop

        t0 = time.perf_counter()
        result = asyncio.run(run_benchmark_loop(
            task_dir=str(task_dir),
            max_attempts=args.max_attempts,
            use_swarm=not args.no_swarm,
        ))
        elapsed = time.perf_counter() - t0

        # Print summary
        print(f"\n{'='*60}")
        if result.success:
            print(f"  RESULT: PASS in {result.total_attempts} attempt(s) ({elapsed:.1f}s)")
        else:
            best = max(result.attempts, key=lambda a: len(a.tests_passed)) if result.attempts else None
            best_n = len(best.tests_passed) if best else 0
            total_n = best_n + (len(best.tests_failed) if best else 0)
            print(f"  RESULT: FAIL — best was {best_n}/{total_n} tests passing")
        print(f"{'='*60}")

        if result.success and result.final_code:
            fix_path = Path(f"shard_fix_{buggy_path.name}")
            fix_path.write_text(result.final_code, encoding="utf-8")
            print(f"\n  Fix saved to: {fix_path}")
            print(f"\n--- Fix preview (first 40 lines) ---")
            lines = result.final_code.splitlines()[:40]
            print("\n".join(lines))
            if len(result.final_code.splitlines()) > 40:
                print("  ...")

    finally:
        shutil.rmtree(task_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
