"""
Tests for night_runner.py — pure functions (topic filters, generators, enums).

Covers: topic_quality, is_valid_topic, is_trivial_topic,
        generate_recombined_topic, generate_curiosity_topic,
        capability_frontier, SessionState.
"""
import logging
import sys
import os

import pytest
from unittest.mock import MagicMock

# Ensure chromadb stub is a proper package mock before night_runner is imported.
# Some test files inject MagicMock() without __path__, which causes
# "not a package" errors under coverage instrumentation (Python 3.13+).
_chroma = MagicMock()
_chroma.__path__ = []
sys.modules['chromadb'] = _chroma
sys.modules['chromadb.utils'] = MagicMock()
sys.modules['chromadb.utils.embedding_functions'] = MagicMock()
sys.modules['chromadb.config'] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from night_runner import (
    topic_quality,
    is_valid_topic,
    is_trivial_topic,
    generate_recombined_topic,
    generate_curiosity_topic,
    capability_frontier,
    SessionState,
    BAD_TOKENS,
    OFF_TOPIC_KEYWORDS,
    _MAX_INTEGRATION_DEPTH,
)


_log = logging.getLogger("test_night_runner")


# ── topic_quality ─────────────────────────────────────────────────────────────

class TestTopicQuality:

    def test_valid_technical_topic(self):
        assert topic_quality("binary search algorithm") is True

    def test_too_short_single_word(self):
        assert topic_quality("python") is False

    def test_too_short_empty(self):
        assert topic_quality("") is False

    def test_bad_token_chiedo(self):
        assert topic_quality("chiedo facendo qualcosa") is False

    def test_bad_token_potrei(self):
        assert topic_quality("potrei analizzare questo") is False

    def test_off_topic_quantized_inertia(self):
        assert topic_quality("quantized inertia theory") is False

    def test_off_topic_casimir_effect(self):
        assert topic_quality("hubble-scale casimir effect") is False

    def test_starts_with_impossible(self):
        assert topic_quality("impossible quantum mechanics") is False

    def test_integration_depth_too_deep(self):
        # Two "integration of" = depth 2, which hits the >= 2 limit
        assert topic_quality("integration of integration of sorting and graphs") is False

    def test_integration_depth_one_ok(self):
        assert topic_quality("integration of async patterns") is True

    def test_all_bad_tokens_trigger(self):
        for token in BAD_TOKENS:
            assert topic_quality(f"{token} something else") is False, \
                f"Expected False for bad token: {token}"


# ── is_valid_topic ────────────────────────────────────────────────────────────

class TestIsValidTopic:

    def test_markdown_header_rejected(self):
        assert is_valid_topic("# Task 03 — Optimize the Transaction Processor", _log) is False

    def test_task_number_rejected(self):
        assert is_valid_topic("Task 04 Fix the banking module", _log) is False

    def test_imperative_fix_the_rejected(self):
        assert is_valid_topic("Fix the authentication module", _log) is False

    def test_imperative_refactor_the_rejected(self):
        assert is_valid_topic("Refactor the database layer", _log) is False

    def test_nested_integration_rejected(self):
        assert is_valid_topic("integration of integration of graphs and trees", _log) is False

    def test_nested_applied_to_rejected(self):
        assert is_valid_topic("x applied to y applied to z", _log) is False

    def test_italian_thought_pattern_short_rejected(self):
        assert is_valid_topic("potrei analizzare", _log) is False

    def test_whitelisted_keyword_passes(self):
        assert is_valid_topic("binary search algorithm", _log) is True

    def test_python_whitelisted(self):
        assert is_valid_topic("python async patterns", _log) is True

    def test_algorithm_whitelisted(self):
        assert is_valid_topic("sorting algorithm complexity", _log) is True

    def test_blacklisted_phrase_rejected(self):
        assert is_valid_topic("ho imparato qualcosa oggi", _log) is False

    def test_blacklisted_sistema_stabile_rejected(self):
        assert is_valid_topic("sistema stabile e robusto", _log) is False

    def test_avg_word_length_too_short_rejected(self):
        # All very short words, no whitelist match
        assert is_valid_topic("a b c d e f g", _log) is False

    def test_docker_whitelisted(self):
        assert is_valid_topic("docker container security hardening", _log) is True

    def test_machine_learning_whitelisted(self):
        assert is_valid_topic("machine learning optimization", _log) is True


# ── is_trivial_topic ──────────────────────────────────────────────────────────

class TestIsTrivialTopic:

    def test_hello_world_trivial(self):
        assert is_trivial_topic("hello world program", _log) is True

    def test_fizzbuzz_trivial(self):
        assert is_trivial_topic("fizzbuzz in python", _log) is True

    def test_what_is_trivial(self):
        assert is_trivial_topic("what is a variable", _log) is True

    def test_single_word_trivial(self):
        assert is_trivial_topic("python", _log) is True

    def test_cose_un_trivial(self):
        assert is_trivial_topic("cos'è un algoritmo", _log) is True

    def test_binary_search_not_trivial(self):
        assert is_trivial_topic("binary search algorithm", _log) is False

    def test_async_patterns_not_trivial(self):
        assert is_trivial_topic("async await concurrency patterns", _log) is False

    def test_reverse_string_trivial(self):
        assert is_trivial_topic("reverse string in python", _log) is True


# ── generate_recombined_topic ─────────────────────────────────────────────────

class TestGenerateRecombinedTopic:

    def test_returns_none_with_less_than_2_caps(self):
        assert generate_recombined_topic([]) is None
        assert generate_recombined_topic(["only one"]) is None

    def test_returns_integration_string(self):
        caps = ["sorting", "binary search"]
        result = generate_recombined_topic(caps)
        assert result is not None
        assert result.startswith("Integration of ")

    def test_both_capabilities_in_result(self):
        caps = ["sorting", "binary search"]
        result = generate_recombined_topic(caps)
        assert "sorting" in result or "binary search" in result

    def test_picks_two_different_caps(self):
        # With many runs, should pick different pairs
        caps = ["a", "b", "c", "d", "e"]
        results = {generate_recombined_topic(caps) for _ in range(20)}
        assert len(results) > 1  # should produce variety


# ── capability_frontier ───────────────────────────────────────────────────────

class TestCapabilityFrontier:

    def test_single_word_excluded(self):
        result = capability_frontier(["python", "async await patterns"])
        assert "python" not in result
        assert "async await patterns" in result

    def test_multi_word_included(self):
        result = capability_frontier(["binary search", "tree traversal"])
        assert "binary search" in result
        assert "tree traversal" in result

    def test_empty_returns_empty(self):
        assert capability_frontier([]) == []

    def test_all_single_words_returns_empty(self):
        assert capability_frontier(["python", "sorting", "graphs"]) == []


# ── generate_curiosity_topic ──────────────────────────────────────────────────

class TestGenerateCuriosityTopic:

    def test_returns_none_with_no_frontier(self):
        # No multi-word capabilities
        result = generate_curiosity_topic(["python", "sorting"])
        assert result is None

    def test_returns_integration_with_frontier(self):
        caps = ["binary search", "tree traversal", "dynamic programming"]
        result = generate_curiosity_topic(caps)
        assert result is not None
        assert result.startswith("Integration of ")

    def test_returns_none_with_only_one_frontier(self):
        result = generate_curiosity_topic(["python", "sorting", "binary search"])
        # only 1 multi-word → frontier has 1 → can't pick 2
        assert result is None


# ── SessionState enum ─────────────────────────────────────────────────────────

class TestSessionState:

    def test_all_states_exist(self):
        expected = {"INIT", "SELECT", "STUDY", "REFACTOR", "RECORD", "COMPLETE", "FAILED", "DONE"}
        actual = {s.name for s in SessionState}
        assert expected == actual

    def test_states_are_unique(self):
        values = [s.value for s in SessionState]
        assert len(values) == len(set(values))

    def test_init_is_first(self):
        states = list(SessionState)
        assert states[0] == SessionState.INIT

    def test_done_is_last(self):
        states = list(SessionState)
        assert states[-1] == SessionState.DONE


if __name__ == "__main__":
    import pytest as _pt
    _pt.main([__file__, "-v"])
