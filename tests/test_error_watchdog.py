"""Tests for ErrorWatchdog — log parsing and repair triggering."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from error_watchdog import (
    MIN_OCCURRENCES,
    DetectedError,
    _extract_error_blocks,
    _parse_error_block,
    scan_log,
    repair_detected_errors,
)
from swe_agent import RepairResult

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_FILE = str(REPO_ROOT / "backend" / "study_agent.py")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_traceback(filepath: str, exc: str = "AttributeError", msg: str = "test error") -> str:
    return (
        f"Traceback (most recent call last):\n"
        f'  File "{filepath}", line 42, in some_function\n'
        f"    result = obj.method()\n"
        f"{exc}: {msg}\n"
    )


def _make_log(tracebacks: list[str]) -> str:
    lines = []
    for i, tb in enumerate(tracebacks):
        lines.append(f"[NIGHT RUNNER] [0{i}:00] Starting cycle {i+1}")
        lines.append(tb)
        lines.append(f"[NIGHT RUNNER] [0{i}:01] Cycle {i+1} done")
    return "\n".join(lines)


# ── _extract_error_blocks ──────────────────────────────────────────────────────

class TestExtractErrorBlocks(unittest.TestCase):

    def test_no_tracebacks_returns_empty(self):
        log = "[INFO] All good\n[INFO] Session started\n"
        self.assertEqual(_extract_error_blocks(log), [])

    def test_single_traceback_extracted(self):
        tb = _make_traceback(BACKEND_FILE)
        blocks = _extract_error_blocks(tb)
        self.assertEqual(len(blocks), 1)
        self.assertIn("Traceback", blocks[0])

    def test_two_tracebacks_extracted(self):
        log = _make_log([
            _make_traceback(BACKEND_FILE, "AttributeError", "err1"),
            _make_traceback(BACKEND_FILE, "KeyError", "err2"),
        ])
        blocks = _extract_error_blocks(log)
        self.assertEqual(len(blocks), 2)

    def test_three_identical_tracebacks_all_extracted(self):
        tb = _make_traceback(BACKEND_FILE)
        log = _make_log([tb, tb, tb])
        blocks = _extract_error_blocks(log)
        self.assertEqual(len(blocks), 3)


# ── _parse_error_block ─────────────────────────────────────────────────────────

class TestParseErrorBlock(unittest.TestCase):

    def test_parses_backend_file(self):
        tb = _make_traceback(BACKEND_FILE, "AttributeError", "'NoneType' has no attribute 'read'")
        result = _parse_error_block(tb)
        self.assertIsNotNone(result)
        filepath, exc_type, message = result
        self.assertEqual(exc_type, "AttributeError")
        self.assertIn("NoneType", message)

    def test_skips_site_packages(self):
        tb = _make_traceback(
            "/usr/lib/python3/dist-packages/some_lib.py",
            "ImportError", "cannot import"
        )
        result = _parse_error_block(tb)
        self.assertIsNone(result)

    def test_returns_none_on_no_file(self):
        block = "AttributeError: something went wrong\n"
        result = _parse_error_block(block)
        self.assertIsNone(result)

    def test_extracts_innermost_backend_file(self):
        # Two files in traceback — backend file is the innermost
        block = (
            "Traceback (most recent call last):\n"
            f'  File "/usr/lib/python3/site-packages/requests/api.py", line 10\n'
            f'    do_thing()\n'
            f'  File "{BACKEND_FILE}", line 99, in study_topic\n'
            f"    result = self.cache[key]\n"
            "KeyError: 'missing_key'\n"
        )
        result = _parse_error_block(block)
        self.assertIsNotNone(result)
        filepath, exc_type, _ = result
        self.assertIn("study_agent", filepath)
        self.assertEqual(exc_type, "KeyError")


# ── scan_log ───────────────────────────────────────────────────────────────────

class TestScanLog(unittest.TestCase):

    def _write_log(self, content: str) -> Path:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        return Path(f.name)

    def tearDown(self):
        # Clean up any temp files (best-effort)
        pass

    def test_no_tracebacks_returns_empty(self):
        log = self._write_log("[INFO] All good\n")
        errors = scan_log(log)
        self.assertEqual(errors, [])
        log.unlink(missing_ok=True)

    def test_single_occurrence_not_reported(self):
        tb = _make_traceback(BACKEND_FILE)
        log = self._write_log(_make_log([tb]))
        errors = scan_log(log)
        self.assertEqual(errors, [], "Single occurrence must not trigger repair")
        log.unlink(missing_ok=True)

    def test_two_occurrences_reported(self):
        tb = _make_traceback(BACKEND_FILE, "AttributeError", "test error")
        log = self._write_log(_make_log([tb, tb]))
        errors = scan_log(log)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].occurrences, 2)
        self.assertEqual(errors[0].exc_type, "AttributeError")
        log.unlink(missing_ok=True)

    def test_three_occurrences_reported_with_count(self):
        tb = _make_traceback(BACKEND_FILE, "KeyError", "missing key")
        log = self._write_log(_make_log([tb, tb, tb]))
        errors = scan_log(log)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].occurrences, 3)
        log.unlink(missing_ok=True)

    def test_two_different_errors_both_reported(self):
        tb1 = _make_traceback(BACKEND_FILE, "AttributeError", "error one")
        tb2 = _make_traceback(BACKEND_FILE, "KeyError", "error two")
        log = self._write_log(_make_log([tb1, tb1, tb2, tb2]))
        errors = scan_log(log)
        self.assertEqual(len(errors), 2)
        exc_types = {e.exc_type for e in errors}
        self.assertIn("AttributeError", exc_types)
        self.assertIn("KeyError", exc_types)
        log.unlink(missing_ok=True)

    def test_site_packages_errors_skipped(self):
        tb = _make_traceback(
            "/usr/lib/python3/site-packages/lib.py", "ImportError", "bad import"
        )
        log = self._write_log(_make_log([tb, tb]))
        errors = scan_log(log)
        self.assertEqual(errors, [], "site-packages errors must be skipped")
        log.unlink(missing_ok=True)

    def test_nonexistent_log_returns_empty(self):
        errors = scan_log(Path("/tmp/this_log_does_not_exist_xyz.log"))
        self.assertEqual(errors, [])

    def test_context_truncated_to_max(self):
        from error_watchdog import MAX_CONTEXT_CHARS
        long_tb = _make_traceback(BACKEND_FILE) + ("x " * 2000)
        log = self._write_log(_make_log([long_tb, long_tb]))
        errors = scan_log(log)
        if errors:
            self.assertLessEqual(len(errors[0].context), MAX_CONTEXT_CHARS)
        log.unlink(missing_ok=True)


# ── repair_detected_errors ─────────────────────────────────────────────────────

class TestRepairDetectedErrors(unittest.TestCase):

    def _write_log(self, content: str) -> Path:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        return Path(f.name)

    def test_no_errors_returns_empty_list(self):
        log = self._write_log("[INFO] Clean session\n")
        results = run(repair_detected_errors(log))
        self.assertEqual(results, [])
        log.unlink(missing_ok=True)

    def test_successful_repair_recorded(self):
        tb = _make_traceback(BACKEND_FILE, "AttributeError", "fix me")
        log = self._write_log(_make_log([tb, tb]))

        fake_result = RepairResult(
            success=True, filepath=BACKEND_FILE,
            patch_code="def foo(): pass", commit_hash="abc1234", attempts=1,
        )

        with patch("swe_agent.SWEAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.repair_backend_file = AsyncMock(return_value=fake_result)
            results = run(repair_detected_errors(log))

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])
        self.assertEqual(results[0]["commit_hash"], "abc1234")
        log.unlink(missing_ok=True)

    def test_failed_repair_recorded(self):
        tb = _make_traceback(BACKEND_FILE, "KeyError", "not fixable")
        log = self._write_log(_make_log([tb, tb]))

        fake_result = RepairResult(
            success=False, filepath=BACKEND_FILE,
            error="All 3 attempts failed", attempts=3,
        )

        with patch("swe_agent.SWEAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.repair_backend_file = AsyncMock(return_value=fake_result)
            results = run(repair_detected_errors(log))

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["success"])
        self.assertIn("attempts", results[0])
        self.assertEqual(results[0]["attempts"], 3)
        log.unlink(missing_ok=True)

    def test_result_contains_required_keys(self):
        tb = _make_traceback(BACKEND_FILE, "AttributeError", "err")
        log = self._write_log(_make_log([tb, tb]))

        fake_result = RepairResult(
            success=True, filepath=BACKEND_FILE, commit_hash="xyz", attempts=1,
        )

        with patch("swe_agent.SWEAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.repair_backend_file = AsyncMock(return_value=fake_result)
            results = run(repair_detected_errors(log))

        self.assertEqual(len(results), 1)
        r = results[0]
        for key in ("filepath", "exc_type", "success", "commit_hash", "attempts", "error"):
            self.assertIn(key, r, f"Missing key: {key}")
        log.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
