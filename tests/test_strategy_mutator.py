"""Tests for StrategyMutator — EvoScientist LLM-based strategy evolution.

LLM is always mocked so tests run offline.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from strategy_mutator import StrategyMutator


# ── helpers ──────────────────────────────────────────────────────────────────

def _strat(text: str, score: float = 5.0) -> dict:
    return {"strategy": text, "score": score, "outcome": "failure"}


def _llm_ok(text: str):
    """Returns an async LLM stub that always returns `text`."""
    async def _fn(prompt: str) -> str:
        return text
    return _fn


def _llm_raise():
    """Returns an async LLM stub that always raises."""
    async def _fn(prompt: str) -> str:
        raise RuntimeError("LLM unavailable")
    return _fn


# ── _select_top2 ─────────────────────────────────────────────────────────────

class TestSelectTop2:

    def test_picks_highest_score(self):
        strategies = [
            _strat("Strategy A", 4.0),
            _strat("Strategy B", 7.0),
            _strat("Strategy C", 6.0),
        ]
        top2 = StrategyMutator._select_top2(strategies)
        assert top2[0]["strategy"] == "Strategy B"
        assert top2[1]["strategy"] == "Strategy C"

    def test_deduplicates_identical_texts(self):
        strategies = [
            _strat("Same strategy", 7.0),
            _strat("Same strategy", 6.0),
            _strat("Different strategy", 5.0),
        ]
        top2 = StrategyMutator._select_top2(strategies)
        texts = [s["strategy"] for s in top2]
        assert texts.count("Same strategy") == 1

    def test_returns_at_most_two(self):
        strategies = [_strat(f"S{i}", float(i)) for i in range(10)]
        top2 = StrategyMutator._select_top2(strategies)
        assert len(top2) == 2

    def test_returns_empty_on_no_input(self):
        assert StrategyMutator._select_top2([]) == []

    def test_returns_one_if_only_one_unique(self):
        strategies = [_strat("Only one", 5.0)]
        top2 = StrategyMutator._select_top2(strategies)
        assert len(top2) == 1

    def test_ignores_empty_strategy_text(self):
        strategies = [
            _strat("", 9.0),        # empty — should be ignored
            _strat("Valid A", 7.0),
            _strat("Valid B", 5.0),
        ]
        top2 = StrategyMutator._select_top2(strategies)
        texts = [s["strategy"] for s in top2]
        assert "" not in texts
        assert "Valid A" in texts


# ── _clean ────────────────────────────────────────────────────────────────────

class TestClean:

    def test_strips_markdown_fences(self):
        raw = "```\nUse deep copy to avoid mutation.\n```"
        assert StrategyMutator._clean(raw) == "Use deep copy to avoid mutation."

    def test_strips_leading_number(self):
        raw = "1. Apply idempotency guard before transformation."
        assert StrategyMutator._clean(raw) == "Apply idempotency guard before transformation."

    def test_strips_leading_dash(self):
        raw = "- Ensure thread-safe access with RLock."
        assert StrategyMutator._clean(raw) == "Ensure thread-safe access with RLock."

    def test_returns_empty_on_none(self):
        assert StrategyMutator._clean(None) == ""

    def test_preserves_clean_text(self):
        raw = "Replace Lock with RLock for re-entrant locking."
        assert StrategyMutator._clean(raw) == raw


# ── _is_valid ─────────────────────────────────────────────────────────────────

class TestIsValid:

    def test_valid_strategy(self):
        assert StrategyMutator._is_valid("Use deep copy to avoid mutation side-effects.")

    def test_too_short(self):
        assert not StrategyMutator._is_valid("Use copy.")

    def test_too_long(self):
        assert not StrategyMutator._is_valid("A" * 301)

    def test_empty(self):
        assert not StrategyMutator._is_valid("")

    def test_lowercase_start_rejected(self):
        assert not StrategyMutator._is_valid("use deep copy to avoid mutation side-effects in all cases.")


# ── evolve (async) ────────────────────────────────────────────────────────────

class TestEvolve:

    @pytest.mark.asyncio
    async def test_returns_evolved_strategy_on_success(self):
        strategies = [
            _strat("Add idempotency guard before transformation.", 7.0),
            _strat("Use deep copy to avoid shared state mutation.", 6.0),
        ]
        llm = _llm_ok(
            "Combine idempotency guard with deep copy: check flag first, "
            "then operate on a copied input to prevent shared state mutation."
        )
        result = await StrategyMutator().evolve(strategies, "ghost bug fix", llm)
        assert result is not None
        assert len(result) >= 20
        assert result[0].isupper()

    @pytest.mark.asyncio
    async def test_returns_none_when_fewer_than_two_strategies(self):
        strategies = [_strat("Only one strategy here.", 7.0)]
        llm = _llm_ok("Evolved text that should not be called.")
        result = await StrategyMutator().evolve(strategies, "some topic", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_failure(self):
        strategies = [
            _strat("Strategy A for the test.", 7.0),
            _strat("Strategy B for the test.", 6.0),
        ]
        result = await StrategyMutator().evolve(strategies, "topic x", _llm_raise())
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_output_too_short(self):
        strategies = [
            _strat("Add idempotency guard before transformation.", 7.0),
            _strat("Use deep copy to avoid shared state mutation.", 6.0),
        ]
        result = await StrategyMutator().evolve(strategies, "topic x", _llm_ok("ok"))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_output_starts_lowercase(self):
        strategies = [
            _strat("Add idempotency guard before transformation.", 7.0),
            _strat("Use deep copy to avoid shared state mutation.", 6.0),
        ]
        llm = _llm_ok("apply deep copy and guard flag before processing input.")
        result = await StrategyMutator().evolve(strategies, "topic x", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_cleans_markdown_from_llm_output(self):
        strategies = [
            _strat("Add idempotency guard before transformation.", 7.0),
            _strat("Use deep copy to avoid shared state mutation.", 6.0),
        ]
        raw = "```\nEnsure the flag is checked and input is copied before any mutation occurs.\n```"
        result = await StrategyMutator().evolve(strategies, "topic x", _llm_ok(raw))
        assert result is not None
        assert "```" not in result

    @pytest.mark.asyncio
    async def test_prompt_contains_both_strategies(self):
        """Verify the LLM receives both strategies in the prompt."""
        captured = {}

        async def _capture_llm(prompt: str) -> str:
            captured["prompt"] = prompt
            return "Combine idempotency guard with a deep copy of mutable input before processing."

        strategies = [
            _strat("Use idempotency guard at entry point.", 8.0),
            _strat("Apply deep copy before mutation.", 5.0),
        ]
        await StrategyMutator().evolve(strategies, "mutation topic", _capture_llm)

        assert "Use idempotency guard at entry point." in captured["prompt"]
        assert "Apply deep copy before mutation." in captured["prompt"]
        assert "mutation topic" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_strategy_list(self):
        result = await StrategyMutator().evolve([], "any topic", _llm_ok("Anything"))
        assert result is None
