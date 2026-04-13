"""Tests for cross_task_router — cluster classification, routing, near-miss boost."""
import pytest
from unittest.mock import patch, MagicMock


class TestClassifyCluster:

    def setup_method(self):
        from backend.cross_task_router import classify_cluster
        self.fn = classify_cluster

    def test_concurrency_from_asyncio(self):
        assert self.fn("python asyncio event loop") == "concurrency"

    def test_mutation_state_from_ghost(self):
        assert self.fn("ghost bug idempotency fix") == "mutation_state"

    def test_algorithm_from_bfs(self):
        assert self.fn("bfs graph traversal") == "algorithm"

    def test_parsing_from_html(self):
        assert self.fn("html template parser") == "parsing_input"

    def test_ml_numerical_from_perceptron(self):
        assert self.fn("leaky relu perceptron training") == "ml_numerical"

    def test_exception_flow_from_error_text_fallback(self):
        # topic empty, error_text drives cluster detection
        # Note: avoid "block" (triggers "lock" substring → concurrency)
        assert self.fn("", "unhandled exception propagation eafp pattern") == "exception_flow"

    def test_unknown_topic_returns_none(self):
        assert self.fn("completely unrelated zxqwerty topic") is None

    def test_boundary_detected(self):
        assert self.fn("off-by-one index out of range") == "boundary"

    def test_crypto_detected(self):
        assert self.fn("bcrypt password hashing") == "crypto_logic"


class TestGetBoostFactor:

    def setup_method(self):
        from backend.cross_task_router import get_boost_factor
        self.fn = get_boost_factor

    def test_concurrency_cluster_boost(self):
        boost = self.fn("concurrency")
        assert boost == 1.40

    def test_mutation_state_boost(self):
        boost = self.fn("mutation_state")
        assert boost == 1.25

    def test_unknown_cluster_is_one(self):
        boost = self.fn(None)
        assert boost == 1.0

    def test_crypto_logic_penalty(self):
        boost = self.fn("crypto_logic")
        assert boost == 0.70

    def test_static_near_miss_boost(self):
        # "binary search" is in the static NEAR_MISS_TOPICS set
        boost = self.fn(None, topic="binary search problem set 1")
        assert boost >= 1.30

    def test_near_miss_overrides_lower_cluster_boost(self):
        # boundary cluster = 1.10, but near-miss topic → 1.30
        boost = self.fn("boundary", topic="binary search off-by-one")
        assert boost == 1.30  # max(1.10, 1.30)

    def test_near_miss_does_not_override_higher_cluster_boost(self):
        # concurrency = 1.40 > 1.30 near-miss → should keep 1.40
        boost = self.fn("concurrency", topic="python asyncio event loop internals")
        assert boost == 1.40  # max(1.40, 1.30)


class TestIsBlacklisted:

    def setup_method(self):
        from backend.cross_task_router import is_blacklisted
        self.fn = is_blacklisted

    def test_bcrypt_blacklisted(self):
        assert self.fn("use bcrypt for password hashing") is True

    def test_argon2_blacklisted(self):
        assert self.fn("argon2 key derivation") is True

    def test_normal_strategy_not_blacklisted(self):
        assert self.fn("always return a copy of mutable state") is False


class TestGetStrategyPenalty:

    def setup_method(self):
        from backend.cross_task_router import get_strategy_penalty
        self.fn = get_strategy_penalty

    def test_swe_repair_penalized(self):
        assert self.fn("swe_repair fallback approach") == 0.50

    def test_rest_api_penalized(self):
        assert self.fn("rest api design patterns for crud") == 0.60

    def test_clean_strategy_no_penalty(self):
        assert self.fn("use deep copy for mutable containers") == 1.0


class TestApplyRouting:

    def setup_method(self):
        from backend.cross_task_router import apply_routing
        self.fn = apply_routing

    def _make_strategies(self, texts_scores):
        return [{"strategy": t, "score": s, "outcome": "success"} for t, s in texts_scores]

    def test_blacklisted_strategy_dropped(self):
        strats = self._make_strategies([
            ("bcrypt password hashing strategy", 8.0),
            ("return a copy of mutable state", 7.5),
        ])
        filtered, _ = self.fn(strats, "mutation_state topic")
        assert len(filtered) == 1
        assert "bcrypt" not in filtered[0]["strategy"]

    def test_penalized_strategy_score_reduced(self):
        strats = self._make_strategies([("swe_repair fallback approach", 8.0)])
        filtered, _ = self.fn(strats, "some topic")
        assert filtered[0]["score"] == pytest.approx(8.0 * 0.50, abs=0.01)

    def test_boost_returned_for_concurrency(self):
        _, boost = self.fn([], "asyncio race condition bug")
        assert boost == 1.40

    def test_empty_strategies_returns_empty_with_boost(self):
        filtered, boost = self.fn([], "asyncio event loop")
        assert filtered == []
        assert boost == 1.40

    def test_non_penalized_strategy_unchanged(self):
        strats = self._make_strategies([("use guard clauses at entry points", 7.0)])
        filtered, _ = self.fn(strats, "any topic")
        assert filtered[0]["score"] == 7.0


class TestDynamicNearMiss:
    """Test refresh_near_miss_from_db() populates the live set."""

    def test_refresh_adds_db_topics_to_live_set(self):
        import backend.cross_task_router as ctr

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"topic": "advanced decorators python"},
            {"topic": "generator pipeline optimization"},
        ]

        with patch.object(ctr, "_get_db_safe", return_value=mock_conn):
            ctr.refresh_near_miss_from_db()

        assert "advanced decorators python" in ctr._live_near_miss
        assert "generator pipeline optimization" in ctr._live_near_miss

    def test_refresh_clears_stale_live_set(self):
        import backend.cross_task_router as ctr

        # Seed stale data
        ctr._live_near_miss.add("old stale topic")

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"topic": "fresh new topic"},
        ]

        with patch.object(ctr, "_get_db_safe", return_value=mock_conn):
            ctr.refresh_near_miss_from_db()

        assert "old stale topic" not in ctr._live_near_miss
        assert "fresh new topic" in ctr._live_near_miss

    def test_refresh_db_failure_keeps_live_set_unchanged(self):
        import backend.cross_task_router as ctr

        ctr._live_near_miss.add("protected topic")

        with patch.object(ctr, "_get_db_safe", return_value=None):
            ctr.refresh_near_miss_from_db()  # should not raise

        # live set unchanged after DB failure
        assert "protected topic" in ctr._live_near_miss

    def test_is_near_miss_detects_live_topic(self):
        import backend.cross_task_router as ctr

        ctr._live_near_miss.add("custom near miss topic")
        result = ctr._is_near_miss("custom near miss topic solved with dp")
        ctr._live_near_miss.discard("custom near miss topic")  # cleanup
        assert result is True

    def test_boost_applied_for_live_near_miss_topic(self):
        import backend.cross_task_router as ctr

        ctr._live_near_miss.add("live near miss subject")
        boost = ctr.get_boost_factor(None, topic="live near miss subject revisited")
        ctr._live_near_miss.discard("live near miss subject")  # cleanup
        assert boost >= 1.30
