"""Tests for FeedbackField -- GWT Phase 3 Reentrant Loop."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from cognition.feedback_field import FeedbackField


def _ff():
    return FeedbackField(decay=0.95, boost=1.05, max_multiplier=1.5)


# ── 1. Winner decay ───────────────────────────────────────────────────────────

def test_winner_decay():
    ff = _ff()
    ff.update(winners=["experience"], all_modules=["experience", "identity"])
    assert abs(ff.get_multipliers()["experience"] - 0.95) < 1e-9


# ── 2. Loser boost ────────────────────────────────────────────────────────────

def test_loser_boost():
    ff = _ff()
    ff.update(winners=["experience"], all_modules=["experience", "identity"])
    assert abs(ff.get_multipliers()["identity"] - 1.05) < 1e-9


# ── 3. Cap at max_multiplier ──────────────────────────────────────────────────

def test_cap_at_max_multiplier():
    ff = _ff()
    # identity always loses → boost 20x; should cap at 1.5
    for _ in range(20):
        ff.update(winners=["experience"], all_modules=["experience", "identity"])
    assert ff.get_multipliers()["identity"] <= 1.5
    assert abs(ff.get_multipliers()["identity"] - 1.5) < 1e-6


# ── 4. No floor: winner can go below 1.0 ─────────────────────────────────────

def test_no_floor_winner_below_one():
    ff = _ff()
    # experience always wins → 0.95^20 ≈ 0.358 — no floor
    for _ in range(20):
        ff.update(winners=["experience"], all_modules=["experience", "identity"])
    m = ff.get_multipliers()["experience"]
    assert m < 1.0
    assert m > 0.0   # still positive


# ── 5. apply() scales bid correctly ──────────────────────────────────────────

def test_apply_scales_bid():
    ff = FeedbackField()
    ff._multipliers["x"] = 1.2
    result = ff.apply("x", 10.0)
    assert abs(result - 12.0) < 1e-9


# ── 6. First-time module defaults to 1.0 ─────────────────────────────────────

def test_first_time_module_defaults_to_one():
    ff = _ff()
    result = ff.apply("never_seen", 5.0)
    assert abs(result - 5.0) < 1e-9


# ── 7. update() handles empty winners ────────────────────────────────────────

def test_update_empty_winners():
    ff = _ff()
    ff.update(winners=[], all_modules=["a", "b"])
    # all are losers → both boosted
    assert ff.get_multipliers()["a"] == pytest.approx(1.05)
    assert ff.get_multipliers()["b"] == pytest.approx(1.05)


# ── 8. reset() clears all multipliers ────────────────────────────────────────

def test_reset_clears_multipliers():
    ff = _ff()
    ff.update(winners=["a"], all_modules=["a", "b"])
    ff.reset()
    assert ff.get_multipliers() == {}
    assert ff.apply("a", 1.0) == 1.0


# ── 9. Multiple cycles: alternating winner ────────────────────────────────────

def test_alternating_winner_stays_near_one():
    ff = _ff()
    modules = ["a", "b"]
    # a and b alternate winning — multipliers should stay near 1.0 long term
    for i in range(20):
        winner = modules[i % 2]
        ff.update(winners=[winner], all_modules=modules)
    ma = ff.get_multipliers().get("a", 1.0)
    mb = ff.get_multipliers().get("b", 1.0)
    # Both should be close to 1.0 (within 0.2) — no runaway monopoly
    assert abs(ma - 1.0) < 0.2
    assert abs(mb - 1.0) < 0.2
