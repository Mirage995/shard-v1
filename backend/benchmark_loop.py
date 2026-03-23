"""benchmark_loop.py — Closed feedback loop for SHARD benchmark tasks.

The core proof that LLM + SHARD > stateless LLM.

Flow:
  1. Load task (legacy code + tests + README)
  2. Ask LLM to refactor
  3. Run pytest
  4. On failure: parse errors, feed back to LLM
  5. Repeat until all tests pass or max attempts

Usage:
    python benchmark_loop.py ../benchmark/task_01_html_trap
    python benchmark_loop.py ../benchmark/task_01_html_trap --max-attempts 8
"""
import ast
import asyncio
import glob
import logging
import os
from benchmark_memory import load_episodes, save_episode, build_experience_summary
from knowledge_bridge import query_knowledge_base
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# -- Import llm_router (handles dual import paths) ----------------------------
try:
    from llm_router import llm_complete
except ImportError:
    from backend.llm_router import llm_complete

# -- Import swarm_engine (optional — degrades gracefully if absent) ------------
try:
    from swarm_engine import swarm_complete
except ImportError:
    try:
        from backend.swarm_engine import swarm_complete
    except ImportError:
        swarm_complete = None

# -- Import concurrency_simulator (optional — degrades gracefully) -------------
try:
    from concurrency_simulator import probe_concurrency, format_for_prompt, is_concurrency_task
    _conc_sim_available = True
except ImportError:
    try:
        from backend.concurrency_simulator import probe_concurrency, format_for_prompt, is_concurrency_task
        _conc_sim_available = True
    except ImportError:
        _conc_sim_available = False

logger = logging.getLogger("shard.benchmark_loop")

# -- Optional consciousness reference (set by server.py after init) ------------
_consciousness = None

def set_consciousness(c):
    global _consciousness
    _consciousness = c

def _push_benchmark_event(task_key, attempt, passed, failed, mode):
    if _consciousness:
        try:
            _consciousness.push_event("benchmark", {
                "task": task_key, "attempt": attempt,
                "passed": passed, "failed": failed, "mode": mode,
            })
        except Exception:
            pass

# -- Config --------------------------------------------------------------------
MAX_ATTEMPTS_DEFAULT = 5
LLM_MAX_TOKENS = 8192
LLM_TEMPERATURE = 0.05
PYTEST_TIMEOUT = 60  # seconds


# -- Data structures -----------------------------------------------------------

@dataclass
class AttemptRecord:
    attempt: int
    code: str
    tests_passed: list
    tests_failed: list
    error_summary: str       # condensed failure info for logging
    raw_pytest: str
    syntax_valid: bool
    elapsed: float

@dataclass
class BenchmarkResult:
    task_dir: str
    success: bool
    total_attempts: int
    attempts: list           # list[AttemptRecord]
    final_code: str
    elapsed_total: float
    kb_used: bool = False    # True if knowledge bridge injected context
    kb_chars: int = 0        # chars of KB context injected


# -- Prompt builders -----------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a precise Python bug-fixing and refactoring agent. "
    "Output ONLY valid Python source code. "
    "No markdown fences, no explanations, no commentary. "
    "Every function must be fully implemented — no ellipsis, no pass, no TODO."
)


def _derive_study_topics(task_key: str, readme: str, best_attempt) -> list:
    """Derive 1-2 study topics from a failed benchmark task.

    Uses the task name and failed test names as signals — no LLM call needed.
    Topics are fed to NightRunner's improvement queue so the next night session
    studies exactly what the benchmark struggled with.
    """
    topics = []

    # Topic 1: from task name (e.g. "task_03_dirty_data" → "dirty data handling and validation")
    name_part = task_key.lower().replace("task_", "").strip()
    # strip leading index number (e.g. "03_dirty_data" → "dirty data")
    parts = name_part.split("_", 1)
    if len(parts) == 2 and parts[0].isdigit():
        name_part = parts[1].replace("_", " ")
    else:
        name_part = name_part.replace("_", " ")
    if len(name_part.split()) >= 2:
        topics.append(f"{name_part} handling and debugging")

    # Topic 2: from README first sentence (captures domain context)
    if readme:
        first_line = next((l.strip() for l in readme.splitlines() if len(l.strip()) > 20), "")
        if first_line and len(first_line.split()) >= 4:
            # Truncate to reasonable topic length
            words = first_line.split()[:10]
            readme_topic = " ".join(words).rstrip(".,:")
            if readme_topic not in topics:
                topics.append(readme_topic)

    return topics[:2]  # max 2 topics per failed task


def _build_initial_prompt(source: str, readme: str, output_filename: str,
                          experience_summary: str = "") -> str:
    memory_block = f"\n{experience_summary}\n" if experience_summary else ""
    return f"""Read the task description and source code below.
Your job: create {output_filename} — an optimized/fixed version of the source code.
{memory_block}
=== TASK DESCRIPTION (read this FIRST — it explains what to do) ===
{readme}

=== SOURCE CODE (the code to fix/refactor) ===
{source}

Write the COMPLETE {output_filename} file. Output raw Python only."""


def _detect_stuck_tests(attempts: list, min_consecutive: int = 2) -> list:
    """Return test names that failed in every one of the last min_consecutive valid attempts."""
    valid = [a for a in attempts if a.syntax_valid]
    if len(valid) < min_consecutive:
        return []
    recent = valid[-min_consecutive:]
    stuck = set(recent[0].tests_failed)
    for rec in recent[1:]:
        stuck &= set(rec.tests_failed)
    return sorted(stuck)


def _build_correction_prompt(
    source: str, tests: str, current_code: str, attempts: list, output_filename: str,
    stuck_tests: list = None,
) -> str:
    # Full details for every attempt — the LLM must see the complete history to avoid oscillating
    history_parts = []
    for rec in attempts:
        label = "LATEST" if rec is attempts[-1] else f"attempt {rec.attempt}"
        if not rec.syntax_valid:
            history_parts.append(
                f"--- Attempt {rec.attempt} ({label}) — SYNTAX ERROR ---\n{rec.error_summary}"
            )
        else:
            failed_str = ", ".join(rec.tests_failed) if rec.tests_failed else "(none)"
            passed_str = ", ".join(rec.tests_passed) if rec.tests_passed else "(none)"
            history_parts.append(
                f"--- Attempt {rec.attempt} ({label}) ---\n"
                f"Passed: {passed_str}\n"
                f"Failed: {failed_str}\n"
                f"Errors:\n{rec.error_summary}"
            )

    history = "\n\n".join(history_parts)

    # Regression warnings — tests that were passing but are now failing
    if len(attempts) >= 2:
        prev_passed = set(attempts[-2].tests_passed)
        curr_passed = set(attempts[-1].tests_passed)
        regressions = prev_passed - curr_passed
    else:
        regressions = set()

    regression_block = ""
    if regressions:
        reg_list = "\n".join(f"  - {t}" for t in sorted(regressions))
        regression_block = f"""
=== REGRESSIONS (were passing, now broken — do NOT lose these) ===
{reg_list}
"""

    # GraphRAG: inject causal warnings from SHARD's knowledge graph
    causal_block = ""
    try:
        from graph_rag import query_causal_context
        combined = f"{output_filename} {source[:500]} {tests[:500]}"
        causal = query_causal_context(combined)
        if causal:
            causal_block = f"\n=== CAUSAL KNOWLEDGE (from SHARD's previous studies) ===\n{causal}\n"
    except Exception:
        pass

    # Stuck tests block — tests that haven't improved across attempts
    stuck_block = ""
    if stuck_tests:
        stuck_list = "\n".join(f"  - {t}" for t in stuck_tests)
        # Detect if any stuck test looks like a performance test
        perf_keywords = ("fast", "speed", "slow", "scale", "performance", "efficient",
                         "linear", "quadratic", "bench", "latency", "throughput")
        is_perf = any(kw in t.lower() for t in stuck_tests for kw in perf_keywords)
        if is_perf:
            perf_hint = (
                "\n  4. These are PERFORMANCE tests — your algorithm may be too slow. "
                "Consider: replace nested loops with O(n log n) sorting, use dict lookups "
                "instead of list scans, avoid recomputing values in loops."
            )
        else:
            perf_hint = ""
        stuck_block = f"""
=== STUCK TESTS (failed in EVERY attempt so far — prioritize these) ===
{stuck_list}
These tests have NOT improved across {len(attempts)} attempt(s). You MUST change your approach:
  1. Read the test code literally — what exact value/type does it assert?
  2. Trace your code mentally with the test's input — what does it actually return?
  3. Your current implementation strategy is wrong for these cases — rethink from scratch.{perf_hint}

"""

    return f"""Your previous attempt FAILED the tests. Study the FULL history below and fix ALL failing tests.

=== SOURCE CODE (reference) ===
{source}

=== YOUR CURRENT CODE (attempt {len(attempts)}) ===
{current_code}

=== FAILURE HISTORY (all attempts) ===
{history}
{regression_block}{stuck_block}{causal_block}
=== FIX INSTRUCTIONS ===
1. Read the FULL history — earlier attempts may have solved some problems you later broke.
2. Fix EVERY currently failing test.
3. Do NOT regress tests that were passing in any previous attempt.
4. Output the COMPLETE corrected {output_filename}. Raw Python only."""


# -- Code extraction -----------------------------------------------------------

def _extract_code(response: str) -> str:
    """Extract Python code from LLM response, stripping markdown fences."""
    # Try to extract from markdown fences
    fence_match = re.search(r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # If no fences, try to parse the whole response as Python
    try:
        ast.parse(response)
        return response.strip()
    except SyntaxError:
        pass

    # Last resort: strip any leading/trailing non-code lines
    lines = response.strip().splitlines()
    # Remove lines that look like markdown or commentary
    cleaned = []
    for line in lines:
        if line.startswith("```") or line.startswith("Here"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _validate_syntax(code: str) -> tuple:
    """Returns (is_valid, error_message)."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"


# -- Pytest runner + parser ----------------------------------------------------

def _run_pytest(task_dir: Path, test_file: str) -> tuple:
    """Run pytest and return (all_passed, raw_output)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=long", "--no-header"],
            cwd=str(task_dir),
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        output = result.stdout + "\n" + result.stderr
        all_passed = result.returncode == 0
        return all_passed, output.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: pytest exceeded 60 seconds"
    except Exception as e:
        return False, f"RUNNER ERROR: {e}"


def _parse_pytest_output(raw: str) -> tuple:
    """Parse pytest -v output into (passed_list, failed_list, error_summary).

    Returns:
        passed:  ['test_html_identical', 'test_html_length', ...]
        failed:  ['test_has_data_processing_layer', ...]
        summary: condensed multi-line string with failure details
    """
    passed = []
    failed = []

    # Parse PASSED/FAILED lines from -v output
    for match in re.finditer(r"::(\w+)\s+(PASSED|FAILED|ERROR)", raw):
        name = match.group(1)
        status = match.group(2)
        if status == "PASSED":
            passed.append(name)
        else:
            failed.append(name)

    # Extract failure detail blocks (between FAILURES header and short test summary)
    summary_parts = []

    # Get the FAILURES section
    failures_match = re.search(
        r"={3,}\s*FAILURES\s*={3,}(.*?)(?:={3,}\s*short test summary|$)",
        raw, re.DOTALL,
    )
    if failures_match:
        failures_text = failures_match.group(1)
        # Split by test headers
        test_blocks = re.split(r"_{3,}\s*(test_\w+)\s*_{3,}", failures_text)
        # test_blocks: ['', 'test_name1', 'block1', 'test_name2', 'block2', ...]
        for i in range(1, len(test_blocks), 2):
            test_name = test_blocks[i]
            block = test_blocks[i + 1].strip() if i + 1 < len(test_blocks) else ""
            # Truncate each block to ~500 chars to keep prompt manageable
            if len(block) > 500:
                block = block[:500] + "\n... (truncated)"
            summary_parts.append(f"[{test_name}]\n{block}")

    # Also capture ERRORS section (setup failures etc.)
    errors_match = re.search(
        r"={3,}\s*ERRORS\s*={3,}(.*?)(?:={3,}\s*short test summary|$)",
        raw, re.DOTALL,
    )
    if errors_match:
        errors_text = errors_match.group(1).strip()
        if len(errors_text) > 1000:
            errors_text = errors_text[:1000] + "\n... (truncated)"
        summary_parts.append(f"[SETUP ERRORS]\n{errors_text}")

    # Fallback: if no structured failures found, use the last 30 lines
    if not summary_parts and failed:
        last_lines = "\n".join(raw.splitlines()[-30:])
        summary_parts.append(last_lines)

    error_summary = "\n\n".join(summary_parts) if summary_parts else "(no details)"
    return passed, failed, error_summary


# -- Atomic file write ---------------------------------------------------------

def _write_file(path: Path, content: str):
    """Atomic write: write to temp file then replace."""
    fd, tmp = tempfile.mkstemp(suffix=".py", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# -- Main loop -----------------------------------------------------------------

async def run_benchmark_loop(
    task_dir: str | Path,
    max_attempts: int = MAX_ATTEMPTS_DEFAULT,
    progress_cb=None,
    use_episodic_memory: bool = False,
    use_swarm: bool = False,
    use_concurrency_sim: bool = True,  # auto-detects if task needs it
) -> BenchmarkResult:
    """Run the closed feedback loop on a benchmark task.

    progress_cb: optional async callable(dict) — called on attempt_start and attempt_done events.
    use_episodic_memory: if True, inject past session history into Attempt 1 prompt.

    Returns BenchmarkResult with success=True if all tests pass.
    """
    task_dir = Path(task_dir).resolve()
    t_start = time.time()

    # -- 1. Load task files ------------------------------------------------
    readme_path = task_dir / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    # Discover source file (the buggy/legacy code to fix/refactor)
    # Convention: any .py that isn't test_* or __* is the source
    source_files = sorted(
        f for f in task_dir.glob("*.py")
        if not f.name.startswith("test_") and not f.name.startswith("__")
    )
    if not source_files:
        raise FileNotFoundError(f"No source file found in {task_dir}")
    source_path = source_files[0]
    source = source_path.read_text(encoding="utf-8")

    # Discover test file
    test_files = sorted(task_dir.glob("test_task*.py")) or sorted(task_dir.glob("test_*.py"))
    if not test_files:
        raise FileNotFoundError(f"No test file found in {task_dir}")
    test_file = test_files[0]
    tests = test_file.read_text(encoding="utf-8")

    # Discover expected output filename from test file
    # Look for patterns like: fixed_pipeline.py not found, "refactored_agent.py"
    output_name_match = re.search(r'(\w+\.py)\s+not found', tests)
    if not output_name_match:
        output_name_match = re.search(r'"(\w+\.py)".*not found', tests)
    if output_name_match:
        output_filename = output_name_match.group(1)
    else:
        # Fallback: derive from source name
        output_filename = "fixed_" + source_path.name
    output_path = task_dir / output_filename

    print()
    print("=" * 68)
    print("  SHARD Benchmark Loop")
    print(f"  Task: {task_dir.name}")
    print(f"  Source: {source_path.name} -> {output_filename}")
    print(f"  Max attempts: {max_attempts}")
    print(f"  Episodic memory: {'ON' if use_episodic_memory else 'OFF'}")
    print(f"  Swarm engine:    {'ON' if (use_swarm and swarm_complete) else 'OFF'}")

    # Detect if task needs concurrency simulation
    _run_conc_sim = (
        use_concurrency_sim
        and _conc_sim_available
        and is_concurrency_task(readme, tests)
    )
    print(f"  Concurrency sim: {'ON' if _run_conc_sim else 'OFF'}")
    print("=" * 68)

    # -- Load episodic memory (always load, inject only if flag is set) ----
    task_key = task_dir.name
    past_episodes = load_episodes(task_key)
    experience_summary = build_experience_summary(past_episodes) if (use_episodic_memory and past_episodes) else ""
    if experience_summary:
        print(f"  [memory] Injecting {len(past_episodes)} past session(s) into Attempt 1 prompt")

    # -- Query Knowledge Base (always run independent of flag) --------------
    kb_used = False
    kb_chars = 0
    try:
        query_text = readme[:300].replace('\n', ' ').strip() if readme else task_key
        kb_data = query_knowledge_base(query_text)
        if kb_data:
            kb_used = True
            kb_chars = len(kb_data)
            if experience_summary:
                experience_summary += "\n\n" + kb_data
            else:
                experience_summary = kb_data
            print(f"  [kb] Injected {kb_chars} chars of knowledge base context into prompt")
    except Exception as e:
        print(f"  [kb] Knowledge Base injection failed: {e}")

    # -- 2. Loop -----------------------------------------------------------
    attempts = []

    for attempt_num in range(1, max_attempts + 1):
        t_attempt = time.time()
        if attempt_num == 1:
            mode = "LLM SOLO"
        elif use_swarm and swarm_complete:
            mode = "SWARM"
        else:
            mode = "SHARD FEEDBACK"
        print(f"\n{'-' * 50}")
        print(f"  Attempt {attempt_num}/{max_attempts}  [{mode}]")
        print(f"{'-' * 50}")

        # -- Build prompt (or skip for swarm which builds internally) --
        prompt = ""  # swarm path does not use a flat prompt
        if attempt_num == 1:
            prompt = _build_initial_prompt(source, readme, output_filename, experience_summary)
            print(f"  [LLM SOLO] Initial prompt ({len(prompt):,} chars)")
        elif mode == "SWARM":
            print(f"  [SWARM] Architect → Coder → Critic pipeline")
        else:
            # Always pass the last *syntactically valid* code — never pass broken code
            last_valid = next(
                (r for r in reversed(attempts) if r.syntax_valid),
                None,
            )
            current_code = last_valid.code if last_valid else source
            stuck_tests = _detect_stuck_tests(attempts)
            if stuck_tests:
                print(f"  [stuck] {len(stuck_tests)} test(s) stuck across attempts: {stuck_tests}")
            prompt = _build_correction_prompt(
                source, tests, current_code, attempts, output_filename,
                stuck_tests=stuck_tests,
            )
            print(f"  [SHARD FEEDBACK] Correction prompt ({len(prompt):,} chars)")

        if progress_cb:
            try:
                await progress_cb({"event": "attempt_start", "attempt": attempt_num, "mode": mode})
            except Exception:
                pass

        # -- Call LLM or Swarm -----------------------------------------
        if mode == "SWARM":
            swarm_stuck = _detect_stuck_tests(attempts)
            if swarm_stuck:
                print(f"  [stuck] {len(swarm_stuck)} test(s) stuck — injecting into Architect: {swarm_stuck}")
            print("  [swarm] Calling... ", end="", flush=True)
            try:
                response = await swarm_complete(
                    source=source,
                    tests=tests,
                    attempts=attempts,
                    output_filename=output_filename,
                    max_tokens=LLM_MAX_TOKENS,
                    temperature=LLM_TEMPERATURE,
                    stuck_tests=swarm_stuck if swarm_stuck else None,
                )
                print(f"OK ({len(response):,} chars)")
            except Exception as e:
                print(f"FAILED: {e}")
                attempts.append(AttemptRecord(
                    attempt=attempt_num, code="", tests_passed=[], tests_failed=[],
                    error_summary=f"Swarm call failed: {e}", raw_pytest="",
                    syntax_valid=False, elapsed=time.time() - t_attempt,
                ))
                continue
        else:
            print("  [llm] Calling... ", end="", flush=True)
            try:
                response = await llm_complete(
                    prompt=prompt,
                    system=SYSTEM_PROMPT,
                    max_tokens=LLM_MAX_TOKENS,
                    temperature=LLM_TEMPERATURE,
                )
                print(f"OK ({len(response):,} chars)")
            except Exception as e:
                print(f"FAILED: {e}")
                attempts.append(AttemptRecord(
                    attempt=attempt_num, code="", tests_passed=[], tests_failed=[],
                    error_summary=f"LLM call failed: {e}", raw_pytest="",
                    syntax_valid=False, elapsed=time.time() - t_attempt,
                ))
                continue

        # -- Extract code ----------------------------------------------
        code = _extract_code(response)

        # -- Validate syntax -------------------------------------------
        syntax_ok, syntax_err = _validate_syntax(code)
        if not syntax_ok:
            elapsed = time.time() - t_attempt
            print(f"  [syntax] INVALID: {syntax_err}")
            attempts.append(AttemptRecord(
                attempt=attempt_num, code=code, tests_passed=[], tests_failed=[],
                error_summary=syntax_err, raw_pytest="",
                syntax_valid=False, elapsed=elapsed,
            ))
            if progress_cb:
                try:
                    await progress_cb({"event": "attempt_done", "attempt": attempt_num,
                                       "success": False, "syntax_error": True,
                                       "passed": 0, "failed": 0, "failed_tests": []})
                except Exception:
                    pass
            continue

        print("  [syntax] Valid")

        # -- Write file ------------------------------------------------
        _write_file(output_path, code)
        print(f"  [write] {output_path.name} ({len(code.splitlines())} lines)")

        # -- Concurrency probe (before pytest — catches races early) ----
        conc_report_text = ""
        if _run_conc_sim:
            print(f"  [conc_sim] Probing thread safety... ", end="", flush=True)
            try:
                conc_report = probe_concurrency(code, output_path, readme, tests)
                if conc_report.triggered:
                    if conc_report.passed:
                        print("OK (thread-safe)")
                    else:
                        print(f"ISSUES DETECTED")
                        print(f"    {conc_report.summary}")
                        conc_report_text = format_for_prompt(conc_report)
                        # Inject into experience_summary so correction prompt sees it
                        experience_summary = (
                            (experience_summary + "\n\n" if experience_summary else "")
                            + conc_report_text
                        )
                else:
                    print("skipped")
            except Exception as _ce:
                print(f"ERROR ({_ce})")

        # -- Run pytest ------------------------------------------------
        print(f"  [pytest] Running {test_file.name}... ", end="", flush=True)
        all_passed, raw_pytest = _run_pytest(task_dir, test_file.name)

        passed, failed, error_summary = _parse_pytest_output(raw_pytest)
        elapsed = time.time() - t_attempt

        if all_passed:
            print(f"ALL PASSED ({len(passed)} tests)")
            _push_benchmark_event(task_key, attempt_num, len(passed), 0, mode)
            attempts.append(AttemptRecord(
                attempt=attempt_num, code=code, tests_passed=passed,
                tests_failed=[], error_summary="", raw_pytest=raw_pytest,
                syntax_valid=True, elapsed=elapsed,
            ))
            if progress_cb:
                try:
                    await progress_cb({"event": "attempt_done", "attempt": attempt_num,
                                       "success": True, "syntax_error": False,
                                       "passed": len(passed), "failed": 0, "failed_tests": []})
                except Exception:
                    pass
            # Victory
            total_elapsed = time.time() - t_start
            print(f"\n{'=' * 68}")
            print(f"  VICTORY on attempt {attempt_num}/{max_attempts}")
            print(f"  Tests passed: {len(passed)}")
            print(f"  Total time: {total_elapsed:.1f}s")
            print(f"{'=' * 68}\n")
            save_episode(task_key, success=True, total_attempts=attempt_num,
                         attempts=attempts, final_code=code,
                         kb_used=kb_used, kb_chars=kb_chars)
            return BenchmarkResult(
                task_dir=str(task_dir), success=True,
                total_attempts=attempt_num, attempts=attempts,
                final_code=code, elapsed_total=total_elapsed,
                kb_used=kb_used, kb_chars=kb_chars,
            )
        else:
            print(f"{len(passed)} passed, {len(failed)} failed")
            _push_benchmark_event(task_key, attempt_num, len(passed), len(failed), mode)
            for name in failed[:5]:
                print(f"    FAIL: {name}")
            if len(failed) > 5:
                print(f"    ... and {len(failed) - 5} more")

            attempts.append(AttemptRecord(
                attempt=attempt_num, code=code, tests_passed=passed,
                tests_failed=failed, error_summary=error_summary,
                raw_pytest=raw_pytest, syntax_valid=True, elapsed=elapsed,
            ))
            if progress_cb:
                try:
                    await progress_cb({"event": "attempt_done", "attempt": attempt_num,
                                       "success": False, "syntax_error": False,
                                       "passed": len(passed), "failed": len(failed),
                                       "failed_tests": failed[:5]})
                except Exception:
                    pass

    # -- All attempts exhausted --------------------------------------------
    total_elapsed = time.time() - t_start
    best = max(attempts, key=lambda a: len(a.tests_passed)) if attempts else None
    best_score = len(best.tests_passed) if best else 0

    print(f"\n{'=' * 68}")
    print(f"  FAILED after {max_attempts} attempts")
    print(f"  Best score: {best_score}/{best_score + len(best.tests_failed) if best else 0} tests")
    print(f"  Total time: {total_elapsed:.1f}s")
    print(f"{'=' * 68}\n")
    save_episode(task_key, success=False, total_attempts=max_attempts,
                 attempts=attempts, final_code="",
                 kb_used=kb_used, kb_chars=kb_chars)

    # -- Feed failure signal to NightRunner improvement queue --------------
    # Derive study topics from the task README so NightRunner knows what to study.
    try:
        from improvement_engine import ImprovementEngine
        study_topics = _derive_study_topics(task_key, readme, best)
        if study_topics:
            added = ImprovementEngine().enqueue_topics(study_topics)
            print(f"  [benchmark→NightRunner] Queued {added} study topic(s): {study_topics}")
    except Exception as e:
        print(f"  [benchmark→NightRunner] Could not queue topics: {e}")
    return BenchmarkResult(
        task_dir=str(task_dir), success=False,
        total_attempts=max_attempts, attempts=attempts,
        final_code=attempts[-1].code if attempts else "",
        elapsed_total=total_elapsed,
        kb_used=kb_used, kb_chars=kb_chars,
    )


# -- CLI entry point -----------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="SHARD Benchmark Loop — closed feedback loop for refactoring tasks"
    )
    parser.add_argument("task_dir", help="Path to benchmark task directory")
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS_DEFAULT,
                        help=f"Max correction attempts (default: {MAX_ATTEMPTS_DEFAULT})")
    parser.add_argument("--use-swarm", action="store_true", default=False,
                        help="Enable 3-agent Swarm pipeline on Attempt 2+")
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load .env for API keys
    try:
        from dotenv import load_dotenv
        env_dir = Path(__file__).resolve().parent.parent
        load_dotenv(env_dir / ".env")
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass

    result = asyncio.run(run_benchmark_loop(args.task_dir, max_attempts=args.max_attempts, use_swarm=args.use_swarm))
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
