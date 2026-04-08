"""Tests for suggest_curriculum_topics — concept-overlap curriculum algorithm.

All tests use an in-memory SQLite DB injected via monkeypatching so they run
offline with no dependency on shard.db.
"""
import sys
import os
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_kg_rows(*entries):
    """Build mock knowledge_graph rows as dicts.

    Each entry is a tuple:
      (topic_origin, source_concept, target_concept, relation_type)
    """
    return [
        {
            "topic_origin": to,
            "source_concept": sc,
            "target_concept": tc,
            "relation_type": rt,
        }
        for to, sc, tc, rt in entries
    ]


def _db_stub(kg_rows):
    """Return a db_query stub that returns kg_rows for any SELECT."""
    def _query(sql, params=()):
        # Step 1 query: asks for source/target concepts
        if "source_concept, target_concept" in sql and "topic_origin IN" in sql:
            certified = set(params)
            return [r for r in kg_rows if r["topic_origin"] in certified]
        # Step 2 query: asks for overlap count — simulate with Python count
        if "COUNT(*) AS overlap" in sql:
            # Extract certified exclusion list (last N params, where N == number of cert placeholders)
            # Simpler: recompute manually from kg_rows
            # params layout: concepts*2 + cert_list
            # We just re-run the overlap logic directly
            concept_params_end = len(params) - len([p for p in params if p in {r["topic_origin"] for r in kg_rows}])
            # Fallback: return all rows with a synthetic overlap count
            from collections import Counter
            cert_set = set(params[len(params)//2 + len(params)%2:]) if len(params) > 2 else set()
            overlap: Counter = Counter()
            for r in kg_rows:
                if r["topic_origin"] and r["topic_origin"] not in cert_set:
                    if r["source_concept"] in params or r["target_concept"] in params:
                        overlap[r["topic_origin"]] += 1
            return [{"topic_origin": t, "overlap": c} for t, c in overlap.most_common(40)]
        return []
    return _query


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def simple_kg():
    """Minimal KG: two certified topics share concept 'recursion'.
    Two uncertified topics also use 'recursion' → should appear in curriculum.
    """
    return _make_kg_rows(
        # Certified
        ("binary search",          "recursion",        "base case",       "requires"),
        ("binary search",          "sorted array",     "index",           "requires"),
        ("dynamic programming",    "recursion",        "memoization",     "improves"),
        # Not certified — overlap with 'recursion'
        ("tree traversal",         "recursion",        "tree node",       "requires"),
        ("merge sort",             "recursion",        "divide conquer",  "requires"),
        # Not certified — no overlap with certified concepts
        ("unrelated topic",        "quantum",          "qubit",           "extends"),
    )


# ── unit tests ────────────────────────────────────────────────────────────────

class TestSuggestCurriculumTopics:

    def _call(self, certified, pool, kg_rows, top_n=5):
        from skill_library import suggest_curriculum_topics
        stub = _db_stub(kg_rows)
        with patch("skill_library.db_query", stub, create=True):
            # Also patch the import inside suggest_curriculum_topics
            import skill_library as sl
            orig = getattr(sl, "_shard_db_query", None)
            with patch.object(sl, "suggest_curriculum_topics",
                              wraps=sl.suggest_curriculum_topics):
                # Patch shard_db.query used inside the function
                import importlib, types
                fake_mod = types.ModuleType("shard_db")
                fake_mod.query = stub
                with patch.dict(sys.modules, {"shard_db": fake_mod}):
                    return sl.suggest_curriculum_topics(certified, pool, top_n)

    def test_returns_empty_for_no_certified_topics(self):
        from skill_library import suggest_curriculum_topics
        import types
        fake_mod = types.ModuleType("shard_db")
        fake_mod.query = lambda *a, **k: []
        with patch.dict(sys.modules, {"shard_db": fake_mod}):
            result = suggest_curriculum_topics(set(), ["any topic"], top_n=5)
        assert result == []

    def test_returns_empty_when_kg_has_no_certified_concepts(self):
        # KG rows only for non-certified topics → step 1 returns nothing
        kg_rows = _make_kg_rows(
            ("uncertified topic", "some concept", "other", "requires"),
        )
        result = self._call({"certified topic"}, [], kg_rows)
        assert result == []

    def test_finds_topics_with_concept_overlap(self, simple_kg):
        certified = {"binary search", "dynamic programming"}
        result = self._call(certified, [], simple_kg)
        # 'tree traversal' and 'merge sort' share 'recursion' with certified topics
        assert "tree traversal" in result
        assert "merge sort" in result

    def test_unrelated_topic_excluded(self, simple_kg):
        certified = {"binary search", "dynamic programming"}
        result = self._call(certified, [], simple_kg)
        assert "unrelated topic" not in result

    def test_certified_topics_excluded_from_result(self, simple_kg):
        certified = {"binary search", "dynamic programming"}
        result = self._call(certified, [], simple_kg)
        assert "binary search" not in result
        assert "dynamic programming" not in result

    def test_respects_top_n(self, simple_kg):
        certified = {"binary search", "dynamic programming"}
        result = self._call(certified, [], simple_kg, top_n=1)
        assert len(result) <= 1

    def test_prefers_curated_pool_topics(self, simple_kg):
        certified = {"binary search", "dynamic programming"}
        # Only 'merge sort' is in the pool
        pool = ["merge sort", "other random topic"]
        result = self._call(certified, pool, simple_kg, top_n=3)
        # 'merge sort' should appear before 'tree traversal' since it's in pool
        if "merge sort" in result and "tree traversal" in result:
            assert result.index("merge sort") < result.index("tree traversal")

    def test_higher_overlap_ranked_first(self):
        # 'advanced recursion' overlaps on 3 concepts, 'basic loops' only on 1
        kg_rows = _make_kg_rows(
            # Certified
            ("binary search", "recursion",  "base case",    "requires"),
            ("binary search", "indexing",   "pointer",      "requires"),
            ("binary search", "comparison", "equality",     "requires"),
            # Not certified — 3 overlapping concepts
            ("advanced recursion", "recursion",  "tail call",    "extends"),
            ("advanced recursion", "indexing",   "array",        "requires"),
            ("advanced recursion", "comparison", "ordering",     "requires"),
            # Not certified — 1 overlapping concept
            ("basic loops",        "recursion",  "iteration",    "extends"),
        )
        result = self._call({"binary search"}, [], kg_rows, top_n=2)
        assert len(result) >= 1
        # advanced recursion has more overlap → should rank higher
        if "advanced recursion" in result and "basic loops" in result:
            assert result.index("advanced recursion") < result.index("basic loops")

    def test_returns_empty_on_db_error(self):
        from skill_library import suggest_curriculum_topics
        import types
        fake_mod = types.ModuleType("shard_db")
        fake_mod.query = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        with patch.dict(sys.modules, {"shard_db": fake_mod}):
            result = suggest_curriculum_topics({"some topic"}, [], top_n=5)
        assert result == []
