"""Tests for UncertaintyTracker — epistemic confidence over certified capabilities."""
import math
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone


def _make_db_mock(skill_rows=None, exp_rows=None):
    """Build a mock db connection returning preset skill_library and experiments rows."""
    conn = MagicMock()

    def execute_side_effect(query, params=()):
        result = MagicMock()
        q = query.strip().lower()
        if "skill_library" in q:
            result.fetchone.return_value = skill_rows
            result.fetchall.return_value = [skill_rows] if skill_rows else []
        elif "experiments" in q:
            result.fetchall.return_value = exp_rows if exp_rows is not None else []
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
        return result

    conn.execute.side_effect = execute_side_effect
    return conn


# ── Unit tests for _compute_uncertainty() ─────────────────────────────────────

class TestComputeUncertainty:
    """Test the core math without any DB."""

    def setup_method(self):
        from backend.uncertainty_tracker import _compute_uncertainty
        self.fn = _compute_uncertainty

    def test_perfect_cert_recent_gives_low_uncertainty(self):
        u = self.fn(score=9.5, attempts_before_cert=0, days_since_cert=1)
        assert u < 0.10, f"Expected < 0.10, got {u}"

    def test_low_score_many_attempts_gives_high_uncertainty(self):
        u = self.fn(score=5.0, attempts_before_cert=4, days_since_cert=90)
        assert u > 0.70, f"Expected > 0.70, got {u}"

    def test_medium_score_moderate_attempts(self):
        # score=7.0, attempts=2, days=30
        # confidence = 0.70 * (1/3) * exp(-30/90) ≈ 0.167 → uncertainty ≈ 0.833
        u = self.fn(score=7.0, attempts_before_cert=2, days_since_cert=30)
        assert 0.75 < u < 0.95, f"Expected 0.75–0.95, got {u}"

    def test_uncertainty_increases_with_age(self):
        u_fresh = self.fn(score=8.0, attempts_before_cert=1, days_since_cert=1)
        u_old   = self.fn(score=8.0, attempts_before_cert=1, days_since_cert=180)
        assert u_old > u_fresh

    def test_uncertainty_increases_with_more_attempts(self):
        u_easy = self.fn(score=7.5, attempts_before_cert=0, days_since_cert=10)
        u_hard = self.fn(score=7.5, attempts_before_cert=5, days_since_cert=10)
        assert u_hard > u_easy

    def test_uncertainty_increases_with_lower_score(self):
        u_high = self.fn(score=9.0, attempts_before_cert=1, days_since_cert=15)
        u_low  = self.fn(score=5.5, attempts_before_cert=1, days_since_cert=15)
        assert u_low > u_high

    def test_output_clamped_0_to_1(self):
        # Extreme bad case should not exceed 1.0
        u = self.fn(score=0.1, attempts_before_cert=20, days_since_cert=365)
        assert 0.0 <= u <= 1.0

    def test_output_clamped_zero_floor(self):
        # Perfect case should not go below 0.0
        u = self.fn(score=10.0, attempts_before_cert=0, days_since_cert=0)
        assert 0.0 <= u <= 1.0


# ── Integration tests for get_uncertainty() ───────────────────────────────────

class TestGetUncertainty:
    """Test full get_uncertainty() with mocked DB."""

    def _now_iso(self, days_ago=0):
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return dt.isoformat()

    def test_unknown_topic_returns_zero(self):
        import backend.uncertainty_tracker as ut
        conn = _make_db_mock(skill_rows=None, exp_rows=[])
        with patch.object(ut, "_get_db", return_value=conn):
            result = ut.get_uncertainty("nonexistent_topic_xyz")
        assert result == 0.0

    def test_high_score_recent_cert_low_uncertainty(self):
        # confidence = 0.95 * (1/1) * exp(-2/90) ≈ 0.929 → uncertainty ≈ 0.071
        import backend.uncertainty_tracker as ut
        skill_row = {"score": 9.5, "certified_at": self._now_iso(days_ago=2)}
        exp_rows  = [{"certified": 1}]  # certified first try → 0 failures
        conn = _make_db_mock(skill_rows=skill_row, exp_rows=exp_rows)
        with patch.object(ut, "_get_db", return_value=conn):
            result = ut.get_uncertainty("python asyncio")
        assert result < 0.15

    def test_low_score_old_cert_high_uncertainty(self):
        # confidence = 0.50 * (1/5) * exp(-120/90) ≈ 0.026 → uncertainty ≈ 0.974
        import backend.uncertainty_tracker as ut
        skill_row = {"score": 5.0, "certified_at": self._now_iso(days_ago=120)}
        exp_rows  = [{"certified": 0}] * 4 + [{"certified": 1}]
        conn = _make_db_mock(skill_rows=skill_row, exp_rows=exp_rows)
        with patch.object(ut, "_get_db", return_value=conn):
            result = ut.get_uncertainty("sql advanced joins")
        assert result > 0.60

    def test_result_is_float_in_range(self):
        import backend.uncertainty_tracker as ut
        skill_row = {"score": 7.5, "certified_at": self._now_iso(days_ago=30)}
        exp_rows  = [{"certified": 0}, {"certified": 0}, {"certified": 1}]
        conn = _make_db_mock(skill_rows=skill_row, exp_rows=exp_rows)
        with patch.object(ut, "_get_db", return_value=conn):
            result = ut.get_uncertainty("some topic")
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0


# ── Integration tests for get_high_uncertainty_topics() ───────────────────────

class TestGetHighUncertaintyTopics:

    def _now_iso(self, days_ago=0):
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return dt.isoformat()

    def test_returns_list(self):
        import backend.uncertainty_tracker as ut
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        with patch.object(ut, "_get_db", return_value=conn):
            result = ut.get_high_uncertainty_topics()
        assert isinstance(result, list)

    def test_high_uncertainty_topics_above_threshold(self):
        import backend.uncertainty_tracker as ut

        rows = [
            {"topic": "fragile_topic", "score": 5.0, "certified_at": self._now_iso(120)},
            {"topic": "solid_topic",   "score": 9.5, "certified_at": self._now_iso(1)},
        ]
        exp_rows_fragile = [{"certified": 0}] * 3 + [{"certified": 1}]
        exp_rows_solid   = [{"certified": 1}]

        conn = MagicMock()

        def execute_side_effect(query, params=()):
            result = MagicMock()
            q = query.strip().lower()
            if "select topic" in q and "skill_library" in q:
                result.fetchall.return_value = rows
            elif "experiments" in q and params:
                topic = params[0] if params else ""
                result.fetchall.return_value = (
                    exp_rows_fragile if topic == "fragile_topic" else exp_rows_solid
                )
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
            return result

        conn.execute.side_effect = execute_side_effect
        with patch.object(ut, "_get_db", return_value=conn):
            result = ut.get_high_uncertainty_topics(threshold=0.5, top_n=10)

        assert "fragile_topic" in result
        assert "solid_topic" not in result

    def test_respects_top_n(self):
        import backend.uncertainty_tracker as ut
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        with patch.object(ut, "_get_db", return_value=conn):
            result = ut.get_high_uncertainty_topics(top_n=3)
        assert len(result) <= 3
