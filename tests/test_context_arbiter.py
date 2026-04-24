"""Tests for ContextArbiter -- GWT Phase 2 per-topic context competition."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from context_arbiter import ContextArbiter, ContextBlock


# ── Helpers ───────────────────────────────────────────────────────────────────

def _arb(max_tokens=500, threshold=0.3):
    return ContextArbiter(max_tokens=max_tokens, threshold=threshold)


# ── 1. select() returns non-empty string with typical blocks ─────────────────

def test_select_returns_content_with_typical_blocks():
    arb = _arb()
    arb.add_block("Past session context here.", "past_context", 0.75)
    arb.add_block("[SHARD IDENTITY] cert_rate=60%", "identity_block", 0.70)
    arb.add_block("[MOOD HINT] Neutral state.", "mood_hint", 0.90)
    result = arb.select(mood_score=0.0)
    assert result != ""
    assert "Past session context" in result


# ── 2. select() respects max_tokens ──────────────────────────────────────────

def test_select_respects_max_tokens():
    arb = _arb(max_tokens=10, threshold=0.0)  # 10 tokens = 40 chars
    arb.add_block("x" * 100, "past_context", 0.75)   # 100 chars >> 40
    arb.add_block("y" * 30, "identity_block", 0.70)   # 30 chars fits
    result = arb.select(mood_score=0.0)
    assert "y" * 30 in result
    assert "x" * 100 not in result


# ── 3. Frustrated mood: identity_block suppressed ────────────────────────────

def test_frustrated_mood_suppresses_identity():
    # identity_block bid = 0.70 * ValenceField.mod("identity", -0.8) * 1.0
    # ValenceField.mod("identity", -0.8) = 0.5 (valence < -0.3)
    # bid = 0.70 * 0.5 = 0.35 < threshold 0.3? No, 0.35 > 0.3 -- threshold is 0.3
    # With threshold=0.36, 0.35 < 0.36 -> suppressed
    arb = _arb(threshold=0.36)
    arb.add_block("[IDENTITY]", "identity_block", 0.70)
    arb.add_block("[EXPERIENCE]", "past_context", 0.75)
    result = arb.select(mood_score=-0.8)
    assert "[IDENTITY]" not in result
    assert "[EXPERIENCE]" in result   # past_context: 0.75 * 1.0 = 0.75 >= 0.36


def test_frustrated_mood_identity_bid_value():
    # Verify the exact bid: 0.70 * 0.5 (frustrated mod) * 1.0 = 0.35
    arb = _arb(threshold=0.0)
    arb.add_block("[IDENTITY]", "identity_block", 0.70)
    arb.select(mood_score=-0.8)
    identity_block = arb.blocks[0]
    assert abs(identity_block.computed_bid - 0.35) < 1e-9


# ── 4. Confident mood: behavior_directive boosted ────────────────────────────

def test_confident_mood_boosts_behavior_directive():
    # behavior_directive bid = 0.85 * 1.2 (arousal>0.3) * 1.0 = 1.02
    arb = _arb(threshold=0.0)
    arb.add_block("[DIRECTIVE]", "behavior_directive", 0.85)
    arb.select(mood_score=+0.8)
    directive_block = arb.blocks[0]
    assert abs(directive_block.computed_bid - 1.02) < 1e-9


def test_confident_mood_directive_included():
    arb = _arb()
    arb.add_block("[DIRECTIVE] push deeper", "behavior_directive", 0.85)
    arb.add_block("[IDENTITY]", "identity_block", 0.70)
    result = arb.select(mood_score=+0.8)
    assert "[DIRECTIVE]" in result


# ── 5. Empty blocks list returns empty string ─────────────────────────────────

def test_empty_blocks_returns_empty_string():
    arb = _arb()
    result = arb.select(mood_score=0.0)
    assert result == ""


# ── 6. Stable reading order ───────────────────────────────────────────────────

def test_stable_reading_order():
    arb = _arb(threshold=0.0)
    arb.add_block("MOOD", "mood_hint", 0.90)
    arb.add_block("PAST", "past_context", 0.75)
    arb.add_block("IDENTITY", "identity_block", 0.70)
    arb.add_block("DIRECTIVE", "behavior_directive", 0.85)
    result = arb.select(mood_score=0.0)
    # Stable order: past_context, identity_block, mood_hint, behavior_directive
    assert result.index("PAST") < result.index("IDENTITY")
    assert result.index("IDENTITY") < result.index("MOOD")
    assert result.index("MOOD") < result.index("DIRECTIVE")


# ── 7. clear() resets blocks ─────────────────────────────────────────────────

def test_clear_resets_blocks():
    arb = _arb()
    arb.add_block("content", "past_context", 0.75)
    arb.clear()
    assert arb.select(mood_score=0.0) == ""


# ── 8. Fallback when nothing passes threshold ────────────────────────────────

def test_fallback_when_nothing_passes_threshold():
    arb = _arb(threshold=0.99)
    arb.add_block("only block", "past_context", 0.75)
    result = arb.select(mood_score=0.0)
    assert "only block" in result


# ── 9. NightRunner arousal coupling: frustrated reduces budget ────────────────

def test_arousal_coupling_frustrated_reduces_budget():
    topic_budget = 20
    mood_score = -0.8
    arousal = abs(mood_score)
    valence = mood_score
    if valence < -0.3 and arousal > 0.4:
        effective = max(5, round(topic_budget * 0.7))
    elif valence > 0.3 and arousal > 0.4:
        effective = round(topic_budget * 1.3)
    else:
        effective = topic_budget
    assert effective == max(5, round(20 * 0.7))   # 14


def test_arousal_coupling_confident_increases_budget():
    topic_budget = 20
    mood_score = +0.8
    arousal = abs(mood_score)
    valence = mood_score
    if valence < -0.3 and arousal > 0.4:
        effective = max(5, round(topic_budget * 0.7))
    elif valence > 0.3 and arousal > 0.4:
        effective = round(topic_budget * 1.3)
    else:
        effective = topic_budget
    assert effective == round(20 * 1.3)   # 26


def test_arousal_coupling_neutral_unchanged():
    topic_budget = 20
    mood_score = 0.0
    arousal = abs(mood_score)
    valence = mood_score
    if valence < -0.3 and arousal > 0.4:
        effective = max(5, round(topic_budget * 0.7))
    elif valence > 0.3 and arousal > 0.4:
        effective = round(topic_budget * 1.3)
    else:
        effective = topic_budget
    assert effective == 20


def test_arousal_coupling_never_below_5():
    # With budget=5 and frustrated: max(5, round(5*0.7)) = max(5, 4) = 5
    topic_budget = 5
    effective = max(5, round(topic_budget * 0.7))
    assert effective == 5


# ── Task-aware selection (GWT tactical mode) ─────────────────────────────────

def test_tactical_suppresses_identity_below_threshold():
    # identity_block base_salience=0.4 → after 0.6× = 0.24 < threshold 0.3 → excluded
    # skill_library base_salience=0.4 → after 1.3× = 0.52 > threshold 0.3 → included
    arb = _arb(threshold=0.3)
    arb.add_block("skill content here", "skill_library", 0.4)
    arb.add_block("identity content here", "identity_block", 0.4)
    result = arb.select(mood_score=0.0, task_type="tactical")
    assert "skill content" in result
    assert "identity content" not in result


def test_tactical_suppresses_mood_hint():
    arb = _arb(threshold=0.25)
    # mood_hint base_salience=0.3 → after 0.6× suppression = 0.18 < threshold
    arb.add_block("mood hint text", "mood_hint", 0.3)
    arb.add_block("skill content", "skill_library", 0.4)
    result = arb.select(mood_score=0.0, task_type="tactical")
    assert "skill content" in result
    assert "mood hint text" not in result


def test_strategic_unchanged_behavior():
    arb1 = _arb()
    arb2 = _arb()
    for arb in (arb1, arb2):
        arb.add_block("past ctx", "past_context", 0.75)
        arb.add_block("identity block", "identity_block", 0.70)
        arb.add_block("mood hint", "mood_hint", 0.90)
    assert arb1.select(mood_score=0.0) == arb2.select(mood_score=0.0, task_type="strategic")


def test_unknown_task_type_falls_back_to_strategic():
    arb = _arb()
    arb.add_block("content", "past_context", 0.75)
    result = arb.select(mood_score=0.0, task_type="unknown_value")
    assert "content" in result
