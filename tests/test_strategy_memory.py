"""Tests for StrategyMemory — strategy extraction, storage, and retrieval."""
import sys
import os
import unittest
from datetime import datetime, timedelta
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


class TestRecencyBoost(unittest.TestCase):
    def test_recent_timestamp_near_one(self):
        ts = datetime.now().isoformat()
        boost = StrategyMemory._recency_boost(ts)
        self.assertGreater(boost, 0.99)

    def test_half_life_at_168h(self):
        ts = (datetime.now() - timedelta(hours=168)).isoformat()
        boost = StrategyMemory._recency_boost(ts)
        self.assertAlmostEqual(boost, 0.5, places=2)

    def test_invalid_timestamp_returns_default(self):
        boost = StrategyMemory._recency_boost("not-a-date")
        self.assertEqual(boost, 0.5)


class TestUtilityScoreRanking(unittest.TestCase):
    def _make_sm_with_results(self, docs, metas, distances):
        """Return a StrategyMemory whose collection.query() returns controlled data."""
        sm = StrategyMemory.__new__(StrategyMemory)
        mock_col = MagicMock()
        mock_col.count.return_value = len(docs)
        mock_col.query.return_value = {
            "documents": [docs],
            "metadatas": [metas],
            "ids": [[f"id_{i}" for i in range(len(docs))]],
            "distances": [distances],
        }
        sm.collection = mock_col
        return sm

    def test_high_success_rate_ranked_first(self):
        sm = self._make_sm_with_results(
            docs=["strategy A", "strategy B"],
            metas=[
                {"topic": "t", "outcome": "success", "score": "8.0", "success_rate": 0.9, "timestamp": datetime.now().isoformat()},
                {"topic": "t", "outcome": "success", "score": "8.0", "success_rate": 0.1, "timestamp": datetime.now().isoformat()},
            ],
            distances=[0.1, 0.1],  # same similarity
        )
        results = sm.query("test topic", k=2)
        self.assertEqual(results[0]["strategy"], "strategy A")
        self.assertGreater(results[0]["utility_score"], results[1]["utility_score"])

    def test_recent_strategy_ranked_above_old(self):
        sm = self._make_sm_with_results(
            docs=["recent", "old"],
            metas=[
                {"topic": "t", "outcome": "s", "score": "7.0", "success_rate": 0.7, "timestamp": datetime.now().isoformat()},
                {"topic": "t", "outcome": "s", "score": "7.0", "success_rate": 0.7, "timestamp": (datetime.now() - timedelta(days=30)).isoformat()},
            ],
            distances=[0.1, 0.1],
        )
        results = sm.query("test topic", k=2)
        self.assertEqual(results[0]["strategy"], "recent")

    def test_utility_score_present_in_result(self):
        sm = self._make_sm_with_results(
            docs=["strat"],
            metas=[{"topic": "t", "outcome": "s", "score": "7.0", "success_rate": 0.8, "timestamp": datetime.now().isoformat()}],
            distances=[0.2],
        )
        results = sm.query("test topic", k=1)
        self.assertIn("utility_score", results[0])
        self.assertIsInstance(results[0]["utility_score"], float)

    def test_zero_success_rate_ranked_last(self):
        sm = self._make_sm_with_results(
            docs=["good", "bad"],
            metas=[
                {"topic": "t", "outcome": "s", "score": "8.0", "success_rate": 0.8, "timestamp": datetime.now().isoformat()},
                {"topic": "t", "outcome": "f", "score": "0.0", "success_rate": 0.0, "timestamp": datetime.now().isoformat()},
            ],
            distances=[0.15, 0.15],
        )
        results = sm.query("test topic", k=2)
        self.assertEqual(results[0]["strategy"], "good")

    def test_results_capped_at_k(self):
        sm = self._make_sm_with_results(
            docs=["a", "b", "c"],
            metas=[
                {"topic": "t", "outcome": "s", "score": "7.0", "success_rate": 0.7, "timestamp": datetime.now().isoformat()},
                {"topic": "t", "outcome": "s", "score": "7.0", "success_rate": 0.7, "timestamp": datetime.now().isoformat()},
                {"topic": "t", "outcome": "s", "score": "7.0", "success_rate": 0.7, "timestamp": datetime.now().isoformat()},
            ],
            distances=[0.1, 0.2, 0.3],
        )
        results = sm.query("test topic", k=2)
        self.assertLessEqual(len(results), 2)


if __name__ == '__main__':
    unittest.main()
