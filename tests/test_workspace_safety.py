"""Tests for workspace_safety guards."""
import pytest
from backend.cognition.workspace_safety import WorkspaceSafetyGuard, SafetyConfig


class FakeProposal:
    def __init__(self, module_name, base_salience=0.5):
        self.module_name = module_name
        self.base_salience = base_salience


class FakeCognitionCore:
    def executive(self):
        return {
            "anchor": {"certification_rate": 0.5, "last_topic": "test"},
            "summary": "Fake executive summary",
        }


# ── Ignition Guard ──────────────────────────────────────────────────────────


def test_ignition_failure_empty_workspace():
    guard = WorkspaceSafetyGuard()
    assert guard.check_ignition_failure([]) is True
    assert guard.check_ignition_failure([FakeProposal("x")]) is False


def test_fallback_context():
    guard = WorkspaceSafetyGuard()
    core = FakeCognitionCore()
    fb = guard.get_fallback_context(core)
    assert "FALLBACK" in fb
    assert "cert_rate" in fb


# ── Monopoly / Diversity Guard ──────────────────────────────────────────────


def test_no_monopoly_initially():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(max_consecutive_wins=3))
    assert guard.is_monopoly() is None


def test_monopoly_detected_after_threshold():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(max_consecutive_wins=3))
    guard.track_winner("goal", [FakeProposal("goal")])
    guard.track_winner("goal", [FakeProposal("goal")])
    assert guard.is_monopoly() is None  # 2 < 3
    guard.track_winner("goal", [FakeProposal("goal")])
    assert guard.is_monopoly() == "goal"


def test_monopoly_resets_on_winner_change():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(max_consecutive_wins=3))
    for _ in range(5):
        guard.track_winner("goal", [FakeProposal("goal")])
    assert guard.is_monopoly() == "goal"
    guard.track_winner("desire", [FakeProposal("desire")])
    assert guard.is_monopoly() is None


def test_diversity_boost():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(monopoly_boost_factor=1.5))
    proposals = [
        FakeProposal("goal", 0.5),
        FakeProposal("experience", 0.4),
        FakeProposal("identity", 0.6),
    ]
    result = guard.force_diversity_boost(proposals, monopoly_module="goal")
    assert result[0].base_salience == 0.5   # goal unchanged
    assert result[1].base_salience == 0.6   # experience boosted 0.4*1.5=0.6
    assert result[2].base_salience == 0.9   # identity boosted 0.6*1.5=0.9


def test_diversity_boost_caps_at_1_0():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(monopoly_boost_factor=2.0))
    proposals = [FakeProposal("experience", 0.8)]
    result = guard.force_diversity_boost(proposals, monopoly_module="goal")
    assert result[0].base_salience == 1.0  # capped


# ── Mood Death-Spiral Guard ─────────────────────────────────────────────────


def test_death_spiral_not_triggered_initially():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(mood_spiral_threshold=-0.7, mood_spiral_cycles=3))
    assert guard.track_mood(-0.8) is False  # only 1 sample
    assert guard.track_mood(-0.8) is False  # 2 samples


def test_death_spiral_triggered():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(mood_spiral_threshold=-0.7, mood_spiral_cycles=3))
    guard.track_mood(-0.8)
    guard.track_mood(-0.75)
    assert guard.track_mood(-0.9) is True  # 3 consecutive below -0.7


def test_death_spiral_resets_after_good_mood():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(mood_spiral_threshold=-0.7, mood_spiral_cycles=3))
    guard.track_mood(-0.8)
    guard.track_mood(-0.8)
    guard.track_mood(-0.5)  # good mood breaks streak
    assert guard.track_mood(-0.8) is False  # streak broken, need 3 more


def test_spiral_override_directives():
    guard = WorkspaceSafetyGuard()
    override = guard.get_spiral_override()
    assert override["clear_context"] is True
    assert override["force_module"] == "experience"
    assert override["suppress_module"] == "identity"


# ── Telemetry ───────────────────────────────────────────────────────────────


def test_telemetry_initial():
    guard = WorkspaceSafetyGuard()
    tel = guard.get_telemetry()
    assert tel["ignition_rate"] == 0.0
    assert tel["diversity_index"] == 0.0
    assert tel["monopoly_active"] is False
    assert tel["mood_spiral_active"] is False


def test_telemetry_after_cycles():
    guard = WorkspaceSafetyGuard(config=SafetyConfig(max_consecutive_wins=10))
    guard.track_winner("goal", [FakeProposal("goal")])
    guard.track_winner("experience", [FakeProposal("experience")])
    guard.track_winner("goal", [FakeProposal("goal")])
    tel = guard.get_telemetry()
    assert tel["ignition_rate"] == 1.0
    assert tel["diversity_index"] == pytest.approx(0.667, rel=0.01)  # 2 unique / 3 recent
    assert tel["last_5_winners"] == ["goal", "experience", "goal"]


def test_reset_clears_all():
    guard = WorkspaceSafetyGuard()
    guard.track_winner("goal", [FakeProposal("goal")])
    guard.track_mood(-0.8)
    guard.reset()
    tel = guard.get_telemetry()
    assert tel["total_cycles"] == 0
    assert tel["ignition_rate"] == 0.0
    assert guard.is_monopoly() is None
