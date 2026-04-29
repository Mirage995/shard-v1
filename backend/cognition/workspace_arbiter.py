"""workspace_arbiter.py -- GWT Phase 1: competitive workspace selection.

Modules propose content blocks with a base_salience score. The ValenceField
modulates each bid using the current mood_score before the competition runs.
Only proposals that exceed the ignition_threshold enter the workspace; the
rest are silently suppressed.

This implements the core Global Workspace Theory insight: emotion modulates
competition FROM OUTSIDE -- it does not compete for workspace entry itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Stable output order: context reads naturally regardless of bid ranking
_STABLE_ORDER: List[str] = [
    "experience",
    "knowledge",
    "identity",
    "goal",
    "desire",
    "world",
    "mood_hint",
    "behavior_directive",
]
_ORDER_MAP = {bt: i for i, bt in enumerate(_STABLE_ORDER)}


@dataclass
class WorkspaceProposal:
    module_name: str        # e.g. "identity", "experience", "goal"
    content: str            # text to inject into prompt
    base_salience: float    # 0.0-1.0 intrinsic importance
    topic_affinity: float   # 0.0-1.0 relevance to the current topic
    block_type: str         # one of the types in _STABLE_ORDER
    computed_bid: float = field(default=0.0, compare=False)


class ValenceField:
    """Translate mood_score into per-block bid multipliers.

    The limbic system does NOT compete with cognitive modules -- it modulates
    their bids from outside (Feinberg & Mallatt; Dehaene GNW).
    """

    @staticmethod
    def mod(block_type: str, mood_score: float) -> float:
        arousal = abs(mood_score)
        valence = mood_score

        if block_type == "mood_hint":
            return 1.0
        if block_type == "behavior_directive":
            return 1.2 if arousal > 0.3 else 0.8
        if block_type == "identity":
            # Frustrated: suppress identity noise; agent needs fresh start, not self-history
            return 0.5 if valence < -0.3 else 1.0
        if block_type == "experience":
            # Frustrated: boost experience to avoid repeating failed strategies
            return 1.3 if valence < -0.3 else 1.0
        if block_type == "knowledge":
            return 1.0
        if block_type == "goal":
            # Confident: pursue goals more aggressively
            return 1.2 if valence > 0.3 else 0.9
        if block_type == "desire":
            # Strong emotion (either sign) surfaces desires
            return 1.2 if arousal > 0.3 else 0.9
        if block_type == "world":
            return 1.0
        return 1.0


class WorkspaceArbiter:
    """Run competitive workspace selection on a set of proposals.

    Each call cycle:
      1. add_proposal() for each candidate block
      2. run_competition(mood_score) -> selected proposals
      3. clear() before the next topic

    Phase 3 — Reentrant Loop: with enable_feedback=True, a FeedbackField
    modulates bids using win/loss history, preventing static monopolies.
    """

    def __init__(
        self,
        max_tokens: int = 500,
        ignition_threshold: float = 0.4,
        enable_feedback: bool = True,
        persist_feedback: bool = False,
    ):
        self._max_tokens = max_tokens
        self._ignition_threshold = ignition_threshold
        self._proposals: List[WorkspaceProposal] = []
        self._last_winners: List[WorkspaceProposal] = []
        self._last_ignition_was_fallback: bool = False

        if enable_feedback:
            try:
                from backend.cognition.feedback_field import FeedbackField
            except ImportError:
                from cognition.feedback_field import FeedbackField
            self._feedback = FeedbackField(persist=persist_feedback)
        else:
            self._feedback = None

    def add_proposal(self, p: WorkspaceProposal) -> None:
        self._proposals.append(p)

    def run_competition(self, mood_score: float) -> List[WorkspaceProposal]:
        """Select the best proposals that fit within the token budget.

        Steps:
        1. Compute bid = base_salience × ValenceField.mod × topic_affinity
        2. Filter: bid >= ignition_threshold  (all-or-none ignition)
        3. Sort by bid descending
        4. Greedily select until max_tokens exhausted (1 token ≈ 4 chars)
        5. Fallback: if nothing passes ignition, return highest-bid single proposal
        6. Re-sort selected proposals in stable reading order before returning
        """
        if not self._proposals:
            self._last_winners = []
            return []

        # Step 1 — compute bids (ValenceField × topic_affinity)
        for p in self._proposals:
            _vmod = ValenceField.mod(p.block_type, mood_score)
            p._valence_mod = _vmod
            p.computed_bid = (
                p.base_salience
                * _vmod
                * p.topic_affinity
            )

        # Phase 3: apply FeedbackField multipliers (history-aware)
        if self._feedback:
            for p in self._proposals:
                _pre = p.computed_bid
                p.computed_bid = self._feedback.apply(p.module_name, p.computed_bid)
                p._feedback_mult = (p.computed_bid / _pre) if _pre else 1.0

        # GWT_BID_TRACE: per-proposal breakdown so we can verify mood actually moves bids
        try:
            print(f"[GWT_BID_TRACE] mood_score={mood_score:+.3f}  threshold={self._ignition_threshold:.2f}")
            for p in self._proposals:
                _vmod = getattr(p, "_valence_mod", 1.0)
                _fmult = getattr(p, "_feedback_mult", 1.0)
                print(f"[GWT_BID_TRACE]   {p.module_name:<14} block={p.block_type:<18} base={p.base_salience:.2f} val={_vmod:.2f} fb={_fmult:.2f} aff={p.topic_affinity:.2f} -> bid={p.computed_bid:.3f}")
        except Exception:
            pass

        # Step 2+3 — filter and sort
        above = sorted(
            [p for p in self._proposals if p.computed_bid >= self._ignition_threshold],
            key=lambda p: p.computed_bid,
            reverse=True,
        )

        # Step 4 — greedy token selection
        selected: List[WorkspaceProposal] = []
        char_budget = self._max_tokens * 4
        used_chars = 0
        for p in above:
            cost = len(p.content)
            if used_chars + cost <= char_budget:
                selected.append(p)
                used_chars += cost

        # Step 5 — fallback: nothing passed ignition (tracked for caller)
        self._last_ignition_was_fallback = False
        if not selected:
            self._last_ignition_was_fallback = True
            all_sorted = sorted(self._proposals, key=lambda p: p.computed_bid, reverse=True)
            top = all_sorted[0]
            # Truncate fallback content to stay within token budget
            if len(top.content) > char_budget:
                top = WorkspaceProposal(
                    module_name=top.module_name,
                    content=top.content[:char_budget],
                    base_salience=top.base_salience,
                    topic_affinity=top.topic_affinity,
                    block_type=top.block_type,
                )
            selected = [top]

        # Step 6 — stable reading order
        selected.sort(key=lambda p: _ORDER_MAP.get(p.block_type, len(_STABLE_ORDER)))

        self._last_winners = selected

        # Phase 3: update FeedbackField for next cycle (after winners are decided)
        if self._feedback and self._last_winners:
            winner_names = [w.module_name for w in self._last_winners]
            all_names = list(dict.fromkeys(p.module_name for p in self._proposals))
            self._feedback.update(winner_names, all_names)

        return selected

    def get_winner(self) -> Optional[WorkspaceProposal]:
        """Return the proposal with the highest bid from the last competition."""
        if not self._last_winners:
            return None
        return max(self._last_winners, key=lambda p: p.computed_bid)

    @property
    def last_ignition_was_fallback(self) -> bool:
        """True if the last run_competition() used the fallback (no genuine ignition)."""
        return self._last_ignition_was_fallback

    def get_proposals(self) -> List[WorkspaceProposal]:
        """Return current proposals (for safety guard pre-processing)."""
        return self._proposals

    def set_proposals(self, proposals: List[WorkspaceProposal]) -> None:
        """Replace proposals (for safety guard post-processing)."""
        self._proposals = proposals

    def clear(self) -> None:
        self._proposals = []
        self._last_winners = []
