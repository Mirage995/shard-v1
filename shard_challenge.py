"""shard_challenge.py — Run SHARD on any buggy file + test, no setup needed.

Usage:
    python shard_challenge.py buggy.py test_buggy.py
    python shard_challenge.py buggy.py test_buggy.py --max-attempts 5
    python shard_challenge.py buggy.py test_buggy.py --install "requests boto3"
    python shard_challenge.py buggy.py test_buggy.py --repo https://github.com/foo/bar
    python shard_challenge.py buggy.py test_buggy.py --repo /local/path/to/repo

The script:
  1. Creates a temp benchmark task folder
  2. Copies the buggy file as processor.py
  3. (Optional) Ingests a repo via Repomix and injects it as knowledge context
  4. Detects the output filename from the test (or defaults to fixed_<name>.py)
  5. Runs the SHARD benchmark loop
  6. Prints results + the winning fix
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT))


# -- Standalone CognitionCore observer ----------------------------------------
# Lightweight implementation of the ShardConsciousness interface.
# Activates CognitionCore features (event tracking, XP, brain graph updates)
# in shard_challenge without requiring the full server stack.

class _BenchmarkConsciousness:
    """Minimal consciousness for standalone benchmark runs.

    Implements the same interface as ShardConsciousness so benchmark_loop
    can call push_event() and add_xp() without knowing it's standalone.
    Events are persisted to shard_memory/challenge_events.jsonl.
    """

    def __init__(self, log_path: Path):
        self._log_path = log_path
        self._log_path.parent.mkdir(exist_ok=True)
        self._session_events = []

    def push_event(self, event_type: str, data: dict):
        ev = {"type": event_type, "data": data, "ts": datetime.now().isoformat()}
        self._session_events.append(ev)

        # Real-time cognition pulse per event type
        if event_type == "benchmark":
            attempt = data.get("attempt", "?")
            passed  = data.get("passed", 0)
            failed  = data.get("failed", 0)
            mode    = data.get("mode", "")
            total   = passed + failed
            bar     = "#" * passed + "." * failed
            print(f"  [cognition] attempt {attempt} | {passed}/{total} [{bar}] | {mode}")

        elif event_type == "capability_probe":
            lang      = data.get("lang", "?")
            ready     = data.get("ready", False)
            missing   = data.get("missing", [])
            status    = "READY" if ready else "MISSING RUNTIME"
            miss_str  = f" | missing: {', '.join(missing)}" if missing else ""
            print(f"  [cognition] env probe | lang={lang} | {status}{miss_str}")

        elif event_type == "self_assessment":
            lang  = data.get("lang", "?")
            lines = data.get("profile_lines", 0)
            print(f"  [cognition] self-profile | lang={lang} | {lines} lines injected into prompt")

        elif event_type == "mastery_achieved":
            task     = data.get("task", "?")
            attempts = data.get("attempts", "?")
            tests    = data.get("tests", "?")
            first    = data.get("first_try", False)
            tag      = " [FIRST TRY]" if first else ""
            print(f"  [cognition] MASTERY{tag} | {task} | {tests} tests | {attempts} attempt(s)")

        # Append to persistent log
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        except Exception:
            pass

    def add_xp(self, skill_name: str, amount: float):
        """Update capability graph XP — delegates to CapabilityGraph if available."""
        try:
            cap_path = ROOT / "shard_memory" / "capability_graph.json"
            if not cap_path.exists():
                return
            graph = json.loads(cap_path.read_text(encoding="utf-8"))
            nodes = graph.get("nodes", {})
            # Find the closest matching node
            skill_lower = skill_name.lower()
            match = next(
                (k for k in nodes if skill_lower in k.lower() or k.lower() in skill_lower),
                None
            )
            if match:
                nodes[match]["xp"] = round(nodes[match].get("xp", 0) + amount, 3)
                cap_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
                print(f"  [cognition] +{amount} XP → {match}")
        except Exception:
            pass

    def flush_summary(self):
        """Print a session summary of all benchmark events."""
        if not self._session_events:
            return
        benchmark_events = [e for e in self._session_events if e["type"] == "benchmark"]
        if benchmark_events:
            last = benchmark_events[-1]["data"]
            print(f"\n  [cognition] Session: {len(benchmark_events)} attempt(s) observed | "
                  f"final {last.get('passed',0)}p/{last.get('failed',0)}f")


_LANG_EXTS = {
    ".py":  "python",
    ".js":  "javascript",
    ".ts":  "javascript",
    ".cpp": "cpp",
    ".cc":  "cpp",
    ".rs":  "rust",
    ".go":  "go",
    ".java":"java",
}

def _detect_output_filename(test_path: Path, buggy_stem: str, ext: str = ".py") -> str:
    """Try to detect what filename the test expects as output."""
    src = test_path.read_text(encoding="utf-8")
    import re
    ext_escaped = re.escape(ext)
    m = re.search(rf'fixed_[\w]+{ext_escaped}', src)
    if m:
        return m.group(0)
    return f"fixed_{buggy_stem}{ext}"


_DEFAULT_MAX_CONTEXT = 400_000  # ~100k tokens (4 chars/token avg)


def _truncate_repomix(xml: str, max_chars: int) -> str:
    """Truncate Repomix XML intelligently, keeping structure + README intact.

    Strategy:
      1. If under limit → return as-is.
      2. Otherwise:
         - Always keep: directory structure block, summary/stats block.
         - Always keep: the README file block (first match).
         - Fill remaining budget with other file blocks in order.
         - Append a [TRUNCATED] notice.

    Works on Repomix XML format (plain text / markdown fallback: split on
    '=====' section separators instead).
    """
    import re

    if len(xml) <= max_chars:
        return xml

    # --- XML format (repomix default) ---
    # Extract directory structure block
    dir_block = ""
    m = re.search(r"(<directory_structure>.*?</directory_structure>)", xml, re.DOTALL)
    if m:
        dir_block = m.group(1)

    # Extract summary/stats block
    summary_block = ""
    m = re.search(r"(<summary>.*?</summary>)", xml, re.DOTALL)
    if m:
        summary_block = m.group(1)

    # Extract all <file> blocks
    file_blocks = re.findall(r"(<file\b[^>]*>.*?</file>)", xml, re.DOTALL)

    if not file_blocks:
        # Fallback: plain text with ======= separators (repomix --style plain)
        sections = re.split(r"(={4,}.*?={4,})", xml, flags=re.DOTALL)
        header = sections[0] if sections else ""
        body_sections = sections[1:]

        budget = max_chars - len(header) - 200  # reserve for notice
        kept = [header]
        for sec in body_sections:
            if budget <= 0:
                break
            kept.append(sec[:budget])
            budget -= len(sec)

        kept.append(
            f"\n\n[TRUNCATED BY SHARD CONTEXT LIMIT — original {len(xml):,} chars, "
            f"limit {max_chars:,} chars. Some files omitted.]"
        )
        return "".join(kept)

    # Separate README block from the rest
    readme_blocks = [b for b in file_blocks if re.search(r'path=["\']?readme', b, re.IGNORECASE)]
    other_blocks = [b for b in file_blocks if b not in readme_blocks]

    # Build output respecting budget
    header_parts = []
    if summary_block:
        header_parts.append(summary_block)
    if dir_block:
        header_parts.append(dir_block)
    header_parts.extend(readme_blocks)

    header = "\n".join(header_parts)
    notice = (
        f"\n\n<!-- [TRUNCATED BY SHARD CONTEXT LIMIT] "
        f"Original: {len(xml):,} chars | Limit: {max_chars:,} chars | "
        f"Files shown: {{shown}}/{len(file_blocks)} -->"
    )

    budget = max_chars - len(header) - len(notice) - 50
    kept_files = []
    shown = 0
    for block in other_blocks:
        if budget <= 0:
            break
        if len(block) > budget:
            # Partially include the file with a truncation marker inside
            kept_files.append(block[:budget] + "\n  ... [file truncated]\n</file>")
            shown += 1
            budget = 0
            break
        kept_files.append(block)
        budget -= len(block)
        shown += 1

    result = header + "\n" + "\n".join(kept_files) + notice.format(shown=shown + len(readme_blocks))
    return result


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
    parser.add_argument(
        "--repo",
        default="",
        metavar="URL_OR_PATH",
        help="GitHub URL or local path to ingest via Repomix as knowledge context",
    )
    parser.add_argument(
        "--max-context",
        type=int,
        default=_DEFAULT_MAX_CONTEXT,
        metavar="CHARS",
        help=f"Max chars of Repomix context to inject (default: {_DEFAULT_MAX_CONTEXT:,}). "
             "Excess is truncated intelligently (keeps dir tree + README).",
    )
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

    # -- Optional: ingest repo via Repomix ------------------------------------
    repomix_context: str = ""
    if args.repo:
        cache_dir = ROOT / ".shard_cache"
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / "repomix_context.xml"

        print(f"\n[repomix] Ingesting repo: {args.repo}")
        print(f"[repomix] Cache: {cache_file}")
        try:
            from repomix_bridge import ingest_repo
            repomix_context = ingest_repo(args.repo)
            original_len = len(repomix_context)
            repomix_context = _truncate_repomix(repomix_context, args.max_context)
            cache_file.write_text(repomix_context, encoding="utf-8")
            if len(repomix_context) < original_len:
                print(
                    f"[repomix] Truncated: {original_len:,} → {len(repomix_context):,} chars "
                    f"(limit: {args.max_context:,})"
                )
            print(f"[repomix] Done — {len(repomix_context):,} chars ready for injection\n")
        except Exception as e:
            print(f"[repomix] WARNING: ingestion failed ({e}). Continuing without repo context.\n")

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
        buggy_ext = buggy_path.suffix or ".py"
        output_filename = _detect_output_filename(test_path, buggy_stem, ext=buggy_ext)

        # Copy files into task dir
        shutil.copy(buggy_path, task_dir / "processor.py")
        # Also keep original name so tests that import by filename still work
        if buggy_path.name != "processor.py":
            shutil.copy(buggy_path, task_dir / buggy_path.name)
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

        # Inject Repomix context into README.md so benchmark_loop picks it up
        if repomix_context:
            readme_path = task_dir / "README.md"
            existing = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
            # Use HTML comment header — invisible to markdown topic extractors
            separator = "\n\n<!-- repomix-context: external repo knowledge, not a study topic -->\n\n"
            readme_path.write_text(
                existing + separator + repomix_context,
                encoding="utf-8",
            )
            print(f"  [repomix] Injected {len(repomix_context):,} chars into README.md context\n")

        # Import and run benchmark loop
        import asyncio
        from benchmark_loop import run_benchmark_loop, set_consciousness

        # Wire CognitionCore — active even in standalone challenge runs
        _consciousness = _BenchmarkConsciousness(
            ROOT / "shard_memory" / "challenge_events.jsonl"
        )
        set_consciousness(_consciousness)
        print("  [cognition] CognitionCore: ACTIVE (standalone mode)\n")

        t0 = time.perf_counter()
        result = asyncio.run(run_benchmark_loop(
            task_dir=str(task_dir),
            max_attempts=args.max_attempts,
            use_swarm=not args.no_swarm,
        ))
        elapsed = time.perf_counter() - t0

        # CognitionCore: award XP based on result
        total_tests = len(result.attempts[-1].tests_passed) + len(result.attempts[-1].tests_failed) if result.attempts else 0
        if result.success:
            xp = round(1.0 + (total_tests / 20), 2)
            _consciousness.add_xp("software debugging", xp)
            _consciousness.add_xp("test driven development", xp * 0.5)
        _consciousness.flush_summary()

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
