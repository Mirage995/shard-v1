"""feedback_field.py -- GWT Phase 3: Reentrant Loop bid modulation.

After each competition cycle, winners decay (0.95) and losers boost (1.05,
capped at 1.5x). This creates emergent coalitions where modules alternate and
cooperate across cycles, preventing static winner-take-all dynamics.

FeedbackField is pure in-memory state — no DB, no I/O.
Lifecycle: one instance per WorkspaceArbiter, lives for the session.
"""
from __future__ import annotations

from typing import Dict, List


class FeedbackField:
    """Historical bid multipliers updated after each competition cycle.

    Multipliers start at 1.0 (neutral). Winners decay below 1.0 over time;
    losers accumulate boost up to max_multiplier. No artificial floor on
    winner multipliers — chronic dominance results in chronic suppression.
    """

    def __init__(
        self,
        decay: float = 0.95,
        boost: float = 1.05,
        max_multiplier: float = 1.5,
    ):
        self.decay = decay
        self.boost = boost
        self.max_multiplier = max_multiplier
        self._multipliers: Dict[str, float] = {}

    def update(self, winners: List[str], all_modules: List[str]) -> None:
        """Apply decay to winners, boost to losers for the next cycle.

        Args:
            winners:     module_names that won this competition
            all_modules: all module_names that proposed this cycle
        """
        winner_set = set(winners)
        for name in all_modules:
            if name in winner_set:
                current = self._multipliers.get(name, 1.0)
                self._multipliers[name] = current * self.decay
            else:
                current = self._multipliers.get(name, 1.0)
                self._multipliers[name] = min(current * self.boost, self.max_multiplier)

    def apply(self, module_name: str, base_bid: float) -> float:
        """Return base_bid scaled by this module's current multiplier."""
        return base_bid * self._multipliers.get(module_name, 1.0)

    def get_multipliers(self) -> Dict[str, float]:
        """Return a copy of current multipliers (for telemetry/tests)."""
        return dict(self._multipliers)

    def reset(self) -> None:
        """Hard reset all multipliers (use between sessions if needed)."""
        self._multipliers.clear()
