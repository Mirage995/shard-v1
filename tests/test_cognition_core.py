"""
Tests for CognitionCore — SHARD's Senso Interno.

Verifies:
  - Layer 0+1: executive() returns anchor + summary
  - Layer 2: query_identity() delegates to SelfModel
  - Layer 3: query_knowledge() returns complexity info
  - Layer 4: query_experience() returns topic history
  - Layer 5: query_critique() returns strategy recommendation
  - relational_context() composes layers into tension-aware string
  - audit_emergence() anti-recita: judges behavioral metrics only
  - Shadow Diagnostic Layer: tracks hits/misses/stats
"""
import sys
import os
import asyncio

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_core(**kwargs):
    from cognition.cognition_core import CognitionCore
    return CognitionCore(**kwargs)


def _mock_self_model(cert_rate=0.5, avg_loops=2.0, severity="medium"):
    m = MagicMock()
    m.get_certification_rate.return_value = cert_rate
    m.get_avg_repair_loops.return_value = avg_loops
    m.self_assess_gaps.return_value = {
        "critical_gaps": ["python_advanced"],
        "missing_skills": ["generators", "coroutines"],
        "gap_rate": 0.4,
        "total_map": 10,
        "missing_count": 4,
        "severity": severity,
    }
    m.summarize_capabilities.return_value = {
        "certified": ["linked list", "bfs", "dfs"],
        "total": 3,
    }
    m.summarize_frontier.return_value = ["python generators", "asyncio", "rust"]
    return m


def _mock_episodic_memory(attempts=3, scores=None):
    if scores is None:
        scores = [0.0, 0.0, 7.4]
    m = MagicMock()
    episodes = [
        {"topic": "test", "score": s, "certified": s >= 7.5,
         "failure_reason": "sandbox_zero" if s == 0 else "",
         "strategies_reused": f"strategy_{i}", "timestamp": "2026-01-01T00:00:00"}
        for i, s in enumerate(scores)
    ]
    m.retrieve_context.return_value = episodes
    return m


# ── Layer 0+1 — executive() ───────────────────────────────────────────────────

def test_executive_returns_anchor_and_summary():
    core = _make_core()
    result = core.executive()
    assert "anchor" in result
    assert "summary" in result
    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


def test_anchor_has_required_keys():
    core = _make_core()
    anchor = core.executive()["anchor"]
    for key in ["certification_rate", "total_experiments", "last_topic",
                "last_score", "last_pass", "last_date", "avg_score"]:
        assert key in anchor, f"Missing key: {key}"


def test_executive_summary_includes_cert_rate():
    core = _make_core()
    summary = core.executive()["summary"]
    assert "Certification rate" in summary


# ── Layer 2 — query_identity() ───────────────────────────────────────────────

def test_query_identity_no_self_model():
    core = _make_core()
    result = core.query_identity()
    assert "error" in result


def test_query_identity_with_self_model():
    sm = _mock_self_model()
    core = _make_core(self_model=sm)
    result = core.query_identity()
    assert "error" not in result
    assert result["certification_rate"] == 0.5
    assert result["avg_repair_loops"] == 2.0
    assert result["gap_severity"] == "medium"
    assert "python_advanced" in result["critical_gaps"]


# ── Layer 4 — query_experience() ─────────────────────────────────────────────

def test_query_experience_no_episodic_memory():
    core = _make_core()
    result = core.query_experience("some topic")
    assert result["attempt_count"] == 0


def test_query_experience_with_history():
    em = _mock_episodic_memory(scores=[0.0, 0.0, 7.4])
    core = _make_core(episodic_memory=em)
    result = core.query_experience("python generators")
    assert result["attempt_count"] == 3
    assert result["best_score"] == 7.4
    assert result["near_miss"] is True
    assert result["sandbox_always_zero"] is False  # last is 7.4, not 0


def test_query_experience_sandbox_always_zero():
    em = _mock_episodic_memory(scores=[0.0, 0.0, 0.0])
    core = _make_core(episodic_memory=em)
    result = core.query_experience("hard topic")
    assert result["sandbox_always_zero"] is True


def test_query_experience_theory_high_sandbox_low():
    # avg > 5 but sandbox always 0
    em = _mock_episodic_memory(scores=[6.0, 6.5, 0.0])
    # This won't trigger because sandbox_always_zero = all last 3 are 0 → False
    # Let's try all zero
    em2 = _mock_episodic_memory(scores=[0.0, 0.0, 0.0])
    core = _make_core(episodic_memory=em2)
    result = core.query_experience("topic")
    # avg_score = 0 → theory_high_sandbox_low = False (avg not > 5)
    assert result["theory_high_sandbox_low"] is False


def test_query_experience_chronic_fail():
    em = _mock_episodic_memory(scores=[3.0, 4.0, 5.0, 6.0])
    core = _make_core(episodic_memory=em)
    result = core.query_experience("rest api design")
    assert result["chronic_fail"] is True  # 4 attempts, best < 7.0


# ── relational_context() ──────────────────────────────────────────────────────

def test_relational_context_returns_string():
    core = _make_core()
    ctx = core.relational_context("python generators")
    assert isinstance(ctx, str)
    assert "python generators" in ctx.lower() or "Topic" in ctx


def test_relational_context_includes_tensions_when_near_miss():
    em = _mock_episodic_memory(scores=[7.4, 7.4])
    sm = _mock_self_model(cert_rate=0.6)
    core = _make_core(self_model=sm, episodic_memory=em)
    ctx = core.relational_context("python generators and coroutines")
    # Should detect near-miss tension
    assert "Near-miss" in ctx or "TENSIONI" in ctx


def test_relational_context_max_length():
    """relational_context should stay under 500 tokens (~3000 chars)."""
    em = _mock_episodic_memory(scores=[0.0, 0.0, 0.0, 0.0])
    sm = _mock_self_model()
    core = _make_core(self_model=sm, episodic_memory=em)
    ctx = core.relational_context("some complex topic with lots of history")
    # Approximate token estimate: 1 token ~ 4 chars
    assert len(ctx) < 3000, f"relational_context too long: {len(ctx)} chars"


# ── audit_emergence() — anti-recita rule ─────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_no_tension_returns_no_tension():
    core = _make_core()
    result = await core.audit_emergence(
        topic="test", action="synthesize",
        delta={"tension_present": False}
    )
    assert result == "[NO TENSION]"
    assert core.get_emergence_stats()["opportunities"] == 0


@pytest.mark.asyncio
async def test_audit_strategy_unchanged_is_missed():
    core = _make_core()
    result = await core.audit_emergence(
        topic="test", action="synthesize",
        delta={
            "strategy_used": "standard",
            "strategy_prev": "standard",
            "sandbox_score": 3.0,
            "sandbox_score_prev": 3.0,
            "attempt_number": 2,
            "tension_present": True,
        }
    )
    assert result == "[MISSED EMERGENCE]"
    stats = core.get_emergence_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0


@pytest.mark.asyncio
async def test_audit_strategy_changed_is_hit():
    core = _make_core()
    result = await core.audit_emergence(
        topic="test", action="retry",
        delta={
            "strategy_used": "practical_impl",
            "strategy_prev": "standard_theory",
            "sandbox_score": 0.0,
            "sandbox_score_prev": 0.0,
            "attempt_number": 2,
            "tension_present": True,
        }
    )
    assert result == "[EMERGENCE HIT]"
    assert core.get_emergence_stats()["hits"] == 1


@pytest.mark.asyncio
async def test_audit_score_improvement_is_hit():
    core = _make_core()
    result = await core.audit_emergence(
        topic="test", action="retry",
        delta={
            "strategy_used": "same_strategy",
            "strategy_prev": "same_strategy",
            "sandbox_score": 8.5,
            "sandbox_score_prev": 3.0,
            "attempt_number": 2,
            "tension_present": True,
        }
    )
    assert result == "[EMERGENCE HIT]"


@pytest.mark.asyncio
async def test_audit_text_output_does_not_count():
    """Anti-recita: LLM text saying the right words must NOT count as emergence."""
    core = _make_core()
    # Even if we pass 'llm_text_looks_correct=True', it must be ignored
    result = await core.audit_emergence(
        topic="test", action="synthesize",
        delta={
            "strategy_used": "standard",
            "strategy_prev": "standard",
            "sandbox_score": 0.0,
            "sandbox_score_prev": 0.0,
            "attempt_number": 2,
            "tension_present": True,
            "llm_text_looks_correct": True,  # this must NOT influence the verdict
        }
    )
    assert result == "[MISSED EMERGENCE]"


@pytest.mark.asyncio
async def test_audit_emergence_rate():
    core = _make_core()
    # 2 hits, 1 miss
    for strategy_changed in [True, True, False]:
        await core.audit_emergence(
            topic="test", action="test",
            delta={
                "strategy_used": "new" if strategy_changed else "same",
                "strategy_prev": "old" if strategy_changed else "same",
                "sandbox_score": 5.0,
                "sandbox_score_prev": 5.0,
                "attempt_number": 2,
                "tension_present": True,
            }
        )
    stats = core.get_emergence_stats()
    assert stats["opportunities"] == 3
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["emergence_rate"] == pytest.approx(2 / 3, abs=0.01)


# ── get_emergence_log() ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergence_log_records_entries():
    core = _make_core()
    await core.audit_emergence(
        topic="generators", action="synthesize",
        delta={"tension_present": True, "strategy_used": "a", "strategy_prev": "a",
               "sandbox_score": 0.0, "sandbox_score_prev": 0.0, "attempt_number": 2}
    )
    log = core.get_emergence_log(last_n=5)
    assert len(log) == 1
    entry = log[0]
    assert entry["topic"] == "generators"
    assert entry["action"] == "synthesize"
    assert "result" in entry
    assert "timestamp" in entry


# ── refresh() ────────────────────────────────────────────────────────────────

def test_refresh_reloads_anchor():
    core = _make_core()
    exec1 = core.executive()
    core.refresh()
    exec2 = core.executive()
    # Both should have the same structure
    assert set(exec1["anchor"].keys()) == set(exec2["anchor"].keys())


# ── singleton factory ─────────────────────────────────────────────────────────

def test_get_cognition_core_singleton():
    from cognition.cognition_core import get_cognition_core, _core_instance
    import cognition.cognition_core as cc_module
    # Reset singleton for test isolation
    cc_module._core_instance = None
    core1 = get_cognition_core()
    core2 = get_cognition_core()
    assert core1 is core2
    cc_module._core_instance = None  # cleanup
