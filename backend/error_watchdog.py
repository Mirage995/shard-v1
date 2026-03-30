"""Error Watchdog -- scans NightRunner logs and triggers SWEAgent auto-repair.

Reads the current session log, extracts recurring Python tracebacks,
maps them to backend source files, and calls SWEAgent.repair_backend_file()
for each unique error that has appeared >= MIN_OCCURRENCES times.

Called automatically by NightRunner at the end of each session.
"""
import asyncio
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import List, NamedTuple, Optional

logger = logging.getLogger("shard.error_watchdog")

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"

# Only repair errors that appear this many times in a single session log
MIN_OCCURRENCES: int = 2

# Ignore tracebacks that originate in these directories
SKIP_PATH_FRAGMENTS = (
    "site-packages",
    "lib/python",
    "Lib\\python",
    "dist-packages",
    "__pycache__",
    ".venv",
)

# Max traceback characters sent as error_context to the LLM
MAX_CONTEXT_CHARS = 2000


# ── Data types ─────────────────────────────────────────────────────────────────

class DetectedError(NamedTuple):
    filepath: str      # absolute path to the backend file to repair
    exc_type: str      # e.g. "AttributeError"
    message: str       # e.g. "'NoneType' has no attribute 'foo'"
    context: str       # the full traceback block (truncated to MAX_CONTEXT_CHARS)
    occurrences: int   # how many times this error appeared in the log


# ── Log parsing ────────────────────────────────────────────────────────────────

def _extract_error_blocks(log_text: str) -> List[str]:
    """Split log text into individual traceback blocks.

    A block starts at "Traceback (most recent call last):" and ends
    just before the next non-indented line (or end of text).
    """
    # Each traceback block: starts with "Traceback..." and includes all
    # indented lines plus the final exception line.
    pattern = re.compile(
        r"Traceback \(most recent call last\):.*?(?=\nTraceback |\Z)",
        re.DOTALL,
    )
    return pattern.findall(log_text)


def _parse_error_block(block: str) -> Optional[tuple]:
    """Extract (filepath, exc_type, message) from a single traceback block.

    Returns None if no actionable backend file is found.
    """
    # Collect all File references in the traceback
    file_matches = re.findall(r'File "([^"]+)", line \d+', block)
    if not file_matches:
        return None

    # Walk from innermost frame outward, pick first file inside our repo
    target_file: Optional[str] = None
    for f in reversed(file_matches):
        if any(skip in f for skip in SKIP_PATH_FRAGMENTS):
            continue
        p = Path(f)
        try:
            p.resolve().relative_to(REPO_ROOT)
            if p.exists():
                target_file = str(p.resolve())
                break
        except ValueError:
            pass
        # Try interpreting as a relative path rooted at the repo
        candidate = (REPO_ROOT / f).resolve()
        if candidate.exists():
            try:
                candidate.relative_to(REPO_ROOT)
                target_file = str(candidate)
                break
            except ValueError:
                pass

    if not target_file:
        return None

    # Extract exception type and message from the last line of the block
    exc_match = re.search(
        r"^(\w+(?:\.\w+)*(?:Error|Exception|Warning)): (.*)$",
        block, re.MULTILINE,
    )
    if exc_match:
        exc_type = exc_match.group(1)
        message = exc_match.group(2).strip()[:200]
    else:
        last = block.strip().splitlines()[-1]
        exc_type = "UnknownError"
        message = last[:200]

    return target_file, exc_type, message


def scan_log(log_path: Path) -> List[DetectedError]:
    """Parse a NightRunner log file and return recurring DetectedErrors.

    Errors that appear < MIN_OCCURRENCES times are silently ignored.
    Third-party / stdlib tracebacks are skipped.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning("[WATCHDOG] Cannot read log %s: %s", log_path, e)
        return []

    blocks = _extract_error_blocks(text)
    if not blocks:
        logger.info("[WATCHDOG] No tracebacks found in %s.", log_path.name)
        return []

    logger.info("[WATCHDOG] %d traceback block(s) found in %s.", len(blocks), log_path.name)

    # Group blocks by (filepath, exc_type, message[:80]) -- deduplication key
    by_sig: dict = defaultdict(list)
    for block in blocks:
        parsed = _parse_error_block(block)
        if parsed is None:
            continue
        filepath, exc_type, message = parsed
        sig = (filepath, exc_type, message[:80])
        by_sig[sig].append(block)

    errors: List[DetectedError] = []
    for (filepath, exc_type, message), blocks_for_sig in by_sig.items():
        count = len(blocks_for_sig)
        if count < MIN_OCCURRENCES:
            logger.debug(
                "[WATCHDOG] Skipping %s in %s (%dx < %d min).",
                exc_type, Path(filepath).name, count, MIN_OCCURRENCES,
            )
            continue

        # Use the most recent occurrence as context
        context = blocks_for_sig[-1][:MAX_CONTEXT_CHARS]

        errors.append(DetectedError(
            filepath=filepath,
            exc_type=exc_type,
            message=message,
            context=context,
            occurrences=count,
        ))
        logger.info(
            "[WATCHDOG] Actionable: %s in %s (%dx) -- %s",
            exc_type, Path(filepath).name, count, message[:60],
        )

    return errors


# ── Main entrypoint ────────────────────────────────────────────────────────────

async def repair_detected_errors(log_path: Path) -> List[dict]:
    """Scan the session log and trigger SWEAgent repair for each recurring error.

    Returns a list of result dicts (one per detected error):
      {filepath, exc_type, success, commit_hash, attempts, error}
    """
    try:
        from swe_agent import SWEAgent
    except ImportError:
        from backend.swe_agent import SWEAgent

    errors = scan_log(log_path)

    if not errors:
        logger.info("[WATCHDOG] No actionable errors detected -- codebase looks clean.")
        return []

    logger.info("[WATCHDOG] %d error(s) to repair.", len(errors))

    agent = SWEAgent()
    results = []

    for err in errors:
        logger.info(
            "[WATCHDOG] ──────────────────────────────────────────────────────"
        )
        logger.info(
            "[WATCHDOG] Repairing: %s in %s (%dx)",
            err.exc_type, Path(err.filepath).name, err.occurrences,
        )

        issue = (
            f"{err.exc_type}: {err.message} "
            f"(occurred {err.occurrences}x in this NightRunner session)"
        )

        result = await agent.repair_backend_file(
            filepath=err.filepath,
            issue_text=issue,
            error_context=err.context,
            require_tests=True,
        )

        outcome = {
            "filepath": err.filepath,
            "exc_type": err.exc_type,
            "success": result.success,
            "commit_hash": result.commit_hash,
            "attempts": result.attempts,
            "error": result.error,
        }
        results.append(outcome)

        if result.success:
            logger.info(
                "[WATCHDOG] OK Auto-patched %s in %d attempt(s) -- commit %s",
                Path(err.filepath).name, result.attempts, result.commit_hash,
            )
        else:
            logger.warning(
                "[WATCHDOG] FAIL Could not repair %s after %d attempt(s): %s",
                Path(err.filepath).name, result.attempts, (result.error or "?")[:120],
            )
            logger.warning(
                "[WATCHDOG] Manual intervention required for %s.", Path(err.filepath).name
            )

    # Summary
    n_ok = sum(1 for r in results if r["success"])
    n_fail = len(results) - n_ok
    logger.info(
        "[WATCHDOG] ══ Repair summary: %d/%d patched, %d need manual review. ══",
        n_ok, len(results), n_fail,
    )

    return results
