"""Tests for graph_rag.py — causal knowledge graph extraction and query."""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Mock shard_db before importing graph_rag (it runs ensure_schema() on import)
_mock_shard_db = MagicMock()
_mock_shard_db.query.return_value = []
_mock_shard_db.execute.return_value = None
sys.modules["shard_db"] = _mock_shard_db

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from graph_rag import _parse_relations, query_causal_context, get_graph_stats, _VALID_RELATION_TYPES


class TestParseRelations(unittest.TestCase):
    """_parse_relations — pure parser, no DB."""

    def test_parses_valid_array(self):
        raw = '[{"source": "asyncio", "target": "threading", "relation_type": "causes_conflict", "confidence": 0.9, "context": "Race condition"}]'
        result = _parse_relations(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "asyncio")
        self.assertEqual(result[0]["target"], "threading")
        self.assertEqual(result[0]["relation_type"], "causes_conflict")
        self.assertAlmostEqual(result[0]["confidence"], 0.9)

    def test_strips_markdown_fences(self):
        raw = '```json\n[{"source": "a", "target": "b", "relation_type": "depends_on", "confidence": 0.8, "context": "x"}]\n```'
        result = _parse_relations(raw)
        self.assertEqual(len(result), 1)

    def test_rejects_invalid_relation_type(self):
        raw = '[{"source": "a", "target": "b", "relation_type": "INVALID", "confidence": 0.9, "context": "x"}]'
        result = _parse_relations(raw)
        self.assertEqual(result, [])

    def test_rejects_self_relation(self):
        raw = '[{"source": "a", "target": "a", "relation_type": "depends_on", "confidence": 0.9, "context": "x"}]'
        result = _parse_relations(raw)
        self.assertEqual(result, [])

    def test_lowercases_source_target(self):
        raw = '[{"source": "AsyncIO", "target": "Threading", "relation_type": "causes_conflict", "confidence": 0.7, "context": "x"}]'
        result = _parse_relations(raw)
        self.assertEqual(result[0]["source"], "asyncio")
        self.assertEqual(result[0]["target"], "threading")

    def test_empty_array(self):
        self.assertEqual(_parse_relations("[]"), [])

    def test_invalid_json_returns_empty(self):
        self.assertEqual(_parse_relations("not json"), [])
        self.assertEqual(_parse_relations(""), [])

    def test_missing_fields_skipped(self):
        # Missing target — should skip
        raw = '[{"source": "a", "relation_type": "depends_on", "confidence": 0.8, "context": "x"}]'
        result = _parse_relations(raw)
        self.assertEqual(result, [])

    def test_context_capped_at_200(self):
        long_ctx = "x" * 300
        raw = f'[{{"source": "a", "target": "b", "relation_type": "improves", "confidence": 0.8, "context": "{long_ctx}"}}]'
        result = _parse_relations(raw)
        self.assertLessEqual(len(result[0]["context"]), 200)

    def test_all_valid_relation_types_accepted(self):
        for rtype in _VALID_RELATION_TYPES:
            raw = f'[{{"source": "a", "target": "b", "relation_type": "{rtype}", "confidence": 0.8, "context": "x"}}]'
            result = _parse_relations(raw)
            self.assertEqual(len(result), 1, f"Failed for relation_type: {rtype}")

    def test_multiple_relations(self):
        raw = """[
            {"source": "a", "target": "b", "relation_type": "depends_on", "confidence": 0.8, "context": "c1"},
            {"source": "c", "target": "d", "relation_type": "breaks", "confidence": 0.6, "context": "c2"}
        ]"""
        result = _parse_relations(raw)
        self.assertEqual(len(result), 2)

    def test_default_confidence(self):
        raw = '[{"source": "a", "target": "b", "relation_type": "extends"}]'
        result = _parse_relations(raw)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["confidence"], 0.7)


def _db_mock(return_value=None, side_effect=None):
    """Return a fresh shard_db mock for use in individual tests."""
    m = MagicMock()
    if side_effect is not None:
        m.query.side_effect = side_effect
    elif return_value is not None:
        m.query.return_value = return_value
    else:
        m.query.return_value = []
    m.execute.return_value = None
    return m


class TestQueryCausalContext(unittest.TestCase):
    """query_causal_context — with mocked DB."""

    def test_returns_empty_when_no_rows(self):
        with patch.dict(sys.modules, {"shard_db": _db_mock(return_value=[])}):
            result = query_causal_context("asyncio")
        self.assertEqual(result, "")

    def test_returns_formatted_string_when_rows_match(self):
        rows = [
            {
                "source_concept": "asyncio",
                "target_concept": "threading",
                "relation_type": "causes_conflict",
                "context": "Race condition risk",
                "confidence": 0.9,
            }
        ]
        with patch.dict(sys.modules, {"shard_db": _db_mock(return_value=rows)}):
            result = query_causal_context("asyncio")
        self.assertIn("asyncio", result)
        self.assertIn("threading", result)
        self.assertIn("causes_conflict".replace("_", " "), result)

    def test_filters_low_confidence_at_query(self):
        with patch.dict(sys.modules, {"shard_db": _db_mock(return_value=[])}):
            result = query_causal_context("python")
        self.assertEqual(result, "")

    def test_returns_empty_on_no_keyword_match(self):
        rows = [
            {
                "source_concept": "golang",
                "target_concept": "rust",
                "relation_type": "replaces",
                "context": "Rust replaces Go in systems programming",
                "confidence": 0.8,
            }
        ]
        with patch.dict(sys.modules, {"shard_db": _db_mock(return_value=rows)}):
            result = query_causal_context("asyncio threading")
        self.assertEqual(result, "")

    def test_capped_at_8_results(self):
        rows = [
            {
                "source_concept": f"src{i}",
                "target_concept": f"tgt{i}",
                "relation_type": "depends_on",
                "context": f"context keyword {i}",
                "confidence": 0.8,
            }
            for i in range(15)
        ]
        with patch.dict(sys.modules, {"shard_db": _db_mock(return_value=rows)}):
            result = query_causal_context("keyword")
        lines = [l for l in result.split("\n") if l.strip().startswith(("⚡", "💥", "🚫", "🔗", "↩", "✅", "➕", "→"))]
        self.assertLessEqual(len(lines), 8)

    def test_returns_empty_on_db_exception(self):
        with patch.dict(sys.modules, {"shard_db": _db_mock(side_effect=Exception("DB error"))}):
            result = query_causal_context("asyncio")
        self.assertEqual(result, "")


class TestGetGraphStats(unittest.TestCase):
    """get_graph_stats — returns dict of counts."""

    def test_returns_total_and_by_type(self):
        type_rows = [{"relation_type": "depends_on", "cnt": 10}, {"relation_type": "breaks", "cnt": 3}]
        total_rows = [{"total": 13}]
        mock_db = _db_mock(side_effect=[type_rows, total_rows])
        with patch.dict(sys.modules, {"shard_db": mock_db}):
            stats = get_graph_stats()
        self.assertEqual(stats["total_relations"], 13)
        self.assertEqual(stats["by_type"]["depends_on"], 10)
        self.assertEqual(stats["by_type"]["breaks"], 3)

    def test_returns_zeros_on_exception(self):
        with patch.dict(sys.modules, {"shard_db": _db_mock(side_effect=Exception("DB error"))}):
            stats = get_graph_stats()
        self.assertEqual(stats["total_relations"], 0)
        self.assertEqual(stats["by_type"], {})


if __name__ == "__main__":
    unittest.main()
