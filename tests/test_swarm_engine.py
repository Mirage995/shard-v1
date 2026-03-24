"""
Tests for swarm_engine.py — pure functions and swarm_complete pipeline.

Pure functions: _select_reviewers, _build_reviewer_prompt, _build_patch_prompt,
                _extract_code, _build_architect_prompt, _build_coder_prompt,
                _build_critic_prompt.
Async: swarm_complete (mocked llm_complete).
"""
import asyncio
import sys
import os
from dataclasses import dataclass
from typing import List

import pytest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from swarm_engine import (
    _select_reviewers,
    _build_reviewer_prompt,
    _build_patch_prompt,
    _extract_code,
    _build_architect_prompt,
    _build_coder_prompt,
    _build_critic_prompt,
    swarm_complete,
    ReviewerSpec,
    _REVIEWERS,
    SYSTEM_PROMPT_ARCHITECT,
    SYSTEM_PROMPT_CODER,
    SYSTEM_PROMPT_CRITIC,
)


# ── Minimal AttemptRecord stub ────────────────────────────────────────────────

@dataclass
class FakeAttempt:
    attempt: int
    syntax_valid: bool
    tests_passed: List[str]
    tests_failed: List[str]
    error_summary: str
    code: str = "def foo(): pass"


# ── ReviewerSpec ──────────────────────────────────────────────────────────────

class TestReviewerSpec:

    def test_all_reviewers_have_names(self):
        for r in _REVIEWERS:
            assert r.name and isinstance(r.name, str)

    def test_all_reviewers_have_trigger_keywords(self):
        for r in _REVIEWERS:
            assert r.trigger_keywords and len(r.trigger_keywords) > 0

    def test_reviewer_max_tokens_positive(self):
        for r in _REVIEWERS:
            assert r.max_tokens > 0

    def test_five_reviewers_defined(self):
        assert len(_REVIEWERS) == 5

    def test_known_reviewer_names(self):
        names = {r.name for r in _REVIEWERS}
        assert "Concurrency" in names
        assert "Security" in names
        assert "EdgeCases" in names
        assert "Performance" in names
        assert "DataIntegrity" in names


# ── _select_reviewers ─────────────────────────────────────────────────────────

class TestSelectReviewers:

    def test_no_match_returns_empty(self):
        result = _select_reviewers("def foo(): return 42", "assert foo() == 42")
        assert result == []

    def test_thread_keyword_activates_concurrency(self):
        result = _select_reviewers("import threading", "")
        names = [r.name for r in result]
        assert "Concurrency" in names

    def test_password_keyword_activates_security(self):
        result = _select_reviewers("password = 'secret'", "")
        names = [r.name for r in result]
        assert "Security" in names

    def test_bank_keyword_activates_data_integrity(self):
        result = _select_reviewers("", "test_bank_balance test_transfer")
        names = [r.name for r in result]
        assert "DataIntegrity" in names

    def test_none_keyword_activates_edge_cases(self):
        result = _select_reviewers("if value is None:", "")
        names = [r.name for r in result]
        assert "EdgeCases" in names

    def test_performance_keyword_activates_performance(self):
        result = _select_reviewers("# optimize for large scale", "")
        names = [r.name for r in result]
        assert "Performance" in names

    def test_multiple_keywords_activate_multiple_reviewers(self):
        result = _select_reviewers("import threading; password = 'x'", "")
        names = [r.name for r in result]
        assert "Concurrency" in names
        assert "Security" in names

    def test_case_insensitive_matching(self):
        result = _select_reviewers("THREAD.start()", "")
        names = [r.name for r in result]
        assert "Concurrency" in names


# ── _extract_code ─────────────────────────────────────────────────────────────

class TestExtractCode:

    def test_extracts_python_fenced_block(self):
        response = "```python\ndef foo():\n    return 1\n```"
        result = _extract_code(response)
        assert "def foo():" in result
        assert "```" not in result

    def test_extracts_plain_fenced_block(self):
        response = "```\ndef bar(): pass\n```"
        result = _extract_code(response)
        assert "def bar(): pass" in result

    def test_valid_python_returned_as_is(self):
        code = "def add(a, b):\n    return a + b\n"
        result = _extract_code(code)
        assert "def add" in result

    def test_strips_here_prefix_lines(self):
        response = "Here is your code:\ndef foo(): pass"
        result = _extract_code(response)
        assert "def foo(): pass" in result
        assert "Here is" not in result

    def test_strips_backtick_lines(self):
        response = "```\ndef foo(): pass\n```\nSome text"
        result = _extract_code(response)
        assert "def foo(): pass" in result

    def test_empty_response_returns_empty(self):
        result = _extract_code("")
        assert result == ""


# ── _build_critic_prompt ──────────────────────────────────────────────────────

class TestBuildCriticPrompt:

    def test_contains_code(self):
        prompt = _build_critic_prompt("def foo(): pass", "assert foo() is None", "fix.py")
        assert "def foo(): pass" in prompt

    def test_contains_tests(self):
        prompt = _build_critic_prompt("x = 1", "assert x == 1", "fix.py")
        assert "assert x == 1" in prompt

    def test_contains_filename(self):
        prompt = _build_critic_prompt("x = 1", "test", "my_module.py")
        assert "my_module.py" in prompt

    def test_asks_approved_or_issues(self):
        prompt = _build_critic_prompt("x = 1", "test", "fix.py")
        assert "APPROVED" in prompt


# ── _build_reviewer_prompt ────────────────────────────────────────────────────

class TestBuildReviewerPrompt:

    def test_contains_code(self):
        spec = _REVIEWERS[0]  # Concurrency
        prompt = _build_reviewer_prompt("import threading", "test", spec)
        assert "import threading" in prompt

    def test_contains_test_snippet(self):
        spec = _REVIEWERS[0]
        prompt = _build_reviewer_prompt("x = 1", "assert x == 1", spec)
        assert "assert x == 1" in prompt

    def test_contains_reviewer_name(self):
        spec = ReviewerSpec(name="TestReviewer", trigger_keywords=["x"],
                            system_prompt="Focus on X. If none found: respond exactly 'X: APPROVED'.")
        prompt = _build_reviewer_prompt("x=1", "test", spec)
        assert "TestReviewer" in prompt

    def test_truncates_long_tests(self):
        spec = _REVIEWERS[0]
        long_tests = "x" * 10_000
        prompt = _build_reviewer_prompt("code", long_tests, spec)
        # Tests are capped at 2000 chars in the prompt
        assert len(prompt) < 15_000


# ── _build_patch_prompt ───────────────────────────────────────────────────────

class TestBuildPatchPrompt:

    def test_contains_findings(self):
        findings = [("Security", "SQL injection on line 5")]
        prompt = _build_patch_prompt("code", "source", findings, "fix.py")
        assert "SQL injection on line 5" in prompt

    def test_contains_code(self):
        prompt = _build_patch_prompt("def foo(): pass", "src", [], "fix.py")
        assert "def foo(): pass" in prompt

    def test_contains_filename(self):
        prompt = _build_patch_prompt("x=1", "src", [], "transaction.py")
        assert "transaction.py" in prompt

    def test_multiple_findings_all_present(self):
        findings = [("Security", "Issue A"), ("Concurrency", "Issue B")]
        prompt = _build_patch_prompt("code", "src", findings, "fix.py")
        assert "Issue A" in prompt
        assert "Issue B" in prompt


# ── _build_architect_prompt ───────────────────────────────────────────────────

class TestBuildArchitectPrompt:

    def test_contains_source(self):
        attempts = [FakeAttempt(1, True, ["test_a"], ["test_b"], "AssertionError")]
        prompt = _build_architect_prompt("def original(): pass", "tests", attempts, "fix.py")
        assert "def original(): pass" in prompt

    def test_contains_history(self):
        attempts = [FakeAttempt(1, True, ["test_a"], ["test_b"], "AssertionError in test_b")]
        prompt = _build_architect_prompt("src", "tests", attempts, "fix.py")
        assert "Attempt 1" in prompt
        assert "AssertionError in test_b" in prompt

    def test_syntax_error_attempt_labeled(self):
        attempts = [FakeAttempt(1, False, [], [], "SyntaxError: invalid syntax")]
        prompt = _build_architect_prompt("src", "tests", attempts, "fix.py")
        assert "SYNTAX ERROR" in prompt

    def test_stuck_tests_highlighted(self):
        attempts = [FakeAttempt(1, True, [], ["test_idempotent"], "AssertionError")]
        prompt = _build_architect_prompt("src", "tests", attempts, "fix.py",
                                         stuck_tests=["test_idempotent"])
        assert "STUCK TESTS" in prompt
        assert "test_idempotent" in prompt

    def test_stuck_idempotent_hint_injected(self):
        attempts = [FakeAttempt(1, True, [], ["test_calibrate_idempotent"], "fail")]
        prompt = _build_architect_prompt("src", "tests", attempts, "fix.py",
                                         stuck_tests=["test_calibrate_idempotent"])
        assert "_calibrated" in prompt or "calibrat" in prompt.lower()

    def test_no_stuck_tests_no_stuck_block(self):
        attempts = [FakeAttempt(1, True, ["test_a"], [], "")]
        prompt = _build_architect_prompt("src", "tests", attempts, "fix.py")
        assert "STUCK TESTS" not in prompt


# ── _build_coder_prompt ───────────────────────────────────────────────────────

class TestBuildCoderPrompt:

    def test_contains_strategy(self):
        attempts = [FakeAttempt(1, True, ["test_a"], [], "")]
        prompt = _build_coder_prompt("src", "current_code", "Fix the off-by-one", "fix.py", attempts)
        assert "Fix the off-by-one" in prompt

    def test_contains_current_code(self):
        attempts = [FakeAttempt(1, True, [], [], "")]
        prompt = _build_coder_prompt("src", "def foo(): return 42", "strategy", "fix.py", attempts)
        assert "def foo(): return 42" in prompt

    def test_guard_block_with_passing_tests(self):
        attempts = [FakeAttempt(1, True, ["test_alpha", "test_beta"], [], "")]
        prompt = _build_coder_prompt("src", "code", "strategy", "fix.py", attempts)
        assert "test_alpha" in prompt
        assert "PRESERVE" in prompt.upper() or "passing" in prompt.lower()

    def test_no_guard_block_when_no_passing_tests(self):
        attempts = [FakeAttempt(1, True, [], ["test_fails"], "err")]
        prompt = _build_coder_prompt("src", "code", "strategy", "fix.py", attempts)
        # No passing tests = no guard block
        assert "test_fails" not in prompt or "PRESERVE" not in prompt

    def test_empty_attempts_no_crash(self):
        prompt = _build_coder_prompt("src", "code", "strategy", "fix.py", [])
        assert "strategy" in prompt


# ── swarm_complete (async, mocked llm_complete) ────────────────────────────────

class TestSwarmComplete:

    @pytest.mark.asyncio
    async def test_returns_string(self):
        attempts = [FakeAttempt(1, True, [], ["test_fail"], "err")]
        with patch("swarm_engine.llm_complete", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "def foo(): return 1"
            result = await swarm_complete("src", "tests", attempts, "fix.py")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_calls_llm_multiple_times(self):
        """Pipeline calls llm_complete at least twice (Architect + Coder)."""
        attempts = [FakeAttempt(1, True, [], ["test_fail"], "err")]
        with patch("swarm_engine.llm_complete", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "def foo(): return 1"
            await swarm_complete("src", "tests", attempts, "fix.py")
        assert mock_llm.await_count >= 2

    @pytest.mark.asyncio
    async def test_uses_last_valid_code(self):
        """Coder starts from last syntactically valid attempt, not source."""
        valid = FakeAttempt(1, True, [], [], "", code="def last_valid(): pass")
        invalid = FakeAttempt(2, False, [], [], "SyntaxError", code="broken!!!")

        captured_prompts = []

        async def capture_llm(**kwargs):
            captured_prompts.append(kwargs.get("prompt", ""))
            return "def foo(): return 1"

        with patch("swarm_engine.llm_complete", side_effect=capture_llm):
            await swarm_complete("original_src", "tests", [valid, invalid], "fix.py")

        # The coder prompt (second call) should contain the last valid code
        coder_prompt = captured_prompts[1]
        assert "def last_valid(): pass" in coder_prompt

    @pytest.mark.asyncio
    async def test_no_active_reviewers_no_extra_calls(self):
        """When no reviewer keywords match, only Architect + Coder + Critic are called."""
        attempts = [FakeAttempt(1, True, [], ["test_fail"], "err")]
        with patch("swarm_engine.llm_complete", new_callable=AsyncMock) as mock_llm:
            # No concurrency/security/etc keywords in src/tests
            mock_llm.return_value = "def foo(): return 1"
            await swarm_complete("def simple(): pass", "assert True", attempts, "fix.py")
        # Architect + Coder + Critic = 3 calls (no reviewers triggered)
        assert mock_llm.await_count == 3

    @pytest.mark.asyncio
    async def test_extracts_code_from_fenced_response(self):
        """Fenced markdown code in LLM response is stripped before returning."""
        attempts = [FakeAttempt(1, True, [], [], "")]
        with patch("swarm_engine.llm_complete", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "```python\ndef foo(): return 99\n```"
            result = await swarm_complete("src", "tests", attempts, "fix.py")
        assert "```" not in result

    @pytest.mark.asyncio
    async def test_rollback_hint_uses_rollback_code(self):
        """When rollback_hint=True, Coder receives rollback_code as base, not last_valid."""
        valid = FakeAttempt(1, True, ["test_a", "test_b"], ["test_c"], "", code="def best(): pass")
        regressed = FakeAttempt(2, True, ["test_a"], ["test_b", "test_c"], "", code="def regressed(): pass")

        captured_prompts = []

        async def capture_llm(**kwargs):
            captured_prompts.append(kwargs.get("prompt", ""))
            return "def fixed(): pass"

        with patch("swarm_engine.llm_complete", side_effect=capture_llm):
            await swarm_complete(
                "src", "tests", [valid, regressed], "fix.py",
                rollback_hint=True, rollback_code="def best(): pass",
            )

        # Coder prompt (second call) must contain rollback_code, NOT regressed code
        coder_prompt = captured_prompts[1]
        assert "def best(): pass" in coder_prompt
        assert "def regressed(): pass" not in coder_prompt

    @pytest.mark.asyncio
    async def test_rollback_hint_injects_regression_block_in_architect(self):
        """When rollback_hint=True, Architect prompt contains regression warning."""
        attempts = [FakeAttempt(1, True, [], ["test_fail"], "err")]

        captured_prompts = []

        async def capture_llm(**kwargs):
            captured_prompts.append(kwargs.get("prompt", ""))
            return "def fixed(): pass"

        with patch("swarm_engine.llm_complete", side_effect=capture_llm):
            await swarm_complete(
                "src", "tests", attempts, "fix.py",
                rollback_hint=True, rollback_code="def best(): pass",
            )

        architect_prompt = captured_prompts[0]
        assert "REGRESSIONE" in architect_prompt or "REGRESSION" in architect_prompt

    @pytest.mark.asyncio
    async def test_rollback_false_uses_last_valid_code(self):
        """When rollback_hint=False (default), Coder uses last valid attempt as base."""
        valid = FakeAttempt(1, True, [], [], "", code="def last_valid(): pass")
        captured_prompts = []

        async def capture_llm(**kwargs):
            captured_prompts.append(kwargs.get("prompt", ""))
            return "def fixed(): pass"

        with patch("swarm_engine.llm_complete", side_effect=capture_llm):
            await swarm_complete(
                "src", "tests", [valid], "fix.py",
                rollback_hint=False, rollback_code="def best(): pass",
            )

        coder_prompt = captured_prompts[1]
        assert "def last_valid(): pass" in coder_prompt


# ── _build_architect_prompt rollback ──────────────────────────────────────────

class TestBuildArchitectPromptRollback:

    def test_rollback_hint_adds_regression_block(self):
        attempts = [FakeAttempt(1, True, ["t1"], ["t2"], "err")]
        prompt = _build_architect_prompt("src", "tests", attempts, "fix.py", rollback_hint=True)
        assert "REGRESSIONE" in prompt or "REGRESSION" in prompt

    def test_rollback_hint_false_no_regression_block(self):
        attempts = [FakeAttempt(1, True, ["t1"], ["t2"], "err")]
        prompt = _build_architect_prompt("src", "tests", attempts, "fix.py", rollback_hint=False)
        assert "REGRESSIONE" not in prompt and "REGRESSION DETECTED" not in prompt

    def test_rollback_hint_contains_surgical_instructions(self):
        attempts = [FakeAttempt(1, True, ["t1"], ["t2"], "err")]
        prompt = _build_architect_prompt("src", "tests", attempts, "fix.py", rollback_hint=True)
        # Should mention minimal/surgical change
        assert any(kw in prompt.lower() for kw in ("chirurgic", "surgical", "minimal", "minimo"))


if __name__ == "__main__":
    import pytest as _pt
    _pt.main([__file__, "-v"])
