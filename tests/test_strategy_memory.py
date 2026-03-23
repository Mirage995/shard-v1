"""Tests for StrategyMemory — strategy extraction, storage, and retrieval."""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Mock chromadb before importing
sys.modules['chromadb'] = MagicMock()
sys.modules['chromadb.utils'] = MagicMock()
sys.modules['chromadb.utils.embedding_functions'] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from strategy_memory import StrategyMemory


class TestExtractStrategy(unittest.TestCase):
    """Test extract_strategy static method."""

    def test_returns_none_for_empty(self):
        self.assertIsNone(StrategyMemory.extract_strategy(None))
        self.assertIsNone(StrategyMemory.extract_strategy({}))

    def test_returns_none_no_meaningful_data(self):
        result = StrategyMemory.extract_strategy({
            "topic": "something",
            "sandbox_result": None,
            "eval_data": {},
            "structured": {},
        })
        self.assertIsNone(result)

    def test_extracts_success_strategy(self):
        experiment = {
            "topic": "Python async",
            "sandbox_result": {
                "success": True,
                "stdout": "Hello World",
                "stderr": "",
                "code": "print('Hello World')",
            },
            "eval_data": {
                "score": 8.5,
                "verdict": "PASS",
                "shard_stance": "Strong understanding",
                "gaps": [],
            },
            "structured": {
                "concepts": [{"name": "asyncio"}, {"name": "coroutines"}],
            },
        }
        result = StrategyMemory.extract_strategy(experiment)
        self.assertIsNotNone(result)
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["score"], 8.5)
        self.assertIn("asyncio", result["strategy"])
        self.assertIn("SUCCESS", result["strategy"])

    def test_extracts_failure_strategy(self):
        """score >= 5.0 FAIL is extracted; score < 5.0 FAIL is discarded by sanity filter."""
        experiment = {
            "topic": "Rust ownership",
            "sandbox_result": {
                "success": False,
                "stdout": "",
                "stderr": "NameError: undefined",
                "code": "x = y",
            },
            "eval_data": {
                "score": 5.5,   # above threshold — strategy must be extracted
                "verdict": "FAIL",
                "gaps": ["ownership basics", "borrowing rules"],
            },
            "structured": {
                "concepts": ["ownership"],
            },
        }
        result = StrategyMemory.extract_strategy(experiment)
        self.assertIsNotNone(result)
        self.assertEqual(result["outcome"], "failure")
        self.assertIn("ownership basics", result["strategy"])

    def test_low_score_fail_discarded(self):
        """score < 5.0 with verdict FAIL is filtered out by the sanity filter."""
        experiment = {
            "topic": "Rust ownership",
            "sandbox_result": None,
            "eval_data": {"score": 3.0, "verdict": "FAIL", "gaps": []},
            "structured": {"concepts": ["ownership"]},
        }
        result = StrategyMemory.extract_strategy(experiment)
        self.assertIsNone(result)

    def test_strategy_capped_at_1200(self):
        experiment = {
            "topic": "test",
            "sandbox_result": {
                "success": True,
                "stdout": "x" * 2000,
                "stderr": "",
                "code": "code",
            },
            "eval_data": {"score": 7, "verdict": "PASS", "shard_stance": "a" * 500, "gaps": ["g" * 300]},
            "structured": {"concepts": [{"name": f"concept{i}"} for i in range(10)]},
        }
        result = StrategyMemory.extract_strategy(experiment)
        self.assertIsNotNone(result)
        self.assertLessEqual(len(result["strategy"]), 1200)

    def test_extracts_from_structured_only(self):
        """Can extract strategy even without sandbox."""
        experiment = {
            "topic": "Math",
            "sandbox_result": None,
            "eval_data": {"score": 6, "verdict": "FAIL", "gaps": ["algebra"]},
            "structured": {"concepts": [{"name": "derivatives"}]},
        }
        result = StrategyMemory.extract_strategy(experiment)
        self.assertIsNotNone(result)
        self.assertIn("derivatives", result["strategy"])

    def test_handles_string_concepts(self):
        """Concepts can be plain strings, not just dicts."""
        experiment = {
            "topic": "JS",
            "sandbox_result": None,
            "eval_data": {"score": 5, "verdict": "FAIL"},
            "structured": {"concepts": ["closures", "promises"]},
        }
        result = StrategyMemory.extract_strategy(experiment)
        self.assertIsNotNone(result)
        self.assertIn("closures", result["strategy"])


if __name__ == '__main__':
    unittest.main()
