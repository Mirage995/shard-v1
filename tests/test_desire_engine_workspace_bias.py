"""Tests for DesireEngine.apply_workspace_bias (#53 coupling)."""
import pytest
from unittest.mock import patch, MagicMock
from backend.desire_engine import DesireEngine, DesireState


def _engine_with_topic(topic: str, curiosity_pull: float = 0.3, base_priority: float = 0.5, frustration_hits: int = 0) -> DesireEngine:
    """Return a DesireEngine with pre-seeded state (no DB/file I/O)."""
    de = DesireEngine.__new__(DesireEngine)
    ds = DesireState(
        topic=topic,
        base_priority=base_priority,
        frustration_hits=frustration_hits,
        curiosity_pull=curiosity_pull,
    )
    de._state = {topic: ds}
    de._save = MagicMock()  # suppress DB writes
    return de


def test_positive_valence_boosts_curiosity_pull():
    de = _engine_with_topic("asyncio", curiosity_pull=0.3)
    de.apply_workspace_bias("asyncio", valence_bias=0.30, arousal_bias=0.0)
    assert de._state["asyncio"].curiosity_pull == pytest.approx(0.35, abs=1e-4)
    de._save.assert_called_once()


def test_negative_valence_decays_curiosity_pull():
    de = _engine_with_topic("asyncio", curiosity_pull=0.4)
    de.apply_workspace_bias("asyncio", valence_bias=-0.30, arousal_bias=0.0)
    assert de._state["asyncio"].curiosity_pull == pytest.approx(0.4 * 0.9, abs=1e-4)
    de._save.assert_called_once()


def test_signal_below_threshold_is_noop():
    de = _engine_with_topic("asyncio", curiosity_pull=0.3, base_priority=0.5)
    de.apply_workspace_bias("asyncio", valence_bias=0.10, arousal_bias=0.15)
    assert de._state["asyncio"].curiosity_pull == pytest.approx(0.3, abs=1e-4)
    assert de._state["asyncio"].base_priority == pytest.approx(0.5, abs=1e-4)
    de._save.assert_not_called()


def test_high_arousal_boosts_base_priority_when_not_frustrated():
    de = _engine_with_topic("asyncio", base_priority=0.5, frustration_hits=0)
    de.apply_workspace_bias("asyncio", valence_bias=0.0, arousal_bias=0.30)
    assert de._state["asyncio"].base_priority == pytest.approx(0.5 * 1.05, abs=1e-4)
    de._save.assert_called_once()


def test_high_arousal_does_not_boost_priority_when_frustrated():
    de = _engine_with_topic("asyncio", base_priority=0.5, frustration_hits=2)
    de.apply_workspace_bias("asyncio", valence_bias=0.0, arousal_bias=0.30)
    assert de._state["asyncio"].base_priority == pytest.approx(0.5, abs=1e-4)
    de._save.assert_not_called()


def test_frustration_hits_never_modified():
    de = _engine_with_topic("asyncio", frustration_hits=3)
    de.apply_workspace_bias("asyncio", valence_bias=0.30, arousal_bias=0.30)
    assert de._state["asyncio"].frustration_hits == 3
