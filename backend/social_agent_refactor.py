"""social_agent_refactor.py — Consolidate agent_posts.py + agent_posts_optimized.py

Smart merge strategy:
  - Uses AST to extract only functions unique to the legacy file (not in optimized)
  - Sends: full optimized file + unique legacy functions → ~9K input tokens
  - Attempts single-pass (leaves ~8K tokens for output)
  - Auto-falls-back to two-pass if still truncated

Output: ~/Desktop/social_agent/sandbox/agent_posts_unified.py

Usage:
    python social_agent_refactor.py
    python social_agent_refactor.py --dry-run
"""
import ast
import asyncio
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
BACKEND_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT   = BACKEND_DIR.parent
SOCIAL_AGENT   = Path.home() / "Desktop" / "social_agent"
FILE_LEGACY    = SOCIAL_AGENT / "agent_posts.py"
FILE_OPTIMIZED = SOCIAL_AGENT / "agent_posts_optimized.py"
SANDBOX_DIR    = SOCIAL_AGENT / "sandbox"
OUTPUT_FILE    = SANDBOX_DIR / "agent_posts_unified.py"

MODEL      = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 8192
PART_SPLIT = "# ═══ PART-2 ═══"

sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(PROJECT_ROOT))


# ── AST: extract unique functions from legacy ─────────────────────────────────

def extract_unique_functions(legacy_src: str, optimized_src: str) -> str:
    """Return source of functions/classes in legacy that do NOT exist in optimized."""
    try:
        opt_tree = ast.parse(optimized_src)
        opt_names = {
            node.name
            for node in ast.walk(opt_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }

        leg_tree  = ast.parse(legacy_src)
        leg_lines = legacy_src.splitlines()
        chunks    = []

        for node in ast.walk(leg_tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name in opt_names:
                continue
            # Include decorators if present
            start = (node.decorator_list[0].lineno - 1) if node.decorator_list else (node.lineno - 1)
            end   = node.end_lineno
            chunks.append("\n".join(leg_lines[start:end]))

        return "\n\n".join(chunks)
    except SyntaxError as e:
        print(f"  [WARN] AST parse failed ({e}) — falling back to full legacy")
        return legacy_src


def get_function_names(src: str) -> list[str]:
    try:
        tree = ast.parse(src)
        return [
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
    except Exception:
        return []


# ── Prompt builders ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a senior Python engineer performing a code merge. "
    "Output ONLY valid Python source code — no markdown, no fences, no commentary. "
    "Every function must be fully implemented. "
    "All HTML content MUST be inside Python string literals (triple-quotes or concatenation). "
    "Never write raw HTML tags as bare code lines."
)

RULES = """
MERGE RULES:
1. FILE B (optimized) is the reference. Keep its Pydantic models, style memory,
   feedback, anti-repetition, structured output, and improved error handling.
2. Add `USE_OPTIMIZED = True` after imports (toggles to simpler FILE A logic when False).
3. Include EVERY function from both files. Prefer FILE B's version for duplicates.
4. CLI unchanged: `python agent_posts_unified.py [CLIENT_NAME]`
5. Section comments: # ══ SETUP, # ══ MODELS, # ══ GENERATION, # ══ SELECTION, etc.
6. All HTML must be inside Python string literals — never bare HTML lines in code.
7. Output ONLY valid Python — no markdown, no fences, no explanations.
"""


def build_single_pass_prompt(optimized: str, unique_legacy: str, unique_names: list) -> str:
    unique_note = (
        f"Functions unique to legacy (must be included): {', '.join(unique_names)}"
        if unique_names else "No unique legacy functions found."
    )
    return f"""You are merging two Python files into one unified implementation.
{RULES}
## FILE B — agent_posts_optimized.py (BASE — use this as your foundation)
```python
{optimized}
```

## UNIQUE FUNCTIONS FROM FILE A (legacy only — not in FILE B)
{unique_note}
```python
{unique_legacy if unique_legacy.strip() else "# (none)"}
```

Write the COMPLETE unified file from top to bottom.
Do NOT use ellipsis (...) or skip any section.
Do NOT truncate — write every function in full."""


def build_part1_prompt(optimized: str, unique_legacy: str, unique_names: list) -> str:
    unique_note = (
        f"Functions unique to legacy: {', '.join(unique_names)}"
        if unique_names else "No unique legacy functions."
    )
    return f"""You are merging two Python files. Write PART 1 ONLY of the unified file.
{RULES}
## FILE B — agent_posts_optimized.py (BASE)
```python
{optimized}
```

## UNIQUE FUNCTIONS FROM FILE A (legacy only)
{unique_note}
```python
{unique_legacy if unique_legacy.strip() else "# (none)"}
```

Write PART 1: everything from the top of the file through the end of `generate_posts()` (inclusive).
End your output with EXACTLY this line and nothing after:
{PART_SPLIT}
Do NOT write select_best_variants or anything after it."""


def build_part2_prompt(optimized: str, part1_code: str) -> str:
    # Only send signatures of optimized for context — saves tokens
    lines  = optimized.splitlines()
    sigs   = [l for l in lines if l.startswith("def ") or l.startswith("class ") or l.startswith("    def ")]
    sig_summary = "\n".join(sigs)

    return f"""You are writing PART 2 of a merged Python file. Part 1 is already written.
{RULES}
## FUNCTION SIGNATURES (for reference only — do NOT repeat these):
{sig_summary}

## PART 1 (already written — do NOT repeat):
```python
{part1_code}
```

Write PART 2: start directly with `def select_best_variants(` and write everything
through the end of the file, including render functions and `if __name__ == "__main__":`.
Do NOT repeat any imports or functions from Part 1."""


# ── API ───────────────────────────────────────────────────────────────────────

async def call_claude(client, prompt: str, label: str) -> tuple[str, str]:
    print(f"  [{label}] Calling Claude (max_tokens={MAX_TOKENS})... ", end="", flush=True)
    t0 = time.time()

    def _call():
        return client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

    resp    = await asyncio.to_thread(_call)
    elapsed = time.time() - t0
    code    = resp.content[0].text if resp.content else ""
    stop    = resp.stop_reason
    usage   = resp.usage

    print(f"done ({elapsed:.1f}s) | stop={stop} | in={usage.input_tokens:,} out={usage.output_tokens:,}")
    return strip_fences(code), stop


def strip_fences(code: str) -> str:
    if "```" in code:
        code = "\n".join(l for l in code.split("\n") if not l.strip().startswith("```")).strip()
    return code


# ── Syntax check + fix ────────────────────────────────────────────────────────

def syntax_check(code: str) -> tuple[bool, str]:
    import py_compile, tempfile
    tmp = Path(tempfile.mktemp(suffix=".py"))
    tmp.write_text(code, encoding="utf-8")
    try:
        py_compile.compile(str(tmp), doraise=True)
        return True, ""
    except py_compile.PyCompileError as e:
        return False, str(e)
    finally:
        tmp.unlink(missing_ok=True)


def attempt_syntax_fix(code: str, error: str) -> str:
    """Best-effort: remove bare HTML lines that Claude sometimes generates outside strings."""
    import re
    # Bare HTML line: starts with optional whitespace then < (but not a Python comment or string)
    html_line = re.compile(r'^(\s*)<[a-zA-Z/!][^#"\']*>.*$')
    fixed, count = [], 0
    for line in code.splitlines():
        if html_line.match(line) and not line.strip().startswith("#"):
            indent = len(line) - len(line.lstrip())
            fixed.append(" " * indent + f'"{line.strip()}",')
            count += 1
        else:
            fixed.append(line)
    if count:
        print(f"     Auto-fixed {count} bare HTML lines → quoted strings")
    return "\n".join(fixed)


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_merge(dry_run: bool = False):
    print()
    print("=" * 68)
    print("  SHARD Social Agent Refactor")
    print(f"  {FILE_LEGACY.name} + {FILE_OPTIMIZED.name}  →  {OUTPUT_FILE.name}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 68)

    # ── Read sources ──────────────────────────────────────────────────────
    print("\n[1/4] Reading source files...")
    legacy    = (FILE_LEGACY).read_text(encoding="utf-8", errors="replace")
    optimized = (FILE_OPTIMIZED).read_text(encoding="utf-8", errors="replace")
    print(f"      {FILE_LEGACY.name}: {len(legacy.splitlines())} lines")
    print(f"      {FILE_OPTIMIZED.name}: {len(optimized.splitlines())} lines")

    # ── Extract unique legacy functions ───────────────────────────────────
    print("\n[2/4] Extracting unique legacy functions (AST)...")
    unique_legacy = extract_unique_functions(legacy, optimized)
    unique_names  = get_function_names(unique_legacy)
    print(f"      Unique to legacy: {unique_names or ['(none)']}")
    print(f"      Input reduction: {len(legacy):,} → {len(unique_legacy):,} chars of legacy")

    # ── Build single-pass prompt ──────────────────────────────────────────
    prompt_single = build_single_pass_prompt(optimized, unique_legacy, unique_names)
    print(f"\n[3/4] Single-pass prompt: {len(prompt_single):,} chars")

    if dry_run:
        print("\n── DRY RUN ──")
        print(prompt_single[:1000])
        print("\n[DRY RUN] No API call made.")
        return

    # ── Auth ──────────────────────────────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(BACKEND_DIR / ".env")
    load_dotenv(SOCIAL_AGENT / ".env")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[ERROR] ANTHROPIC_API_KEY not found.")
        sys.exit(1)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    # ── Attempt single pass ───────────────────────────────────────────────
    print("\n[4/4] Merge:")
    code, stop = await call_claude(client, prompt_single, "single-pass")

    if stop == "end_turn":
        print("      ✅ Single-pass complete — no truncation")
        unified = code
    else:
        # Fall back to two-pass
        print("      ⚠️  Truncated — switching to two-pass fallback")

        p1 = build_part1_prompt(optimized, unique_legacy, unique_names)
        part1_raw, stop1 = await call_claude(client, p1, "Part 1")

        if PART_SPLIT in part1_raw:
            part1_code = part1_raw.split(PART_SPLIT)[0].rstrip()
            print(f"      Part 1 marker found — split clean ({len(part1_code.splitlines())} lines)")
        else:
            part1_code = part1_raw
            print(f"      ⚠️  Part 1 marker missing — using full response ({len(part1_code.splitlines())} lines)")

        p2 = build_part2_prompt(optimized, part1_code)
        print(f"      Part 2 prompt: {len(p2):,} chars")
        part2_code, stop2 = await call_claude(client, p2, "Part 2")
        print(f"      Part 2: {len(part2_code.splitlines())} lines | stop={stop2}")

        unified = part1_code + "\n\n" + part2_code

    # ── Syntax check + auto-fix ───────────────────────────────────────────
    print(f"\n      Syntax check: ", end="", flush=True)
    ok, err = syntax_check(unified)
    if ok:
        print("✅ valid Python")
    else:
        print(f"⚠️  error detected — attempting auto-fix")
        print(f"     {err}")
        unified = attempt_syntax_fix(unified, err)
        ok, err = syntax_check(unified)
        print(f"     Re-check: {'✅ fixed' if ok else f'⚠️  still broken: {err}'}")

    # ── Save ──────────────────────────────────────────────────────────────
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(unified, encoding="utf-8")

    orig_total    = len(legacy.splitlines()) + len(optimized.splitlines())
    unified_lines = len(unified.splitlines())
    reduction     = 100 * (1 - unified_lines / orig_total)

    print()
    print("=" * 68)
    print("  MERGE COMPLETE")
    print(f"  Input  : {orig_total:,} lines ({FILE_LEGACY.name} + {FILE_OPTIMIZED.name})")
    print(f"  Output : {unified_lines:,} lines  (reduction: {reduction:.0f}%)")
    print(f"  File   : {OUTPUT_FILE}")
    print(f"  Status : {'✅ valid Python' if ok else '⚠️  syntax issues — review before running'}")
    print("=" * 68)
    print()


def main():
    asyncio.run(run_merge("--dry-run" in sys.argv))


if __name__ == "__main__":
    main()
