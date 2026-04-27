"""Tests for GWT Phase 5: MoodWorkspaceCoupling."""
import pytest
from unittest.mock import MagicMock
from backend.cognition.mood_workspace_coupling import MoodWorkspaceCoupling


def test_known_winner_adds_positive_valence():
    mwc = MoodWorkspaceCoupling()
    mwc.on_workspace_result(winner_module="experience", ignition_failed=False)
    assert mwc.get_bias() == pytest.approx(0.10, abs=1e-6)


def test_ignition_failure_adds_negative_valence():
    mwc = MoodWorkspaceCoupling()
    mwc.on_workspace_result(winner_module=None, ignition_failed=True)
    assert mwc.get_bias() == pytest.approx(-0.15, abs=1e-6)


def test_decay_reduces_bias_over_cycles():
    mwc = MoodWorkspaceCoupling(decay=0.9)
    mwc.on_workspace_result(winner_module="experience", ignition_failed=False)
    bias_after_1 = mwc.get_bias()
    mwc.on_workspace_result(winner_module=None, ignition_failed=False)  # unknown → 0 delta
    # After 2nd call: bias_after_1 * 0.9 + 0.0
    assert mwc.get_bias() == pytest.approx(bias_after_1 * 0.9, abs=1e-6)


def test_clamp_prevents_runaway_accumulation():
    mwc = MoodWorkspaceCoupling(decay=1.0)  # no decay — pure accumulation
    for _ in range(20):
        mwc.on_workspace_result(winner_module=None, ignition_failed=True)  # -0.15 each
    assert mwc.get_bias() >= -1.0


def test_reset_clears_state():
    mwc = MoodWorkspaceCoupling()
    mwc.on_workspace_result(winner_module="goal", ignition_failed=False)
    mwc.reset()
    assert mwc.get_bias() == 0.0
    assert mwc.get_arousal_bias() == 0.0


# ── #53: last_momentum + propagate_to_desire ─────────────────────────────────

def test_last_momentum_active_on_high_arousal():
    mwc = MoodWorkspaceCoupling(decay=1.0)
    # "goal" → arousal_delta +0.15; need 2 cycles without decay to exceed 0.20
    mwc.on_workspace_result(winner_module="goal", ignition_failed=False)
    mwc.on_workspace_result(winner_module="goal", ignition_failed=False)
    assert mwc.last_momentum == "active"


def test_last_momentum_stagnating_on_low_arousal():
    mwc = MoodWorkspaceCoupling(decay=1.0)
    # "identity" → arousal_delta -0.10; need 3 cycles to exceed -0.20
    for _ in range(3):
        mwc.on_workspace_result(winner_module="identity", ignition_failed=False)
    assert mwc.last_momentum == "stagnating"


def test_last_momentum_neutral_on_small_arousal():
    mwc = MoodWorkspaceCoupling()
    mwc.on_workspace_result(winner_module="world", ignition_failed=False)  # arousal -0.05
    assert mwc.last_momentum == "neutral"


def test_propagate_to_desire_calls_apply_workspace_bias():
    mwc = MoodWorkspaceCoupling(decay=1.0)
    mwc.on_workspace_result(winner_module="experience", ignition_failed=False)
    mock_de = MagicMock()
    mwc.propagate_to_desire("asyncio", mock_de)
    mock_de.apply_workspace_bias.assert_called_once_with(
        "asyncio", mwc._valence_bias, mwc._arousal_bias
    )
