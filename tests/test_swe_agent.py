"""Tests for SWEAgent — LLM-driven autonomous code repair."""
import ast
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from swe_agent import (
    MAX_REPAIR_ATTEMPTS,
    RepairResult,
    SWEAgent,
    validate_code_safety,
    validate_patch_safety,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── validate_patch_safety ──────────────────────────────────────────────────────

class TestValidatePatchSafety(unittest.TestCase):

    def test_valid_code_passes(self):
        code = "import os\n\ndef foo():\n    return 42\n"
        ok, violations = validate_patch_safety(code)
        self.assertTrue(ok)
        self.assertEqual(violations, [])

    def test_syntax_error_rejected(self):
        code = "def foo(\n    return 42\n"
        ok, violations = validate_patch_safety(code)
        self.assertFalse(ok)
        self.assertTrue(any("SyntaxError" in v for v in violations))

    def test_eval_rejected(self):
        code = "x = eval('1+1')\n"
        ok, violations = validate_patch_safety(code)
        self.assertFalse(ok)
        self.assertTrue(any("eval" in v for v in violations))

    def test_exec_rejected(self):
        code = "exec('import os')\n"
        ok, violations = validate_patch_safety(code)
        self.assertFalse(ok)
        self.assertTrue(any("exec" in v for v in violations))

    def test_import_os_allowed_in_patch(self):
        # Backend code regularly uses os — must NOT be blocked by the light gate
        code = "import os\nos.makedirs('/tmp/test', exist_ok=True)\n"
        ok, violations = validate_patch_safety(code)
        self.assertTrue(ok, f"Unexpected violations: {violations}")

    def test_compile_rejected(self):
        code = "c = compile('1+1', '<str>', 'eval')\n"
        ok, violations = validate_patch_safety(code)
        self.assertFalse(ok)
        self.assertTrue(any("compile" in v for v in violations))


# ── validate_code_safety (heavy gate) ─────────────────────────────────────────

class TestValidateCodeSafety(unittest.TestCase):

    def test_os_import_rejected(self):
        code = "import os\nprint(os.listdir('.'))\n"
        ok, violations = validate_code_safety(code)
        self.assertFalse(ok)
        self.assertTrue(any("os" in v for v in violations))

    def test_socket_import_rejected(self):
        code = "import socket\n"
        ok, violations = validate_code_safety(code)
        self.assertFalse(ok)

    def test_safe_code_passes(self):
        code = "import math\n\ndef area(r):\n    return math.pi * r ** 2\n"
        ok, violations = validate_code_safety(code)
        self.assertTrue(ok)

    def test_eval_rejected(self):
        code = "result = eval('2 + 2')\n"
        ok, violations = validate_code_safety(code)
        self.assertFalse(ok)

    def test_dunder_subclasses_rejected(self):
        code = "x = ().__class__.__bases__[0].__subclasses__()\n"
        ok, violations = validate_code_safety(code)
        self.assertFalse(ok)

    def test_getattr_eval_rejected(self):
        code = "f = getattr(builtins, 'eval')\n"
        ok, violations = validate_code_safety(code)
        self.assertFalse(ok)


# ── RepairResult dataclass ─────────────────────────────────────────────────────

class TestRepairResult(unittest.TestCase):

    def test_defaults(self):
        r = RepairResult(success=True, filepath="/some/file.py")
        self.assertTrue(r.success)
        self.assertEqual(r.patch_code, "")
        self.assertEqual(r.commit_hash, "")
        self.assertEqual(r.attempts, 0)

    def test_failure_result(self):
        r = RepairResult(success=False, filepath="/foo.py", error="LLM unavailable")
        self.assertFalse(r.success)
        self.assertIn("LLM", r.error)


# ── SWEAgent._extract_code ─────────────────────────────────────────────────────

class TestExtractCode(unittest.TestCase):

    def setUp(self):
        self.agent = SWEAgent()
        self.fallback = "# original code\n"

    def test_plain_python_returned_as_is(self):
        code = "def foo():\n    return 42\n"
        result = self.agent._extract_code(code, self.fallback)
        # _extract_code strips whitespace; trailing newline not preserved
        self.assertEqual(result.strip(), code.strip())

    def test_python_fence_stripped(self):
        raw = "```python\ndef foo():\n    return 42\n```"
        result = self.agent._extract_code(raw, self.fallback)
        self.assertEqual(result, "def foo():\n    return 42")

    def test_plain_fence_stripped(self):
        raw = "```\ndef foo():\n    return 42\n```"
        result = self.agent._extract_code(raw, self.fallback)
        self.assertEqual(result, "def foo():\n    return 42")

    def test_explanation_before_fence_stripped(self):
        raw = "Here is the fix:\n```python\nx = 1\n```"
        result = self.agent._extract_code(raw, self.fallback)
        self.assertEqual(result, "x = 1")


# ── SWEAgent._build_repair_prompt ─────────────────────────────────────────────

class TestBuildRepairPrompt(unittest.TestCase):

    def setUp(self):
        self.agent = SWEAgent()
        self.filepath = Path("backend/foo.py")
        self.code = "def bar():\n    pass\n"

    def test_contains_filename(self):
        prompt = self.agent._build_repair_prompt(
            self.filepath, self.code, "Bug in bar", "", None, 1
        )
        self.assertIn("foo.py", prompt)

    def test_contains_code(self):
        prompt = self.agent._build_repair_prompt(
            self.filepath, self.code, "Bug in bar", "", None, 1
        )
        self.assertIn("def bar():", prompt)

    def test_contains_issue(self):
        prompt = self.agent._build_repair_prompt(
            self.filepath, self.code, "Fix the null pointer", "", None, 1
        )
        self.assertIn("Fix the null pointer", prompt)

    def test_error_context_included(self):
        prompt = self.agent._build_repair_prompt(
            self.filepath, self.code, "issue", "Traceback: ...", None, 1
        )
        self.assertIn("Traceback", prompt)

    def test_previous_failure_included(self):
        prompt = self.agent._build_repair_prompt(
            self.filepath, self.code, "issue", "", "Tests failed: assertion error", 2
        )
        self.assertIn("PREVIOUS ATTEMPT", prompt)
        self.assertIn("assertion error", prompt)

    def test_no_previous_failure_on_attempt_1(self):
        prompt = self.agent._build_repair_prompt(
            self.filepath, self.code, "issue", "", None, 1
        )
        self.assertNotIn("PREVIOUS ATTEMPT", prompt)


# ── SWEAgent._discover_tests ───────────────────────────────────────────────────

class TestDiscoverTests(unittest.TestCase):

    def test_finds_existing_test_file(self):
        agent = SWEAgent()
        # capability_graph.py has tests/test_capability_graph.py
        filepath = Path(__file__).parent.parent / "backend" / "capability_graph.py"
        found = agent._discover_tests(filepath)
        self.assertTrue(len(found) > 0, "Expected to find test_capability_graph.py")

    def test_no_test_for_nonexistent_module(self):
        agent = SWEAgent()
        filepath = Path("backend/nonexistent_xyz_module.py")
        found = agent._discover_tests(filepath)
        self.assertEqual(found, [])


# ── SWEAgent.repair_backend_file (integration with mocks) ─────────────────────

class TestRepairBackendFile(unittest.TestCase):

    def _make_agent(self):
        return SWEAgent()

    def test_rejects_path_outside_repo(self):
        agent = self._make_agent()
        result = run(agent.repair_backend_file(
            filepath="/etc/passwd",
            issue_text="some issue",
        ))
        self.assertFalse(result.success)
        self.assertIn("outside the repo", result.error)

    def test_rejects_nonexistent_file(self):
        agent = self._make_agent()
        result = run(agent.repair_backend_file(
            filepath="backend/this_file_does_not_exist_xyz.py",
            issue_text="some issue",
        ))
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_successful_repair_flow(self):
        """End-to-end with LLM, git, and tests mocked out."""
        agent = self._make_agent()

        good_code = "def foo():\n    return 42\n"

        backend_dir = (Path(__file__).parent.parent / "backend").resolve()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=str(backend_dir),
            delete=False, encoding="utf-8"
        ) as tf:
            tf.write("def foo():\n    return 0  # bug\n")
            tmp_path = str(Path(tf.name).resolve())

        try:
            with (
                patch.object(agent, "_generate_patch", new=AsyncMock(return_value=good_code)),
                patch.object(agent, "_discover_tests", return_value=[]),
                patch.object(agent, "_git_commit", new=AsyncMock(return_value=(True, "abc1234"))),
            ):
                result = run(agent.repair_backend_file(
                    filepath=tmp_path,
                    issue_text="foo returns 0 instead of 42",
                    require_tests=False,
                ))

            self.assertTrue(result.success)
            self.assertEqual(result.commit_hash, "abc1234")
            self.assertEqual(result.attempts, 1)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_security_gate_blocks_eval(self):
        """If LLM returns code with eval(), the security gate must reject it."""
        agent = SWEAgent()

        evil_code = "x = eval('__import__(\"os\").system(\"id\")')\n"

        backend_dir = (Path(__file__).parent.parent / "backend").resolve()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=str(backend_dir),
            delete=False, encoding="utf-8"
        ) as tf:
            tf.write("def foo(): pass\n")
            tmp_path = str(Path(tf.name).resolve())

        try:
            with (
                patch.object(agent, "_generate_patch", new=AsyncMock(return_value=evil_code)),
                patch.object(agent, "_discover_tests", return_value=[]),
                patch.object(agent, "_git_commit", new=AsyncMock(return_value=(True, "abc"))),
                patch.object(agent, "_git_reset_file", new=AsyncMock()),
            ):
                result = run(agent.repair_backend_file(
                    filepath=tmp_path,
                    issue_text="inject eval",
                    require_tests=False,
                ))

            # All attempts should fail at security gate → overall failure
            self.assertFalse(result.success)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_retries_on_test_failure(self):
        """Agent should retry MAX times when tests keep failing."""
        agent = SWEAgent()

        good_code = "def foo():\n    return 42\n"

        backend_dir = (Path(__file__).parent.parent / "backend").resolve()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=str(backend_dir),
            delete=False, encoding="utf-8"
        ) as tf:
            tf.write("def foo(): return 0\n")
            tmp_path = str(Path(tf.name).resolve())

        try:
            with (
                patch.object(agent, "_generate_patch", new=AsyncMock(return_value=good_code)),
                patch.object(agent, "_discover_tests", return_value=["tests/fake_test.py"]),
                patch.object(agent, "_run_tests", new=AsyncMock(return_value=("FAILED: assertion", False))),
                patch.object(agent, "_git_commit", new=AsyncMock(return_value=(True, "x"))),
                patch.object(agent, "_git_reset_file", new=AsyncMock()),
            ):
                result = run(agent.repair_backend_file(
                    filepath=tmp_path,
                    issue_text="always failing test scenario",
                    require_tests=True,
                ))

            self.assertFalse(result.success)
            self.assertEqual(result.attempts, MAX_REPAIR_ATTEMPTS)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ── SWEAgent.run_task backward compat ─────────────────────────────────────────

class TestRunTaskCompat(unittest.TestCase):

    def test_run_task_returns_dict(self):
        agent = SWEAgent()
        with patch.object(
            agent, "repair_backend_file",
            new=AsyncMock(return_value=RepairResult(
                success=True, filepath="/f.py", patch_code="x=1",
                test_output="1 passed", commit_hash="abc", attempts=1,
            ))
        ):
            result = run(agent.run_task("rate_limiter", "some bug"))

        self.assertIn("patch_applied", result)
        self.assertIn("tests_passed", result)
        self.assertIn("commit_hash", result)
        self.assertTrue(result["tests_passed"])
        self.assertEqual(result["commit_hash"], "abc")


if __name__ == "__main__":
    unittest.main()
