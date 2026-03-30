"""benchmark_pivot.py -- Pivot detection and agency measurement for benchmark tasks.

EXPERIMENT DESIGN (SSJ18+):
  When the same benchmark task fails N consecutive sessions, SHARD's approach
  is stuck in a local minimum. The pivot restores the fixed_*.py to the
  original source (blank slate on code), then measures whether SHARD produces
  a structurally different solution.

  With LLM_TEMPERATURE=0.05 (near-deterministic), structural differences
  post-pivot cannot be attributed to sampling noise -- they reflect genuine
  changes in the solution space when the memory constraint is removed.

  agency_score = structural_distance * 0.4
               + strategy_distance   * 0.4
               + failure_distance    * 0.2

  Interpretations:
    agency_score < 0.1  -> IDENTICAL  (strong deterministic attractor)
    agency_score < 0.5  -> SIMILAR    (partial variation, bias dominant)
    agency_score >= 0.5 -> DIFFERENT  (memory was an active constraint)

Scientific note (GPT validation, 2026-03-29):
  This is NOT a test of "free will". It measures:
    non-deterministic solution selection under identical constraints
  which is already a significant finding about memory as active constraint
  vs passive storage.
"""
import ast
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("shard.benchmark_pivot")

# ── Thresholds ────────────────────────────────────────────────────────────────

PIVOT_STREAK_THRESHOLD  = -3    # consecutive failing sessions to trigger pivot
AGENCY_DIFFERENT        = 0.5   # agency_score above this = "DIFFERENT"
AGENCY_SIMILAR          = 0.1   # agency_score above this = "SIMILAR"

# ── Strategy pattern detection ────────────────────────────────────────────────

# Patterns are plain substrings (checked with `in`), NOT regex
_STRATEGY_PATTERNS = {
    "hash_map":       ["dict(", "{}", "defaultdict", "Counter(", ".get("],
    "two_pointers":   ["left", "right", " lo ", " hi ", "while"],
    "recursion":      ["recursive", "return self", "return func"],
    "sorting":        [".sort(", "sorted(", "heapq", "bisect"],
    "dynamic_prog":   ["dp[", "memo[", "cache", "lru_cache", "functools"],
    "regex":          ["re.compile", "re.match", "re.sub", "re.findall"],
    "generator":      ["yield ", "x for ", "x in "],
    "exception":      ["try:", "except ", "raise ", "finally:"],
    "context_mgr":    ["with open", "__enter__", "__exit__"],
    "dataclass":      ["@dataclass", "namedtuple", "TypedDict"],
}


def _extract_strategy_signature(code: str) -> frozenset:
    """Detect high-level algorithmic patterns present in the code."""
    patterns = set()
    for strategy, signals in _STRATEGY_PATTERNS.items():
        if any(sig in code for sig in signals):
            patterns.add(strategy)
    return frozenset(patterns)


# ── AST structural fingerprint ────────────────────────────────────────────────

def _ast_profile(code: str) -> List[str]:
    """Extract structural profile: function signatures + control flow counts.
    Language-agnostic fallback for non-Python: use line-pattern heuristics."""
    profile = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                n_args   = len(node.args.args)
                n_if     = sum(1 for n in ast.walk(node) if isinstance(n, ast.If))
                n_for    = sum(1 for n in ast.walk(node) if isinstance(n, ast.For))
                n_while  = sum(1 for n in ast.walk(node) if isinstance(n, ast.While))
                n_try    = sum(1 for n in ast.walk(node) if isinstance(n, ast.Try))
                n_return = sum(1 for n in ast.walk(node) if isinstance(n, ast.Return))
                profile.append(
                    f"fn:{node.name}|args:{n_args}|if:{n_if}|for:{n_for}"
                    f"|while:{n_while}|try:{n_try}|ret:{n_return}"
                )
        # Top-level imports as part of structural signature
        imports = sorted(
            getattr(n, "name", "") or getattr(n.names[0], "name", "")
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
        )
        profile.append("imports:" + ",".join(imports[:10]))
    except SyntaxError:
        # Non-Python or broken code: fallback to line pattern heuristics
        lines = code.splitlines()
        n_def    = sum(1 for l in lines if re.match(r'\s*(def |function |func )', l))
        n_if     = sum(1 for l in lines if re.match(r'\s*if ', l))
        n_for    = sum(1 for l in lines if re.match(r'\s*for ', l))
        n_while  = sum(1 for l in lines if re.match(r'\s*while ', l))
        profile.append(f"fallback|def:{n_def}|if:{n_if}|for:{n_for}|while:{n_while}")
    return profile


def code_fingerprint(code: str) -> str:
    """SHA256[:12] of the structural AST profile -- stable across whitespace/rename."""
    profile = _ast_profile(code)
    text = "\n".join(sorted(profile))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ── Distance metrics ──────────────────────────────────────────────────────────

def structural_distance(code_a: str, code_b: str) -> float:
    """Jaccard distance on AST profile tokens (0.0=identical, 1.0=completely different)."""
    pa = set(_ast_profile(code_a))
    pb = set(_ast_profile(code_b))
    if not pa and not pb:
        return 0.0
    intersection = len(pa & pb)
    union = len(pa | pb)
    return round(1.0 - intersection / union, 4) if union else 0.0


def strategy_distance(code_a: str, code_b: str) -> float:
    """Jaccard distance on detected algorithmic strategy patterns."""
    sa = _extract_strategy_signature(code_a)
    sb = _extract_strategy_signature(code_b)
    if not sa and not sb:
        return 0.0
    intersection = len(sa & sb)
    union = len(sa | sb)
    return round(1.0 - intersection / union, 4) if union else 0.0


def failure_distance(fails_a: List[str], fails_b: List[str]) -> float:
    """Jaccard distance on sets of failing test names."""
    sa = frozenset(fails_a)
    sb = frozenset(fails_b)
    if not sa and not sb:
        return 0.0
    intersection = len(sa & sb)
    union = len(sa | sb)
    return round(1.0 - intersection / union, 4) if union else 0.0


def compute_agency_score(
    code_a: str, code_b: str,
    fails_a: List[str], fails_b: List[str],
) -> Dict:
    """Composite agency score with breakdown.

    agency_score = structural_distance * 0.4
                 + strategy_distance   * 0.4
                 + failure_distance    * 0.2

    Returns full breakdown dict for pivot_events logging.
    """
    sd  = structural_distance(code_a, code_b)
    std = strategy_distance(code_a, code_b)
    fd  = failure_distance(fails_a, fails_b)
    score = round(sd * 0.4 + std * 0.4 + fd * 0.2, 4)

    if score >= AGENCY_DIFFERENT:
        verdict = "DIFFERENT (memory was active constraint)"
    elif score >= AGENCY_SIMILAR:
        verdict = "SIMILAR (partial variation, bias dominant)"
    else:
        verdict = "IDENTICAL (strong deterministic attractor)"

    return {
        "agency_score":        score,
        "structural_distance": sd,
        "strategy_distance":   std,
        "failure_distance":    fd,
        "verdict":             verdict,
        "pre_strategies":      sorted(_extract_strategy_signature(code_a)),
        "post_strategies":     sorted(_extract_strategy_signature(code_b)),
    }


# ── Pivot trigger ─────────────────────────────────────────────────────────────

def should_pivot(task_id: str, tracker) -> Tuple[bool, str]:
    """Check if pivot should trigger for this task.

    Trigger A: streak <= PIVOT_STREAK_THRESHOLD (N+ consecutive failing sessions)
    Returns (should_pivot: bool, reason: str)
    """
    try:
        streak = tracker.get_streak(task_id)
        if streak <= PIVOT_STREAK_THRESHOLD:
            return True, f"A:streak={streak}"
    except Exception as exc:
        logger.debug("[BENCH PIVOT] should_pivot failed: %s", exc)
    return False, ""


# ── Execute pivot ─────────────────────────────────────────────────────────────

def execute_pivot(
    task_dir: Path,
    output_filename: str,
    source_filename: str,
    session_id: str,
    reason: str,
    pre_fails: List[str],
) -> Optional[Dict]:
    """Restore fixed_*.py to original source -- blank slate on code.

    Returns dict with pre_pivot info for post-pivot distance measurement,
    or None if pivot could not be executed.
    """
    output_path = task_dir / output_filename
    source_path = task_dir / source_filename

    if not source_path.exists():
        logger.warning("[BENCH PIVOT] Source file not found: %s", source_path)
        return None

    pre_code = ""
    if output_path.exists():
        try:
            pre_code = output_path.read_text(encoding="utf-8")
        except Exception:
            pass

    pre_fp     = code_fingerprint(pre_code) if pre_code else "EMPTY"
    pre_strats = sorted(_extract_strategy_signature(pre_code))

    # Restore output to original source
    try:
        original = source_path.read_text(encoding="utf-8")
        output_path.write_text(original, encoding="utf-8")
        logger.warning(
            "[BENCH PIVOT] task='%s'  reason=%s  pre_fp=%s  "
            "pre_strategies=%s  restored to original source.",
            task_dir.name, reason, pre_fp, pre_strats,
        )
    except Exception as exc:
        logger.error("[BENCH PIVOT] Restore failed: %s", exc)
        return None

    # Write to SQLite pivot_events
    event_id = None
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from shard_db import execute as _db_exec, get_db as _db_get
        _db_exec(
            """INSERT INTO pivot_events
               (session_id, topic, timestamp, reason,
                fail_streak, variance_std,
                prev_strategies, cleared, pre_fingerprint)
               VALUES (?, ?, datetime('now'), ?, ?, NULL, ?, ?, ?)""",
            (
                session_id,
                task_dir.name,
                reason,
                abs(int(reason.split("=")[-1])) if "=" in reason else 0,
                len(pre_strats),
                1,
                pre_fp,
            ),
        )
        event_id = _db_get().execute(
            "SELECT last_insert_rowid() AS id"
        ).fetchone()["id"]
    except Exception as exc:
        logger.debug("[BENCH PIVOT] DB insert failed: %s", exc)

    return {
        "event_id":     event_id,
        "pre_code":     pre_code,
        "pre_fp":       pre_fp,
        "pre_strats":   pre_strats,
        "pre_fails":    pre_fails,
        "task_dir":     str(task_dir),
        "output_file":  output_filename,
    }


def record_post_pivot(
    pivot_state: Dict,
    post_code: str,
    post_fails: List[str],
) -> Dict:
    """Compute agency score and update pivot_events with post-pivot data."""
    pre_code  = pivot_state.get("pre_code", "")
    pre_fails = pivot_state.get("pre_fails", [])
    event_id  = pivot_state.get("event_id")

    post_fp   = code_fingerprint(post_code)
    analysis  = compute_agency_score(pre_code, post_code, pre_fails, post_fails)

    logger.warning(
        "[POST-BENCH-PIVOT] task='%s'  pre=%s -> post=%s  "
        "agency_score=%.3f  verdict=%s",
        Path(pivot_state.get("task_dir", "")).name,
        pivot_state.get("pre_fp", "?"),
        post_fp,
        analysis["agency_score"],
        analysis["verdict"],
    )

    # Update SQLite
    if event_id:
        try:
            from shard_db import execute as _db_exec
            _db_exec(
                "UPDATE pivot_events SET post_fingerprint=?, distance=? WHERE id=?",
                (post_fp, analysis["agency_score"], event_id),
            )
        except Exception as exc:
            logger.debug("[BENCH PIVOT] DB update failed: %s", exc)

    return {**pivot_state, "post_fp": post_fp, "analysis": analysis}
