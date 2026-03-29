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
import json
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


# -- Environment capability probe ----------------------------------------------

def _probe_environment() -> dict:
    """Check what runtimes/tools are actually available in this environment.

    Returns a dict: {tool: {"available": bool, "version": str|None}}
    Results are cached for the process lifetime (probing is slow).
    """
    if hasattr(_probe_environment, "_cache"):
        return _probe_environment._cache

    probes = {
        "python":  [sys.executable, "--version"],
        "pytest":  [sys.executable, "-m", "pytest", "--version"],
        "node":    ["node", "--version"],
        "npm":     ["npm",  "--version"],
        "jest":    ["npx",  "jest", "--version"],
        "g++":     ["g++",  "--version"],
        "cargo":   ["cargo","--version"],
        "go":      ["go",   "version"],
        "java":    ["java", "-version"],
    }
    results = {}
    for tool, cmd in probes.items():
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            ok = r.returncode == 0
            ver_line = (r.stdout + r.stderr).strip().splitlines()
            version = ver_line[0][:60] if ver_line else None
            results[tool] = {"available": ok, "version": version if ok else None}
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            results[tool] = {"available": False, "version": None}

    _probe_environment._cache = results
    return results


def _format_env_summary(probe: dict) -> str:
    """Return a compact one-line string of available runtimes."""
    available = [t for t, v in probe.items() if v["available"]]
    missing   = [t for t, v in probe.items() if not v["available"]]
    lines = [f"Available: {', '.join(available)}"]
    if missing:
        lines.append(f"Missing:   {', '.join(missing)}")
    return "\n".join(lines)


# -- Self-profile builder ------------------------------------------------------

def _build_self_profile(task_key: str, lang: str) -> str:
    """Build a self-awareness summary to inject into the initial prompt.

    Combines:
    - Environment capabilities (what runtimes are present)
    - Capability graph node count (breadth of knowledge)
    - Benchmark episode history (past success rate on similar tasks)
    - Language-specific confidence level

    Returns a formatted string ready to include in the prompt.
    """
    sections = []

    # 1. Environment probe
    probe = _probe_environment()
    lang_tool = {"python": "pytest", "javascript": "jest", "cpp": "g++",
                 "rust": "cargo", "go": "go", "java": "java"}.get(lang, "pytest")
    lang_available = probe.get(lang_tool, {}).get("available", False)
    lang_version   = probe.get(lang_tool, {}).get("version", "unknown")

    env_status = f"READY ({lang_version})" if lang_available else "NOT AVAILABLE — expect runner errors"
    sections.append(f"Runtime ({lang}): {env_status}")

    # 2. Capability graph — count acquired nodes as proxy for knowledge breadth
    try:
        cap_path = Path(__file__).resolve().parent.parent / "shard_memory" / "capability_graph.json"
        if cap_path.exists():
            graph = json.loads(cap_path.read_text(encoding="utf-8"))
            n_nodes = len(graph)
            # Find nodes related to current language/task
            lang_keywords = {
                "python": ["python", "algorithm", "data structure", "debugging"],
                "javascript": ["javascript", "node", "async", "web"],
                "cpp": ["c++", "memory", "pointer", "system"],
            }.get(lang, [])
            related = [k for k in graph if any(kw in k.lower() for kw in lang_keywords)]
            sections.append(
                f"Knowledge graph: {n_nodes} acquired concepts"
                + (f", {len(related)} related to {lang}" if related else "")
            )
    except Exception:
        pass

    # 3. Benchmark episode history — success rate on similar tasks
    try:
        from benchmark_memory import load_episodes
        past = load_episodes(task_key)
        if past:
            n_total   = len(past)
            n_success = sum(1 for e in past if e.get("success"))
            rate      = round(n_success / n_total * 100)
            best_ep   = max(past, key=lambda e: e.get("total_attempts", 99), default=None)
            sections.append(
                f"Episode history ({task_key}): {n_success}/{n_total} sessions solved ({rate}%)"
            )
            # Warn if this task has a poor track record
            if n_total >= 2 and rate < 50:
                sections.append(
                    f"  WARNING: this task has been hard historically — "
                    f"prioritize reading the failure history carefully"
                )
        else:
            sections.append(f"Episode history: no prior sessions for '{task_key}' — first attempt")
    except Exception:
        pass

    if not sections:
        return ""

    return (
        "=== SHARD SELF-PROFILE ===\n"
        + "\n".join(f"  {s}" for s in sections)
        + "\n"
    )


def _push_self_awareness_event(consciousness, probe: dict, profile: str, lang: str):
    """Push capability probe + self-assessment events to CognitionCore."""
    if not consciousness:
        return
    try:
        available = [t for t, v in probe.items() if v["available"]]
        missing   = [t for t, v in probe.items() if not v["available"]]
        consciousness.push_event("capability_probe", {
            "lang":      lang,
            "available": available,
            "missing":   missing,
            "ready":     probe.get({"python":"pytest","javascript":"jest",
                                    "cpp":"g++"}.get(lang,"pytest"), {}).get("available", False),
        })
        consciousness.push_event("self_assessment", {
            "profile_lines": len(profile.splitlines()),
            "lang": lang,
            "summary": profile[:300],
        })
    except Exception:
        pass


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

# -- Language detection --------------------------------------------------------

_LANG_MAP = {
    ".py":  "python",
    ".js":  "javascript",
    ".ts":  "javascript",
    ".cpp": "cpp",
    ".cc":  "cpp",
    ".c":   "c",
    ".rs":  "rust",
    ".go":  "go",
    ".java":"java",
    ".rb":  "ruby",
}

def _detect_language(path: Path) -> str:
    """Detect language from file extension. Defaults to 'python'."""
    return _LANG_MAP.get(path.suffix.lower(), "python")


_SYSTEM_PROMPTS = {
    "python": (
        "You are a precise Python bug-fixing and refactoring agent. "
        "Output ONLY valid Python source code. "
        "No markdown fences, no explanations, no commentary. "
        "Every function must be fully implemented — no ellipsis, no pass, no TODO."
    ),
    "javascript": (
        "You are a precise JavaScript/Node.js bug-fixing agent. "
        "Output ONLY valid JavaScript source code (CommonJS or ESM matching the input style). "
        "No markdown fences, no explanations, no commentary. "
        "Every function must be fully implemented — no ellipsis, no TODO comments."
    ),
    "cpp": (
        "You are a precise C++ bug-fixing agent. "
        "Output ONLY valid C++17 source code. "
        "No markdown fences, no explanations, no commentary. "
        "Every function must be fully implemented — no ellipsis, no TODO."
    ),
    "rust": (
        "You are a precise Rust bug-fixing agent. "
        "Output ONLY valid Rust source code. "
        "No markdown fences, no explanations, no commentary."
    ),
    "go": (
        "You are a precise Go bug-fixing agent. "
        "Output ONLY valid Go source code. "
        "No markdown fences, no explanations, no commentary."
    ),
    "java": (
        "You are a precise Java bug-fixing agent. "
        "Output ONLY valid Java source code. "
        "No markdown fences, no explanations, no commentary."
    ),
}

def _get_system_prompt(lang: str) -> str:
    return _SYSTEM_PROMPTS.get(lang, _SYSTEM_PROMPTS["python"])


# Legacy alias kept for any external callers
SYSTEM_PROMPT = _SYSTEM_PROMPTS["python"]


def _derive_study_topics(task_key: str, readme: str, best_attempt) -> list:
    """Derive 1-2 study topics from a failed benchmark task.

    Uses the task name and failed test names as signals — no LLM call needed.
    Topics are fed to NightRunner's improvement queue so the next night session
    studies exactly what the benchmark struggled with.
    """
    topics = []

    # Skip temp dirs from shard_challenge (random names like "shard_challenge_abc123")
    if task_key.startswith("shard_challenge"):
        return []

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
    # Skip HTML comments and XML/Repomix injected content
    if readme:
        first_line = next(
            (l.strip() for l in readme.splitlines()
             if len(l.strip()) > 20
             and not l.strip().startswith("<!--")
             and not l.strip().startswith("<")),
            ""
        )
        if first_line and len(first_line.split()) >= 4:
            words = first_line.split()[:10]
            readme_topic = " ".join(words).rstrip(".,:")
            if readme_topic not in topics:
                topics.append(readme_topic)

    return topics[:2]  # max 2 topics per failed task


def _extract_multi_bug_list(readme: str) -> str:
    """Detect and extract an explicit bug list from the README.

    Returns a formatted 'BUGS TO FIX' block if the task has a multi-bug table
    or numbered bug list, otherwise returns an empty string.
    """
    if not readme:
        return ""

    lines = readme.splitlines()
    bug_lines = []

    # Pattern 1: markdown table with bug index column (| # | ... | Bug | ...)
    in_table = False
    for line in lines:
        if re.search(r"\|\s*#\s*\|", line, re.IGNORECASE):
            in_table = True
            continue
        if in_table:
            if line.strip().startswith("|") and not re.match(r"\|[-| ]+\|", line):
                # Data row — extract columns 2 and 3 (function + bug description)
                cols = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cols) >= 3:
                    bug_lines.append(f"  - [{cols[0]}] {cols[1]}: {cols[2]}")
            elif not line.strip().startswith("|") and bug_lines:
                break

    # Pattern 2: numbered list BUT only inside a section whose heading contains "bug"
    if not bug_lines:
        in_bug_section = False
        for line in lines:
            if re.match(r"#+\s", line):
                in_bug_section = bool(re.search(r"\bbug", line, re.IGNORECASE))
            if in_bug_section:
                if re.match(r"\s*(?:Bug\s*)?\d+[\.\)]\s+\S", line, re.IGNORECASE):
                    bug_lines.append(f"  - {line.strip()}")
                elif re.match(r"#+\s*Bug\s+\d+", line, re.IGNORECASE):
                    bug_lines.append(f"  - {line.strip('#').strip()}")

    if not bug_lines:
        return ""

    n = len(bug_lines)
    return (
        f"\n=== MULTI-BUG TASK: {n} bugs must ALL be fixed in one shot ===\n"
        f"Do NOT wait for test failures to discover bugs — fix ALL of these simultaneously:\n"
        + "\n".join(bug_lines)
        + "\nApproach: identify every root cause first, then write the complete fixed file.\n"
    )


def _measure_performance_delta(task_dir: Path, legacy_file: str,
                                candidate_file: str, call_expr: str,
                                n: int = 5) -> str:
    """Run legacy and candidate side-by-side and return a speedup report.

    Args:
        task_dir:       Path to the task directory.
        legacy_file:    Filename of the original slow code (e.g. 'legacy_processor.py').
        candidate_file: Filename of the candidate fixed code (e.g. 'optimized_processor.py').
        call_expr:      Python expression to benchmark (e.g. 'process_transactions(data)').
        n:              Number of timing repetitions.

    Returns a formatted string to inject into the correction prompt.
    Returns empty string on any error.
    """
    try:
        script = f"""
import sys, timeit, importlib.util, json
sys.path.insert(0, {repr(str(task_dir))})

def _load(fname):
    import importlib.util
    spec = importlib.util.spec_from_file_location("_mod", {repr(str(task_dir))} + "/" + fname)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

try:
    legacy = _load({repr(legacy_file)})
    cand   = _load({repr(candidate_file)})
    # Build shared setup
    setup_legacy = "from __main__ import legacy; " + "import sys; sys.path.insert(0, {repr(str(task_dir))})"
    setup_cand   = "from __main__ import cand;   " + "import sys; sys.path.insert(0, {repr(str(task_dir))})"

    # Use timeit with a simple callable approach
    import time
    def _time(mod, n=5):
        fn = getattr(mod, {repr(call_expr.split("(")[0])}, None)
        if fn is None:
            return None
        # Warm up
        try: fn(*([None] if "None" in {repr(call_expr)} else []))
        except: pass
        times = []
        for _ in range(n):
            t = time.perf_counter()
            try: fn()
            except: pass
            times.append(time.perf_counter() - t)
        return min(times)

    import time

    # More robust: just import and call process_transactions with real data
    import importlib
    legacy_mod = importlib.import_module("legacy_processor") if {repr(legacy_file)} == "legacy_processor.py" else legacy
    cand_mod   = cand

    fn_name = {repr(call_expr.split("(")[0].strip())}
    legacy_fn = getattr(legacy_mod, fn_name, None)
    cand_fn   = getattr(cand_mod,   fn_name, None)

    if legacy_fn is None or cand_fn is None:
        print(json.dumps({{"error": "function not found"}}))
        sys.exit(0)

    # Generate test data matching what tests use
    import random
    data = []
    categories = ["food", "electronics", "clothing", "books"]
    for i in range(10000):
        data.append({{"id": i, "amount": round(random.uniform(1, 1000), 2),
                      "category": random.choice(categories), "status": "completed"}})

    legacy_times = []
    cand_times   = []
    for _ in range({n}):
        t = time.perf_counter(); legacy_fn(data); legacy_times.append(time.perf_counter()-t)
        t = time.perf_counter(); cand_fn(data);   cand_times.append(time.perf_counter()-t)

    legacy_best = min(legacy_times)
    cand_best   = min(cand_times)
    speedup = legacy_best / cand_best if cand_best > 0 else 0
    pct = (speedup - 1) * 100
    print(json.dumps({{"legacy_ms": round(legacy_best*1000,1), "cand_ms": round(cand_best*1000,1),
                       "speedup": round(speedup, 2), "faster_pct": round(pct, 1)}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
            cwd=str(task_dir),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        data = json.loads(result.stdout.strip())
        if "error" in data:
            return ""
        pct = data["faster_pct"]
        legacy_ms = data["legacy_ms"]
        cand_ms = data["cand_ms"]
        speedup = data["speedup"]
        target_met = pct >= 30
        status = "✓ TARGET MET" if target_met else "✗ TARGET NOT MET (need ≥30%)"
        return (
            f"\n=== PERFORMANCE MEASUREMENT (actual timing) ===\n"
            f"Legacy:    {legacy_ms}ms\n"
            f"Your code: {cand_ms}ms\n"
            f"Speedup:   {speedup}x ({pct:+.1f}%) — {status}\n"
            + ("" if target_met else
               "You need to be at least 30% faster than legacy. "
               "Replace O(n²) loops with dict lookups, use collections.Counter/defaultdict, "
               "avoid redundant iterations over the same data.\n")
        )
    except Exception:
        return ""


def _build_initial_prompt(source: str, readme: str, output_filename: str,
                          experience_summary: str = "", lang: str = "python") -> str:
    memory_block = f"\n{experience_summary}\n" if experience_summary else ""
    multi_bug_block = _extract_multi_bug_list(readme)
    lang_label = {"python": "Python", "javascript": "JavaScript", "cpp": "C++",
                  "rust": "Rust", "go": "Go", "java": "Java"}.get(lang, lang)
    return f"""Read the task description and source code below.
Your job: create {output_filename} — an optimized/fixed version of the source code.
{memory_block}{multi_bug_block}
=== TASK DESCRIPTION (read this FIRST — it explains what to do) ===
{readme}

=== SOURCE CODE (the code to fix/refactor) ===
{source}

Write the COMPLETE {output_filename} file. Output raw {lang_label} only."""


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
    stuck_tests: list = None, lang: str = "python", diagnostic: str = "",
    task_dir: Path = None,
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
            # Try to get a real performance measurement
            perf_measurement = ""
            if task_dir:
                # Detect legacy file and candidate file names from output_filename
                _legacy_candidates = ["legacy_processor.py", "legacy.py", "slow.py"]
                _legacy_file = next(
                    (f for f in _legacy_candidates if (task_dir / f).exists()), None
                )
                if _legacy_file and (task_dir / output_filename).exists():
                    _fn_name = "process_transactions"  # most common perf task pattern
                    perf_measurement = _measure_performance_delta(
                        task_dir, _legacy_file, output_filename, f"{_fn_name}(data)"
                    )
            perf_hint = (
                "\n  4. These are PERFORMANCE tests — your algorithm may be too slow. "
                "Consider: replace nested loops with O(n log n) sorting, use dict lookups "
                "instead of list scans, avoid recomputing values in loops."
                + (f"\n{perf_measurement}" if perf_measurement else "")
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

    _lang_labels = {"python": "Python", "javascript": "JavaScript", "cpp": "C++",
                    "rust": "Rust", "go": "Go", "java": "Java"}
    lang_label = _lang_labels.get(lang, lang.capitalize())

    return f"""Your previous attempt FAILED the tests. Study the FULL history below and fix ALL failing tests.

=== SOURCE CODE (reference) ===
{source}

=== YOUR CURRENT CODE (attempt {len(attempts)}) ===
{current_code}

=== FAILURE HISTORY (all attempts) ===
{history}
{regression_block}{stuck_block}{diagnostic}{causal_block}
=== FIX INSTRUCTIONS ===
1. Read the FULL history — earlier attempts may have solved some problems you later broke.
2. Fix EVERY currently failing test.
3. Do NOT regress tests that were passing in any previous attempt.
4. Output the COMPLETE corrected {output_filename}. Raw {lang_label} only."""


# -- Code extraction -----------------------------------------------------------

def _extract_code(response: str, lang: str = "python") -> str:
    """Extract code from LLM response, stripping markdown fences (language-aware)."""
    # Try to extract from markdown fences — all common language identifiers
    fence_match = re.search(
        r"```(?:python|javascript|js|typescript|ts|cpp|c\+\+|c|rust|go|java|ruby)?\s*\n(.*?)```",
        response, re.DOTALL
    )
    if fence_match:
        return fence_match.group(1).strip()

    # For Python: try to parse the whole response as Python
    if lang == "python":
        try:
            ast.parse(response)
            return response.strip()
        except SyntaxError:
            pass

    # Last resort: strip any leading/trailing non-code lines
    lines = response.strip().splitlines()
    cleaned = []
    for line in lines:
        if line.startswith("```") or line.startswith("Here"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _validate_syntax(code: str, lang: str = "python") -> tuple:
    """Returns (is_valid, error_message). Language-aware syntax check."""
    if lang == "python":
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}: {e.msg}"
    elif lang == "javascript":
        try:
            result = subprocess.run(
                ["node", "--check", "/dev/stdin"],
                input=code, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return True, ""
            return False, result.stderr[:300]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True, ""  # node not available in this env — skip, let tests catch it
    elif lang == "cpp":
        try:
            result = subprocess.run(
                ["g++", "-std=c++17", "-fsyntax-only", "-x", "c++", "-"],
                input=code, capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return True, ""
            return False, result.stderr[:300]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True, ""  # g++ not available in this env — skip
    return True, ""  # unknown language: skip validation, let test runner catch it


# -- Test runner + parser (multi-language) ------------------------------------

def _run_tests(task_dir: Path, test_file: str, lang: str = "python",
               source_file: str = None) -> tuple:
    """Run tests for the given language. Returns (all_passed, raw_output)."""
    try:
        if lang == "python":
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_file, "-v", "--tb=long", "--no-header"],
                cwd=str(task_dir),
                capture_output=True, text=True, timeout=PYTEST_TIMEOUT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        elif lang == "javascript":
            result = subprocess.run(
                ["npx", "jest", test_file, "--no-coverage", "--json"],
                cwd=str(task_dir),
                capture_output=True, text=True, timeout=PYTEST_TIMEOUT,
                env={**os.environ, "NODE_ENV": "test"},
            )
        elif lang == "cpp":
            exe_path = task_dir / "_shard_test_runner"
            compile_cmd = ["g++", "-std=c++17", "-o", str(exe_path), test_file]
            if source_file:
                compile_cmd.append(source_file)
            compile_cmd += ["-lgtest", "-lgtest_main", "-lpthread"]
            compile_result = subprocess.run(
                compile_cmd, cwd=str(task_dir),
                capture_output=True, text=True, timeout=30,
            )
            if compile_result.returncode != 0:
                return False, "COMPILE ERROR:\n" + compile_result.stderr
            result = subprocess.run(
                [str(exe_path)], cwd=str(task_dir),
                capture_output=True, text=True, timeout=PYTEST_TIMEOUT,
            )
        else:
            return False, f"UNSUPPORTED LANGUAGE: {lang}"

        output = result.stdout + "\n" + result.stderr
        all_passed = result.returncode == 0
        return all_passed, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT: test runner exceeded {PYTEST_TIMEOUT} seconds"
    except Exception as e:
        return False, f"RUNNER ERROR: {e}"


# Legacy alias for any external callers
def _run_pytest(task_dir: Path, test_file: str) -> tuple:
    return _run_tests(task_dir, test_file, lang="python")


# -- Execution diagnostics -----------------------------------------------------

def _run_diagnostic(task_dir: Path, output_path: Path, test_source: str,
                    stuck_tests: list, lang: str = "python") -> str:
    """Run stuck tests individually and capture actual vs expected values.

    Gives the LLM concrete "your code returned X, test expected Y" feedback
    instead of just an assertion error. Works for Python, JavaScript, C++.

    Returns a formatted diagnostic block ready to inject into the correction prompt.
    """
    if not stuck_tests or not output_path.exists():
        return ""

    diag_parts = []

    if lang == "python":
        for test_name in stuck_tests[:4]:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "-x", f"::{test_name}",
                     "--tb=short", "--no-header", "-q"],
                    cwd=str(task_dir),
                    capture_output=True, text=True, timeout=15,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                output = (result.stdout + result.stderr).strip()
            except Exception as e:
                output = f"(diagnostic run failed: {e})"

            diag_lines = []
            for line in output.splitlines():
                s = line.strip()
                if (s.startswith("E ") or s.startswith("assert ")
                        or "AssertionError" in s or "TypeError" in s
                        or "ValueError" in s or s.startswith(">")):
                    diag_lines.append(s)

            detail = "\n".join(diag_lines[:12]) if diag_lines else output[-300:]
            if detail:
                diag_parts.append(f"[{test_name}]\n{detail}")

    elif lang == "javascript":
        # Jest already prints Expected/Received — re-run and filter those lines
        try:
            result = subprocess.run(
                ["npx", "jest", "--verbose", "--no-coverage",
                 "--testNamePattern", "|".join(re.escape(t) for t in stuck_tests[:4])],
                cwd=str(task_dir),
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "NODE_ENV": "test"},
            )
            output = (result.stdout + result.stderr).strip()
        except Exception as e:
            output = f"(diagnostic run failed: {e})"

        diag_lines = []
        for line in output.splitlines():
            s = line.strip()
            if any(kw in s for kw in ("Expected", "Received", "●", "✕", "✗", "FAIL")):
                diag_lines.append(s)
        detail = "\n".join(diag_lines[:20]) if diag_lines else output[-400:]
        if detail:
            diag_parts.append(f"[jest diagnostics]\n{detail}")

    elif lang == "cpp":
        # GoogleTest prints "Value of: ...\nActual: ...\nExpected: ..." — extract those
        try:
            exe_path = task_dir / "_shard_test_runner"
            if exe_path.exists():
                filter_expr = ":".join(f"*{t}*" for t in stuck_tests[:4])
                result = subprocess.run(
                    [str(exe_path), f"--gtest_filter={filter_expr}"],
                    cwd=str(task_dir),
                    capture_output=True, text=True, timeout=15,
                )
                output = (result.stdout + result.stderr).strip()
                diag_lines = [
                    l.strip() for l in output.splitlines()
                    if any(kw in l for kw in ("Value of", "Actual", "Expected",
                                               "FAILED", "error:", "which is"))
                ]
                detail = "\n".join(diag_lines[:20]) if diag_lines else output[-400:]
                if detail:
                    diag_parts.append(f"[gtest diagnostics]\n{detail}")
        except Exception as e:
            diag_parts.append(f"[gtest diagnostic failed: {e}]")

    if not diag_parts:
        return ""

    return (
        "\n=== EXECUTION DIAGNOSTICS (what your code actually does on stuck tests) ===\n"
        + "\n\n".join(diag_parts)
        + "\n"
    )


def _parse_test_output(raw: str, lang: str = "python") -> tuple:
    """Parse test runner output into (passed_list, failed_list, error_summary)."""
    if lang == "javascript":
        return _parse_jest_output(raw)
    elif lang == "cpp":
        return _parse_gtest_output(raw)
    return _parse_pytest_output(raw)


def _parse_jest_output(raw: str) -> tuple:
    """Parse Jest --json output."""
    import json as _json
    passed, failed, errors = [], [], []
    try:
        # Jest --json writes JSON to stdout; stderr may contain warnings before it
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{") and '"testResults"' in line:
                data = _json.loads(line)
                for suite in data.get("testResults", []):
                    for t in suite.get("testResults", []):
                        name = t.get("fullName") or t.get("title", "unknown")
                        if t.get("status") == "passed":
                            passed.append(name)
                        else:
                            failed.append(name)
                            msgs = t.get("failureMessages", [])
                            if msgs:
                                errors.append(f"[{name}]\n{msgs[0][:400]}")
                break
    except Exception:
        # Fallback: text output (jest without --json or parse error)
        for m in re.finditer(r"(PASS|FAIL)\s+(\S+)", raw):
            if m.group(1) == "PASS":
                passed.append(m.group(2))
            else:
                failed.append(m.group(2))
    error_summary = "\n\n".join(errors) if errors else raw[-800:] if failed else "(no details)"
    return passed, failed, error_summary


def _parse_gtest_output(raw: str) -> tuple:
    """Parse GoogleTest text output."""
    passed = re.findall(r"\[\s*OK\s*\]\s+(\S+)", raw)
    failed = re.findall(r"\[\s*FAILED\s*\]\s+(\S+)", raw)
    # Extract failure details: everything that's not a header line
    detail_lines = [
        l for l in raw.splitlines()
        if l.strip() and not re.match(r"^\[[-= ]+\]", l)
    ]
    error_summary = "\n".join(detail_lines[:50]) if failed else "(no details)"
    return passed, failed, error_summary


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
    use_episodic_memory: bool = True,
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

    # Detect language from files present in task_dir (priority: py > js/ts > cpp > others)
    _lang_priority = [
        ("python",     ["*.py"],          ["test_task*.py", "test_*.py"]),
        ("javascript", ["*.js", "*.ts"],  ["test_task*.js", "*.test.js", "*.spec.js",
                                           "test_task*.ts", "*.test.ts", "*.spec.ts"]),
        ("cpp",        ["*.cpp", "*.cc"], ["test_*.cpp", "*_test.cpp"]),
    ]
    lang = "python"
    source_files = []
    test_files = []
    for _lang, _src_pats, _test_pats in _lang_priority:
        _src = []
        for _pat in _src_pats:
            _src += [f for f in task_dir.glob(_pat)
                     if not f.name.startswith("test_") and not f.name.startswith("__")
                     and not f.stem.startswith("fixed_")]
        if not _src:
            continue
        _tests = []
        for _pat in _test_pats:
            _tests += sorted(task_dir.glob(_pat))
            if _tests:
                break
        if _tests:
            lang = _lang
            source_files = sorted(_src)
            test_files = _tests
            break

    if not source_files:
        raise FileNotFoundError(f"No source file found in {task_dir}")
    if not test_files:
        raise FileNotFoundError(f"No test file found in {task_dir}")

    test_file = test_files[0]
    tests = test_file.read_text(encoding="utf-8")

    # Discover expected output filename from test file FIRST —
    # then derive which source file is the TARGET to fix.
    _ext_map = {"python": ".py", "javascript": ".js", "cpp": ".cpp"}
    _ext = _ext_map.get(lang, ".py")
    _ext_escaped = re.escape(_ext)
    output_name_match = re.search(rf'(\w+{_ext_escaped})\s+not found', tests)
    if not output_name_match:
        output_name_match = re.search(rf'"(\w+{_ext_escaped})".*not found', tests)
    if not output_name_match:
        # Fallback: look for any fixed_*.ext import/require in the test
        output_name_match = re.search(rf'fixed_[\w]+{_ext_escaped}', tests)
    if output_name_match:
        output_filename = output_name_match.group(0) if not output_name_match.lastindex else output_name_match.group(1)
        # Derive primary source: strip leading "fixed_" from output name
        primary_name = re.sub(r'^fixed_', '', output_filename)
        primary_candidate = task_dir / primary_name
        source_path = primary_candidate if primary_candidate in source_files else source_files[0]
    else:
        source_path = source_files[0]
        output_filename = "fixed_" + source_path.name
    output_path = task_dir / output_filename

    # Build source string — multi-file tasks get all files concatenated with labels
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

    # -- Environment probe + self-profile -------------------------------------
    env_probe    = _probe_environment()
    self_profile = _build_self_profile(task_dir.name, lang)
    _push_self_awareness_event(_consciousness, env_probe, self_profile, lang)

    # Warn early if the required runtime is missing
    lang_tool = {"python":"pytest","javascript":"jest","cpp":"g++"}.get(lang,"pytest")
    if not env_probe.get(lang_tool, {}).get("available", False):
        print(f"\n  [WARNING] Runtime '{lang_tool}' not found — tests will fail to run.")
        print(f"            Install it before proceeding.\n")

    print()
    print("=" * 68)
    print("  SHARD Benchmark Loop")
    print(f"  Task: {task_dir.name}")
    print(f"  Language: {lang.upper()}")
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

    # Inject self-profile into experience_summary so Attempt 1 sees it
    if self_profile:
        experience_summary = self_profile + ("\n" + experience_summary if experience_summary else "")
        print(f"  [self] Self-profile injected ({len(self_profile)} chars)")

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

    # -- Semantic memory query -----------------------------------------------
    try:
        from semantic_memory import query_semantic_memory
        _sem_query = f"{task_key} {source[:300]} {tests[:200]}"
        sem_context = query_semantic_memory(_sem_query, top_k=3, min_score=0.35)
        if sem_context:
            experience_summary = (experience_summary + "\n\n" if experience_summary else "") + sem_context
            print(f"  [semantic] Injected {len(sem_context)} chars of semantic memory into prompt")
    except Exception as e:
        print(f"  [semantic] Semantic memory query failed: {e}")

    # -- 2. Golden solution protection ------------------------------------
    # If a passing solution already exists, save it before the LLM overwrites it.
    # If all attempts fail, restore it — never regress a working solution.
    # NOTE: must run before the pivot check and before unlink, so we see the real file.
    _golden_code: str = ""
    _golden_passed: list = []
    if output_path.exists():
        try:
            _golden_code = output_path.read_text(encoding="utf-8")
            _all_pass, _raw = _run_tests(task_dir, test_file.name, lang=lang,
                                         source_file=str(source_path) if lang == "cpp" else None)
            if _all_pass:
                _p, _f, _ = _parse_test_output(_raw, lang=lang)
                _golden_passed = _p
                print(f"  [golden] Existing solution passes {len(_p)} test(s) — will protect on regression")
        except Exception:
            _golden_code = ""

    # -- 2b. Benchmark pivot — chronic block detection ----------------------
    # If the same task has failed N consecutive sessions, the current fixed_*.py
    # encodes a failing approach. Restore to original source (blank slate on code)
    # and measure whether SHARD produces a structurally different solution.
    # temperature=0.05 means differences cannot be attributed to sampling noise.
    # NOTE: runs before unlink so execute_pivot can read the pre-pivot code for
    # agency_score comparison. If pivot fires, the file is overwritten with original
    # source and no unlink is needed. If pivot does not fire, unlink below.
    _pivot_state: dict = {}
    try:
        from benchmark_pivot import should_pivot, execute_pivot
        from benchmark_tracker import BenchmarkTracker as _BT
        _bt = _BT.load()
        _task_id = task_dir.name
        _do_pivot, _pivot_reason = should_pivot(_task_id, _bt)
        if _do_pivot and _golden_passed:
            # Golden solution already passes all tests — no pivot needed.
            # Streak is stale; this run will register a success and reset it.
            print(f"  [pivot] Skipped — golden solution already passes {len(_golden_passed)} test(s).")
            _do_pivot = False
        if _do_pivot:
            # Capture pre-pivot failing tests from most recent episode
            _pre_fails: list = []
            try:
                _eps = load_episodes(_task_id)
                if _eps:
                    _last = _eps[-1]
                    for _att in reversed(_last.get("attempts", [])):
                        if _att.get("failed"):
                            _pre_fails = _att["failed"]
                            break
            except Exception:
                pass
            _pivot_state = execute_pivot(
                task_dir=task_dir,
                output_filename=output_filename,
                source_filename=source_path.name,
                session_id=str(task_dir),
                reason=_pivot_reason,
                pre_fails=_pre_fails,
            ) or {}
            if _pivot_state:
                # Pivot overwrote output_path with original source — reload
                try:
                    source = (task_dir / source_path.name).read_text(encoding="utf-8")
                except Exception:
                    pass
    except Exception as _piv_err:
        print(f"  [pivot] non-fatal: {_piv_err}")

    # -- Clean up stale output (only if no pivot was performed) ---------------
    # If pivot fired, execute_pivot already wrote the original source to output_path.
    # If no pivot, unlink so the loop starts fresh from a blank output file.
    if not _pivot_state:
        if output_path.exists():
            output_path.unlink()

    # -- 3. Loop -----------------------------------------------------------
    attempts = []
    _best_state = None       # AttemptRecord with highest tests_passed count seen so far
    _swarm_rollback = False  # True when last attempt regressed — triggers surgical mode next call
    _post_pivot_recorded = False  # Track if we've recorded post-pivot measurement

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
            prompt = _build_initial_prompt(source, readme, output_filename, experience_summary, lang=lang)
            print(f"  [LLM SOLO] Initial prompt ({len(prompt):,} chars)")
        elif mode == "SWARM":
            print(f"  [SWARM] Architect -> Coder -> Critic pipeline")
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
            # Run execution diagnostics on stuck tests (Python only)
            diagnostic = ""
            if stuck_tests:
                diagnostic = _run_diagnostic(task_dir, output_path, tests, stuck_tests, lang=lang)
                if diagnostic:
                    print(f"  [diag] Execution diagnostics injected for {len(stuck_tests)} stuck test(s)")
            prompt = _build_correction_prompt(
                source, tests, current_code, attempts, output_filename,
                stuck_tests=stuck_tests, lang=lang, diagnostic=diagnostic,
                task_dir=task_dir,
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
                swarm_diag = _run_diagnostic(task_dir, output_path, tests, swarm_stuck, lang=lang)
                if swarm_diag:
                        print(f"  [diag] Execution diagnostics injected for {len(swarm_stuck)} stuck test(s)")
                        # Inject into tests string so swarm_complete sees it
                        tests = tests + swarm_diag
            # Consume rollback flag — active for this one call only
            _rollback_now = _swarm_rollback
            _swarm_rollback = False
            if _rollback_now and _best_state:
                print(f"  [rollback] Modalita' chirurgica — base: tentativo {_best_state.attempt} ({len(_best_state.tests_passed)} pass)")
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
                    rollback_hint=_rollback_now,
                    rollback_code=_best_state.code if (_rollback_now and _best_state) else None,
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
                    system=_get_system_prompt(lang),
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
        code = _extract_code(response, lang=lang)

        # -- Validate syntax -------------------------------------------
        syntax_ok, syntax_err = _validate_syntax(code, lang=lang)
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

        # -- Post-pivot measurement (first write after a pivot) --------
        if _pivot_state and not _post_pivot_recorded:
            try:
                from benchmark_pivot import record_post_pivot
                _post_result = record_post_pivot(
                    pivot_state=_pivot_state,
                    post_code=code,
                    post_fails=[],  # tests not run yet — updated after pytest
                )
                print(
                    f"  [post-pivot] agency_score={_post_result['analysis']['agency_score']:.3f}"
                    f"  verdict={_post_result['analysis']['verdict']}"
                )
                _pivot_state["_post_result"] = _post_result
                _post_pivot_recorded = True
            except Exception as _pp_err:
                print(f"  [post-pivot] non-fatal: {_pp_err}")

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

        # -- Run tests -------------------------------------------------
        _runner_label = {"python": "pytest", "javascript": "jest", "cpp": "gtest"}.get(lang, "tests")
        print(f"  [{_runner_label}] Running {test_file.name}... ", end="", flush=True)
        all_passed, raw_pytest = _run_tests(task_dir, test_file.name, lang=lang,
                                            source_file=str(source_path) if lang == "cpp" else None)

        passed, failed, error_summary = _parse_test_output(raw_pytest, lang=lang)
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
            # Feed success into semantic memory
            try:
                from semantic_memory import get_semantic_memory
                get_semantic_memory().add_episode(
                    task_key=task_key, error_summary="SUCCESS",
                    code_snippet=code[:300], success=True,
                    attempt=attempt_num, lang=lang,
                )
            except Exception:
                pass
            # CognitionCore: signal mastery event
            if _consciousness:
                try:
                    _consciousness.push_event("mastery_achieved", {
                        "task": task_key, "lang": lang,
                        "attempts": attempt_num, "tests": len(passed),
                        "first_try": attempt_num == 1,
                    })
                except Exception:
                    pass
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

            # -- Feed failure into semantic memory (error pattern) ---------
            # Next attempt's correction prompt will query this and avoid the same mistake.
            if error_summary:
                try:
                    from semantic_memory import get_semantic_memory as _get_sem
                    _fix_hint = (
                        f"Task: {task_key} | Attempt {attempt_num} failed.\n"
                        f"Failing tests: {', '.join(failed[:5])}\n"
                        f"Error: {error_summary[:400]}"
                    )
                    _get_sem().add_error_pattern(
                        error_text=error_summary[:500],
                        fix=_fix_hint,
                        lang=lang,
                    )
                    # Also query for similar past fixes and inject into experience_summary
                    _sem_fix = _get_sem().query_for_prompt(
                        error_summary[:300], top_k=2, min_score=0.40,
                    )
                    if _sem_fix:
                        experience_summary = (
                            (experience_summary + "\n\n" if experience_summary else "")
                            + f"[Semantic memory — similar past errors & fixes]\n{_sem_fix}"
                        )
                except Exception:
                    pass

            # -- Early stopping / rollback ---------------------------------
            current_rec = attempts[-1]
            if _best_state is None or len(current_rec.tests_passed) >= len(_best_state.tests_passed):
                _best_state = current_rec
            elif (mode == "SWARM" and
                  len(current_rec.tests_passed) < len(_best_state.tests_passed)):
                # Regression: swarm made things worse — rollback to best state
                print(f"\n  [rollback] REGRESSIONE: tentativo {attempt_num} ha {len(current_rec.tests_passed)} pass "
                      f"< best {len(_best_state.tests_passed)} pass (tentativo {_best_state.attempt})")
                print(f"  [rollback] Scarto la patch regressiva — ripristino tentativo {_best_state.attempt}...")
                _write_file(output_path, _best_state.code)
                _swarm_rollback = True

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

    # -- Golden solution restore -------------------------------------------
    # If the LLM never beat the original passing solution, restore it.
    if _golden_code and len(_golden_passed) > best_score:
        _write_file(output_path, _golden_code)
        print(f"  [golden] LLM best={best_score} < golden={len(_golden_passed)} — restored verified solution")
    elif _golden_code and len(_golden_passed) == best_score and best_score > 0:
        # Tie — keep golden (it's verified, LLM solution is untested at full depth)
        _write_file(output_path, _golden_code)
        print(f"  [golden] Tied at {best_score} tests — kept verified solution")

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
            print(f"  [benchmark->NightRunner] Queued {added} study topic(s): {study_topics}")
    except Exception as e:
        print(f"  [benchmark->NightRunner] Could not queue topics: {e}")
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
