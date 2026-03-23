"""Tests for MetaLearning — topic classification, stats, strategy suggestion."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import meta_learning as ml_module
from meta_learning import MetaLearning, _classify_topic, _linear_trend


def _make_test_db():
    """Create an in-memory SQLite DB with the SHARD schema for isolated tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'backend', 'schema.sql')
    with open(schema_path, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    return conn


# ── _classify_topic ────────────────────────────────────────────────────────────

class TestClassifyTopic(unittest.TestCase):

    def test_algorithms(self):
        self.assertEqual(_classify_topic("BFS and DFS graph traversal"), "algorithms")

    def test_data_structures(self):
        self.assertEqual(_classify_topic("Implementing a linked list"), "data_structures")

    def test_concurrency(self):
        self.assertEqual(_classify_topic("Python asyncio event loop internals"), "concurrency")

    def test_machine_learning(self):
        self.assertEqual(_classify_topic("Training a neural network with backpropagation"), "machine_learning")

    def test_systems(self):
        self.assertEqual(_classify_topic("Virtual memory and page tables"), "systems")

    def test_web(self):
        self.assertEqual(_classify_topic("REST API design with HTTP"), "web")

    def test_math(self):
        self.assertEqual(_classify_topic("Linear algebra: matrix multiplication"), "math")

    def test_oop(self):
        self.assertEqual(_classify_topic("Design patterns: observer and factory"), "oop")

    def test_parsing(self):
        self.assertEqual(_classify_topic("Writing a JSON parser"), "parsing")

    def test_general_fallback(self):
        self.assertEqual(_classify_topic("Something completely unrecognised xyz"), "general")

    def test_case_insensitive(self):
        self.assertEqual(_classify_topic("GRAPH ALGORITHMS"), "algorithms")


# ── _linear_trend ──────────────────────────────────────────────────────────────

class TestLinearTrend(unittest.TestCase):

    def test_single_value(self):
        self.assertEqual(_linear_trend([7.0]), 0.0)

    def test_empty(self):
        self.assertEqual(_linear_trend([]), 0.0)

    def test_flat(self):
        trend = _linear_trend([5.0, 5.0, 5.0, 5.0])
        self.assertAlmostEqual(trend, 0.0, places=2)

    def test_increasing(self):
        trend = _linear_trend([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertGreater(trend, 0.0)

    def test_decreasing(self):
        trend = _linear_trend([5.0, 4.0, 3.0, 2.0, 1.0])
        self.assertLess(trend, 0.0)


# ── MetaLearning (isolated with in-memory SQLite DB) ─────────────────────────

class TestMetaLearning(unittest.TestCase):

    def setUp(self):
        # Create an isolated in-memory DB per test
        self._test_db = _make_test_db()
        # Patch _get_db to return our test DB
        self._patcher = patch.object(ml_module, '_get_db', return_value=self._test_db)
        self._patcher.start()

        # Also redirect JSON fallback to a temp file
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._orig_path = ml_module.META_DB_PATH
        ml_module.META_DB_PATH = Path(self._tmp.name)

        self.strategy_memory = MagicMock()
        self.strategy_memory.get_all_strategies.return_value = []
        self.ml = MetaLearning(self.strategy_memory)

    def tearDown(self):
        self._patcher.stop()
        ml_module.META_DB_PATH = self._orig_path
        self._test_db.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    # ── update() ──────────────────────────────────────────────────────────────

    def test_update_increments_session_count(self):
        self.ml.update("BFS algorithm", score=8.0, certified=True)
        stats = self.ml.get_stats()
        self.assertEqual(stats["global"]["total_sessions"], 1)

    def test_update_records_score(self):
        self.ml.update("BFS algorithm", score=7.5, certified=False)
        stats = self.ml.get_stats()
        self.assertAlmostEqual(stats["global"]["avg_score"], 7.5)

    def test_update_cert_rate(self):
        self.ml.update("BFS algorithm", score=8.0, certified=True)
        self.ml.update("DFS algorithm", score=6.0, certified=False)
        stats = self.ml.get_stats()
        self.assertAlmostEqual(stats["global"]["cert_rate"], 0.5)

    def test_update_category_stats(self):
        self.ml.update("graph traversal algorithm", score=9.0, certified=True)
        stats = self.ml.get_stats()
        self.assertIn("algorithms", stats["categories"])
        self.assertEqual(stats["categories"]["algorithms"]["total"], 1)

    def test_update_persists_to_disk(self):
        self.ml.update("async coroutine", score=7.0, certified=True)
        # Create a new instance — must load from same test DB
        ml2 = MetaLearning(self.strategy_memory)
        stats = ml2.get_stats()
        self.assertEqual(stats["global"]["total_sessions"], 1)

    def test_score_history_capped_at_window(self):
        window = ml_module.HISTORY_WINDOW
        for i in range(window + 5):
            self.ml.update(f"topic {i}", score=float(i % 10), certified=True)
        # Internal score_history should never exceed window
        self.assertLessEqual(len(self.ml._data["score_history"]), window)

    def test_best_worst_category_requires_3_sessions(self):
        # 2 sessions in algorithms — not enough for best/worst
        self.ml.update("graph algorithm", score=9.0, certified=True)
        self.ml.update("sort algorithm", score=8.0, certified=True)
        gs = self.ml._data["global_stats"]
        self.assertIsNone(gs.get("best_category"))

        # Add a third session -> now it should appear
        self.ml.update("search algorithm", score=7.0, certified=True)
        gs = self.ml._data["global_stats"]
        self.assertEqual(gs.get("best_category"), "algorithms")

    def test_sandbox_result_recorded(self):
        self.ml.update(
            "neural network", score=8.0, certified=True,
            sandbox_result={"success": True}
        )
        # Check the DB directly
        row = self._test_db.execute(
            "SELECT sandbox_success FROM experiments ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(row["sandbox_success"], 1)

    def test_sandbox_none_treated_as_false(self):
        self.ml.update("neural network", score=8.0, certified=True, sandbox_result=None)
        row = self._test_db.execute(
            "SELECT sandbox_success FROM experiments ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(row["sandbox_success"], 0)

    # ── suggest_best_strategy() ───────────────────────────────────────────────

    def test_returns_none_with_no_strategies(self):
        self.strategy_memory.get_all_strategies.return_value = []
        result = self.ml.suggest_best_strategy("BFS")
        self.assertIsNone(result)

    def test_returns_none_if_all_scores_zero(self):
        self.strategy_memory.get_all_strategies.return_value = [
            {"topic": "graph", "strategy": "Do something", "avg_score": 0, "success_rate": 0}
        ]
        result = self.ml.suggest_best_strategy("BFS")
        self.assertIsNone(result)

    def test_returns_best_strategy(self):
        self.strategy_memory.get_all_strategies.return_value = [
            {"topic": "graph", "strategy": "Use adjacency list", "avg_score": 8.5, "success_rate": 0.9},
            {"topic": "graph", "strategy": "Use matrix", "avg_score": 6.0, "success_rate": 0.6},
        ]
        result = self.ml.suggest_best_strategy("BFS algorithm")
        self.assertIsNotNone(result)
        self.assertIn("adjacency list", result)

    def test_same_category_preferred(self):
        self.strategy_memory.get_all_strategies.return_value = [
            {"topic": "asyncio coroutine", "strategy": "Concurrency approach", "avg_score": 9.0, "success_rate": 1.0},
            {"topic": "graph traversal algorithm", "strategy": "Graph approach", "avg_score": 7.0, "success_rate": 0.7},
        ]
        # Topic is about algorithms — the graph strategy should be preferred
        result = self.ml.suggest_best_strategy("BFS algorithm")
        self.assertIn("Graph approach", result)

    # ── get_stats() ───────────────────────────────────────────────────────────

    def test_get_stats_shape(self):
        stats = self.ml.get_stats()
        self.assertIn("global", stats)
        self.assertIn("categories", stats)

    def test_get_stats_global_defaults(self):
        stats = self.ml.get_stats()
        self.assertEqual(stats["global"]["total_sessions"], 0)
        self.assertAlmostEqual(stats["global"]["avg_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
