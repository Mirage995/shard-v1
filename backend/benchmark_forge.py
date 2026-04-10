"""benchmark_forge.py -- BenchmarkForge: generate hard SWE tasks from SHARD certifications.

After each study session, BenchmarkForge takes the certified topics and generates new
benchmark tasks that combine 2 certified topics into a non-trivial coding challenge.

Each generated task:
  - benchmark/task_forge_YYYYMMDD_HHMMSS_slug/
      stub.py         -- function stubs (source for benchmark_loop)
      test_task.py    -- pytest with 3+ test classes (hard checks)
      README.md       -- problem description + winning conditions

Naming convention chosen for benchmark_loop.py compatibility:
  - test file contains "solution.py not found" → output_filename = "solution.py"
  - source_files = [stub.py] → source_path = stub.py
  - agent writes solution.py

Validation pipeline (before task is persisted):
  1. Run tests without solution.py → must fail (sanity: tests actually check something)
  2. LLM generates reference solution from stub + tests + README
  3. Run tests WITH reference solution → must pass (sanity: problem is solvable)
  4. If both pass: persist task + reference solution; else: discard

Integration: called from night_runner.py post-certification via forge_from_session().
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("shard.benchmark_forge")

try:
    from llm_router import llm_complete
except ImportError:
    from backend.llm_router import llm_complete

# ── Paths ─────────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).parent
_BENCHMARK_DIR = _BACKEND_DIR.parent / "benchmark"

# ── Config ────────────────────────────────────────────────────────────────────
FORGE_MAX_TASKS_PER_SESSION = 2   # generate at most N tasks per session
FORGE_VALIDATION_TIMEOUT   = 30   # seconds for pytest on generated tests
FORGE_LLM_MAX_TOKENS       = 4096


# ── Prompt templates ──────────────────────────────────────────────────────────

_FORGE_SYSTEM = """\
You are BenchmarkForge, a specialist at designing hard coding challenges for a self-teaching AI.

Rules:
- Combine BOTH topics into ONE non-trivial problem
- The problem must require 2-5 LLM attempts to solve correctly (not trivial, not impossible)
- stub.py must have complete function signatures with docstrings but EMPTY bodies (just `pass`)
- test_task.py must import from solution (not stub) and be strict/multi-class
- Tests must be SELF-CONTAINED: no real network, no real filesystem writes, no signal handlers
- Use pytest fixtures, multiple test classes (TestCorrectness, TestEdgeCases, TestContract)
- The fixture MUST contain exactly: pytest.fail("solution.py not found at {spec_path}")
- Output ONLY valid JSON with keys: readme, stub, test
"""

_FORGE_USER = """\
Generate a hard benchmark task combining these two certified Python topics:
  Topic A: {topic_a}
  Topic B: {topic_b}

The task must:
1. Require meaningful use of BOTH topics
2. Have at least 3 trap edge cases built into the tests
3. Be solvable in pure Python (no external services, no signal handlers)

Return JSON with exactly these keys:
{{
  "readme": "<full README.md content>",
  "stub": "<full stub.py content with empty function bodies>",
  "test": "<full test_task.py content>"
}}

The test_task.py fixture for importing solution must look like:
```python
@pytest.fixture(scope="session")
def solution_module():
    spec_path = TASK_DIR / "solution.py"
    if not spec_path.exists():
        pytest.fail(f"solution.py not found at {{spec_path}}")
    import importlib
    if "solution" in sys.modules:
        del sys.modules["solution"]
    return importlib.import_module("solution")
```
"""

_REF_SOLUTION_PROMPT = """\
You are given a Python coding challenge. Write a COMPLETE, CORRECT solution.

=== README ===
{readme}

=== STUB (function signatures to implement) ===
{stub}

=== TESTS (all must pass) ===
{tests}

Write the COMPLETE solution.py file. Output raw Python only.
"""


# ── Core generation ───────────────────────────────────────────────────────────

async def _generate_task_files(topic_a: str, topic_b: str) -> Optional[dict]:
    """Call LLM to generate readme + stub + test for the topic pair.

    Returns dict with keys {readme, stub, test} or None on failure.
    """
    prompt = _FORGE_USER.format(topic_a=topic_a, topic_b=topic_b)
    try:
        raw = await llm_complete(
            system=_FORGE_SYSTEM,
            prompt=prompt,
            max_tokens=FORGE_LLM_MAX_TOKENS,
            temperature=0.4,
        )
    except Exception as exc:
        logger.warning("[FORGE] LLM call failed: %s", exc)
        return None

    # Extract JSON (handle markdown code fences)
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        logger.warning("[FORGE] No JSON found in LLM response")
        return None
    try:
        data = json.loads(json_match.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("[FORGE] JSON parse failed: %s", exc)
        return None

    required = {"readme", "stub", "test"}
    if not required.issubset(data.keys()):
        logger.warning("[FORGE] Missing keys in JSON: %s", required - data.keys())
        return None

    return data


async def _generate_reference_solution(readme: str, stub: str, test: str) -> Optional[str]:
    """Ask LLM to write a reference solution that should pass all tests."""
    prompt = _REF_SOLUTION_PROMPT.format(readme=readme, stub=stub, tests=test)
    try:
        raw = await llm_complete(
            system="You are an expert Python programmer. Write clean, correct code.",
            prompt=prompt,
            max_tokens=FORGE_LLM_MAX_TOKENS,
            temperature=0.05,
        )
    except Exception as exc:
        logger.warning("[FORGE] Reference solution LLM call failed: %s", exc)
        return None

    # Strip markdown code fences if present
    code = re.sub(r'^```python\s*\n', '', raw.strip())
    code = re.sub(r'\n```\s*$', '', code)
    return code.strip()


def _run_pytest(task_dir: Path, timeout: int = FORGE_VALIDATION_TIMEOUT) -> Tuple[bool, str]:
    """Run pytest in task_dir. Returns (passed: bool, output: str)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "test_task.py", "-v", "--tb=short", "-q"],
            cwd=str(task_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr)[:3000]
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"pytest timed out after {timeout}s"
    except Exception as exc:
        return False, str(exc)


def _make_task_slug(topic_a: str, topic_b: str) -> str:
    """Build a short filesystem-safe slug from the two topic names."""
    def slugify(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r'[^a-z0-9]+', '_', s)
        return s[:20].strip('_')
    return f"{slugify(topic_a)}_x_{slugify(topic_b)}"


def _fix_test_paths(test_content: str) -> str:
    """Ensure test_task.py has proper TASK_DIR setup and solution.py fixture."""
    # Check if TASK_DIR is defined
    if "TASK_DIR" not in test_content:
        header = textwrap.dedent("""\
            import sys
            import importlib
            from pathlib import Path
            import pytest

            TASK_DIR = Path(__file__).resolve().parent
            sys.path.insert(0, str(TASK_DIR))

        """)
        # Insert after existing imports
        test_content = header + test_content

    # Ensure sys.path insert is present
    if "sys.path.insert" not in test_content:
        insert_line = "sys.path.insert(0, str(TASK_DIR))\n"
        test_content = test_content.replace(
            "TASK_DIR = Path(__file__).resolve().parent\n",
            "TASK_DIR = Path(__file__).resolve().parent\n" + insert_line,
        )

    return test_content


async def forge_task(topic_a: str, topic_b: str) -> Optional[Path]:
    """Generate and validate a single benchmark task combining two topics.

    Returns the task directory Path on success, None on failure.
    """
    logger.info("[FORGE] Generating task: %s × %s", topic_a, topic_b)

    # Step 1: Generate files
    files = await _generate_task_files(topic_a, topic_b)
    if not files:
        logger.warning("[FORGE] Task generation failed for %s × %s", topic_a, topic_b)
        return None

    readme = files["readme"]
    stub   = files["stub"]
    test   = _fix_test_paths(files["test"])

    # Step 2: Write to temp dir for validation
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug  = _make_task_slug(topic_a, topic_b)
    name  = f"task_forge_{ts}_{slug}"

    with tempfile.TemporaryDirectory(prefix="shard_forge_") as tmpdir:
        tmp = Path(tmpdir)

        (tmp / "stub.py").write_text(stub, encoding="utf-8")
        (tmp / "test_task.py").write_text(test, encoding="utf-8")
        (tmp / "README.md").write_text(readme, encoding="utf-8")

        # Step 3: Tests without solution.py must FAIL
        passed_without, out_without = _run_pytest(tmp)
        if passed_without:
            logger.warning(
                "[FORGE] Tests pass without solution.py — task is trivially passable or broken. Discarding."
            )
            return None
        logger.info("[FORGE] Sanity check OK: tests fail without solution.py")

        # Step 4: Generate reference solution
        ref_solution = await _generate_reference_solution(readme, stub, test)
        if not ref_solution:
            logger.warning("[FORGE] Reference solution generation failed. Discarding.")
            return None

        (tmp / "solution.py").write_text(ref_solution, encoding="utf-8")

        # Step 5: Tests WITH reference solution must PASS
        passed_with, out_with = _run_pytest(tmp)
        if not passed_with:
            logger.warning(
                "[FORGE] Reference solution does not pass tests. Discarding.\n%s", out_with[:600]
            )
            return None
        logger.info("[FORGE] Reference solution passes all tests ✓")

        # Step 6: Persist to benchmark/ directory
        task_dir = _BENCHMARK_DIR / name
        task_dir.mkdir(parents=True, exist_ok=True)

        (task_dir / "stub.py").write_text(stub, encoding="utf-8")
        (task_dir / "test_task.py").write_text(test, encoding="utf-8")
        (task_dir / "README.md").write_text(readme, encoding="utf-8")
        # Save reference solution — benchmark_loop golden fast-path will detect it
        (task_dir / "solution.py").write_text(ref_solution, encoding="utf-8")

        logger.info("[FORGE] Task persisted: %s", task_dir)
        return task_dir


async def forge_from_session(certified_topics: List[str]) -> List[Path]:
    """Entry point for NightRunner: generate tasks from this session's certifications.

    Takes the list of newly certified topic names, pairs them up, and generates
    up to FORGE_MAX_TASKS_PER_SESSION hard benchmark tasks.

    Returns list of created task directory Paths.
    """
    if len(certified_topics) < 2:
        logger.info("[FORGE] Need ≥2 certified topics to forge a task (got %d)", len(certified_topics))
        return []

    # Build pairs: consecutive pairs from the certified list (avoids combinatorial explosion)
    # If 3+ topics, also pair first with last for cross-domain difficulty
    pairs = []
    for i in range(0, len(certified_topics) - 1, 2):
        pairs.append((certified_topics[i], certified_topics[i + 1]))
    if len(certified_topics) >= 3 and len(pairs) < FORGE_MAX_TASKS_PER_SESSION:
        pairs.append((certified_topics[0], certified_topics[-1]))

    pairs = pairs[:FORGE_MAX_TASKS_PER_SESSION]
    logger.info("[FORGE] Forging %d task(s) from %d certified topics", len(pairs), len(certified_topics))

    results = []
    for topic_a, topic_b in pairs:
        task_dir = await forge_task(topic_a, topic_b)
        if task_dir:
            results.append(task_dir)

    logger.info("[FORGE] Session complete: %d/%d tasks forged successfully", len(results), len(pairs))
    return results
