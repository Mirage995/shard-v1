"""Tests for WorkspaceArbiter -- GWT Phase 1 competitive workspace selection."""
import sys
import os
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from cognition.workspace_arbiter import WorkspaceArbiter, WorkspaceProposal, ValenceField


# ── Helpers ───────────────────────────────────────────────────────────────────

def _proposal(name, content, salience, block_type, affinity=1.0):
    return WorkspaceProposal(
        module_name=name,
        content=content,
        base_salience=salience,
        topic_affinity=affinity,
        block_type=block_type,
    )


def _make_arbiter(max_tokens=500, threshold=0.4):
    # enable_feedback=True but persist_feedback=False → in-memory only, no DB writes
    return WorkspaceArbiter(max_tokens=max_tokens, ignition_threshold=threshold, enable_feedback=True, persist_feedback=False)


def _make_cognition_core(**kwargs):
    from cognition.cognition_core import CognitionCore
    return CognitionCore(**kwargs)


def _mock_self_model(cert_rate=0.5):
    m = MagicMock()
    m.get_certification_rate.return_value = cert_rate
    m.get_avg_repair_loops.return_value = 2.0
    m.self_assess_gaps.return_value = {
        "critical_gaps": ["gap_a"], "missing_skills": [],
        "gap_rate": 0.3, "total_map": 5, "missing_count": 1, "severity": "medium",
    }
    m.summarize_capabilities.return_value = {"certified": ["linked list"], "total": 1}
    m.summarize_frontier.return_value = ["python async"]
    return m


def _mock_episodic_memory(scores=None):
    if scores is None:
        scores = [5.0, 6.0]
    m = MagicMock()
    episodes = [
        {"topic": "test", "score": s, "certified": s >= 7.5,
         "failure_reason": "sandbox_zero" if s == 0 else "",
         "strategies_reused": f"strat_{i}", "timestamp": "2026-01-01T00:00:00"}
        for i, s in enumerate(scores)
    ]
    m.retrieve_context.return_value = episodes
    return m


# ── 1. ValenceField — identity suppressed when frustrated ────────────────────

def test_valence_identity_frustrated():
    assert ValenceField.mod("identity", -0.8) == 0.5


def test_valence_experience_frustrated():
    assert ValenceField.mod("experience", -0.8) == 1.3


# ── 2. ValenceField — goal and behavior_directive boosted when confident ──────

def test_valence_goal_confident():
    assert ValenceField.mod("goal", +0.8) == 1.2


def test_valence_behavior_directive_confident():
    # arousal = |+0.8| = 0.8 > 0.3 → 1.2
    assert ValenceField.mod("behavior_directive", +0.8) == 1.2


# ── 3. Arbiter selects highest-bid proposals first ────────────────────────────

def test_arbiter_selects_highest_bid_first():
    arb = _make_arbiter(threshold=0.0)
    arb.add_proposal(_proposal("low",  "low content",  0.3, "world"))
    arb.add_proposal(_proposal("high", "high content", 0.9, "goal"))
    arb.add_proposal(_proposal("mid",  "mid content",  0.6, "knowledge"))
    selected = arb.run_competition(mood_score=0.0)
    # All pass threshold=0; highest bid first in stable order is NOT the ordering,
    # but the winner should be the high-salience one.
    winner = arb.get_winner()
    assert winner is not None
    # goal with salience=0.9 × mod(goal, 0.0)=0.9 × 1.0 = 0.81 → highest bid
    assert winner.module_name == "high"


# ── 4. Arbiter respects max_tokens ────────────────────────────────────────────

def test_arbiter_respects_max_tokens():
    arb = _make_arbiter(max_tokens=10, threshold=0.0)   # 10 tokens = 40 chars
    long_content = "x" * 100  # 100 chars >> budget
    short_content = "y" * 30  # 30 chars ≤ budget
    arb.add_proposal(_proposal("long",  long_content,  0.9, "experience"))
    arb.add_proposal(_proposal("short", short_content, 0.7, "knowledge"))
    selected = arb.run_competition(mood_score=0.0)
    names = [p.module_name for p in selected]
    assert "long" not in names   # 100 chars > 40 char budget
    assert "short" in names      # 30 chars fits


# ── 5. ignition_threshold filters low bids ────────────────────────────────────

def test_ignition_threshold_filters_low_bids():
    arb = _make_arbiter(threshold=0.6)
    arb.add_proposal(_proposal("below", "content", 0.4, "world"))   # bid=0.4×1.0×1.0=0.4 < 0.6
    arb.add_proposal(_proposal("above", "content", 0.8, "goal"))    # bid=0.8×0.9×1.0=0.72 >= 0.6
    selected = arb.run_competition(mood_score=0.0)
    names = [p.module_name for p in selected]
    assert "above" in names
    assert "below" not in names


# ── 6. Fallback: when nothing passes ignition, returns 1 proposal ─────────────

def test_fallback_when_nothing_passes_ignition():
    arb = _make_arbiter(threshold=0.99)   # very high threshold — nothing passes
    arb.add_proposal(_proposal("only", "fallback content", 0.5, "knowledge"))
    selected = arb.run_competition(mood_score=0.0)
    assert len(selected) == 1
    assert selected[0].module_name == "only"


# ── 7. get_winner returns top proposal after run_competition ──────────────────

def test_get_winner_returns_highest_bid():
    arb = _make_arbiter(threshold=0.0)
    arb.add_proposal(_proposal("a", "aaa", 0.3, "world"))
    arb.add_proposal(_proposal("b", "bbb", 0.9, "experience"))
    arb.add_proposal(_proposal("c", "ccc", 0.6, "knowledge"))
    arb.run_competition(mood_score=0.0)
    winner = arb.get_winner()
    assert winner is not None
    # experience: bid = 0.9 × 1.0 (mood=0) × 1.0 = 0.9 → highest
    assert winner.module_name == "b"


def test_get_winner_returns_none_before_competition():
    arb = _make_arbiter()
    assert arb.get_winner() is None


# ── 8. Integration: resolve_workspace broadcasts workspace_winner globally ────

def test_resolve_workspace_broadcasts_globally():
    core = _make_cognition_core()

    received_events = []

    class _Listener:
        def on_event(self, event_type, data, source):
            received_events.append((event_type, data, source))

    listener = _Listener()
    # Register with NO interests — should still receive force_global events
    core.register("listener", listener, interests=[])

    core.propose_to_workspace("experience", "some experience text", 0.8, "experience")
    core.resolve_workspace("test topic", mood_score=0.0)

    event_types = [e[0] for e in received_events]
    assert "workspace_winner" in event_types

    winner_event = next(e for e in received_events if e[0] == "workspace_winner")
    assert winner_event[1]["module"] == "experience"
    assert winner_event[1]["block_type"] == "experience"
    assert "bid" in winner_event[1]


# ── 9. relational_context: frustrated mood suppresses identity, boosts experience

def test_relational_context_frustrated_mood():
    em = _mock_episodic_memory(scores=[5.0, 6.0])  # has experience
    sm = _mock_self_model(cert_rate=0.5)
    core = _make_cognition_core(self_model=sm, episodic_memory=em)

    ctx = core.relational_context("test topic", mood_score=-0.8)

    # Experience bid = 0.80 × 1.3 (experience boost) × 1.0 = 1.04 — should appear
    assert "Esperienza" in ctx

    # Identity bid = 0.70 × 0.5 (frustrated suppression) × 1.0 = 0.35 < threshold 0.4
    # Should be absent from the output
    assert "Identità: cert_rate" not in ctx


def test_relational_context_neutral_mood_includes_identity():
    sm = _mock_self_model(cert_rate=0.5)
    core = _make_cognition_core(self_model=sm)

    ctx = core.relational_context("test topic", mood_score=0.0)

    # Identity bid = 0.70 × 1.0 × 1.0 = 0.70 >= 0.4 — should appear
    assert "Identità: cert_rate" in ctx


# ── 10. Phase 3: feedback decay reduces repeat-winner bid ────────────────────

def test_feedback_decay_reduces_repeat_winner_bid():
    """Same module winning twice should have lower computed_bid on the second run."""
    arb = _make_arbiter(threshold=0.0)

    # First competition
    p1 = _proposal("module_a", "content", 0.8, "experience")
    arb.add_proposal(p1)
    winners_1 = arb.run_competition(mood_score=0.0)
    bid_after_first = arb.get_winner().computed_bid
    arb.clear()

    # Second competition — same module, same base bid
    p2 = _proposal("module_a", "content", 0.8, "experience")
    arb.add_proposal(p2)
    winners_2 = arb.run_competition(mood_score=0.0)
    bid_after_second = arb.get_winner().computed_bid

    # Decay: 0.95× after first win → second bid should be lower
    assert bid_after_second < bid_after_first


# ── Phase 4: FeedbackField persistence wired in WorkspaceArbiter ─────────────

def test_arbiter_feedback_persist_enabled():
    """WorkspaceArbiter(persist_feedback=True) must create FeedbackField with persist=True."""
    arb = WorkspaceArbiter(enable_feedback=True, persist_feedback=True)
    assert arb._feedback is not None
    assert arb._feedback._persist is True


def test_arbiter_feedback_persist_disabled():
    """WorkspaceArbiter(enable_feedback=False) must have no FeedbackField."""
    arb = WorkspaceArbiter(enable_feedback=False)
    assert arb._feedback is None
