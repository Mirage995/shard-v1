"""context_arbiter.py -- per-topic context competition using ValenceField.

Collects candidate context blocks, computes valence-modulated bids, and
returns a token-budget-aware selection in stable reading order.

Reuses ValenceField from workspace_arbiter so mood modulation is consistent
between GWT Phase 1 (CognitionCore) and Phase 2 (per-topic NightRunner context).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from backend.cognition.workspace_arbiter import ValenceField

_STABLE_ORDER: List[str] = [
    "past_context",
    "identity_block",
    "domain_directive",
    "skill_library",
    "mood_hint",
    "behavior_directive",
]
_ORDER_MAP = {bt: i for i, bt in enumerate(_STABLE_ORDER)}

# Map ContextArbiter block types → ValenceField block types so mood modulation
# uses the same rules as GWT Phase 1 (WorkspaceArbiter).
_VF_TYPE: dict = {
    "past_context":        "experience",
    "identity_block":      "identity",
    "domain_directive":    "knowledge",
    "skill_library":       "knowledge",
    "mood_hint":           "mood_hint",
    "behavior_directive":  "behavior_directive",
}


@dataclass
class ContextBlock:
    content: str
    block_type: str
    base_salience: float
    topic_affinity: float = 1.0
    computed_bid: float = field(default=0.0, compare=False)


class ContextArbiter:
    """Competitive context selection for per-topic prompt assembly.

    Usage per cycle:
      1. add_block() for each candidate
      2. select(mood_score) -> composed context string
      3. clear() before the next topic (or let NightRunner create a new instance)
    """

    def __init__(self, max_tokens: int = 500, threshold: float = 0.3):
        self.max_tokens = max_tokens
        self.threshold = threshold
        self.blocks: List[ContextBlock] = []

    def add_block(
        self,
        content: str,
        block_type: str,
        base_salience: float,
        topic_affinity: float = 1.0,
    ) -> None:
        if content:
            self.blocks.append(
                ContextBlock(content, block_type, base_salience, topic_affinity)
            )

    def select(self, mood_score: float) -> str:
        """Return winning blocks joined by double newline in stable reading order.

        Steps:
        1. bid = base_salience * ValenceField.mod(block_type, mood_score) * topic_affinity
        2. Filter: bid >= threshold
        3. Sort descending by bid
        4. Greedy token selection (1 token ≈ 4 chars)
        5. Re-sort selected in stable reading order
        6. Return joined with "\\n\\n"
        """
        if not self.blocks:
            return ""

        for b in self.blocks:
            vf_type = _VF_TYPE.get(b.block_type, b.block_type)
            b.computed_bid = (
                b.base_salience
                * ValenceField.mod(vf_type, mood_score)
                * b.topic_affinity
            )

        above = sorted(
            [b for b in self.blocks if b.computed_bid >= self.threshold],
            key=lambda b: b.computed_bid,
            reverse=True,
        )

        selected: List[ContextBlock] = []
        char_budget = self.max_tokens * 4
        used_chars = 0
        for b in above:
            cost = len(b.content)
            if used_chars + cost <= char_budget:
                selected.append(b)
                used_chars += cost

        if not selected and self.blocks:
            all_sorted = sorted(self.blocks, key=lambda b: b.computed_bid, reverse=True)
            selected = [all_sorted[0]]

        selected.sort(key=lambda b: _ORDER_MAP.get(b.block_type, len(_STABLE_ORDER)))

        return "\n\n".join(b.content for b in selected).strip()

    def clear(self) -> None:
        self.blocks = []
