"""workspace_safety.py -- Safety guards for the GWT Workspace Arbiter.

Prevents emergent pathologies:
  - Ignition failure (empty workspace)
  - Winner monopoly (same module dominates)
  - Mood death spirals (frustration feedback loop)
  - Workspace telemetry for Shadow Diagnostic

Designed to integrate cleanly with WorkspaceArbiter + CognitionCore.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("shard.workspace_safety")


@dataclass
class SafetyConfig:
    """Tunable parameters for workspace safety guards."""
    max_consecutive_wins: int = 5          # anti-monopoly threshold
    monopoly_boost_factor: float = 1.3     # diversity boost for non-monopoly modules
    ignition_fallback: bool = True         # fallback to anchor+executive if empty
    diversity_window: int = 20             # cycles to measure diversity
    mood_spiral_threshold: float = -0.7    # mood below this triggers guard
    mood_spiral_cycles: int = 3            # consecutive cycles below threshold
    max_workspace_tokens: int = 500        # same as arbiter


class WorkspaceSafetyGuard:
    """Monitor and intervene on workspace dynamics.

    Usage:
        guard = WorkspaceSafetyGuard(config=SafetyConfig())

        # Before competition: check for monopoly override
        if guard.is_monopoly():
            proposals = guard.force_diversity_boost(proposals)

        # After competition: track winner
        guard.track_winner(winner_module, selected_proposals)

        # If workspace empty: get fallback
        if guard.check_ignition_failure(selected_proposals):
            fallback = guard.get_fallback_context(cognition_core)

        # Telemetry for Shadow Diagnostic
        telemetry = guard.get_telemetry()
    """

    def __init__(self, config: Optional[SafetyConfig] = None):
        self.config = config or SafetyConfig()
        self._winner_history: List[str] = []
        self._consecutive_counts: Dict[str, int] = {}
        self._last_winner: Optional[str] = None
        self._total_cycles: int = 0
        self._ignition_hits: int = 0
        self._mood_history: List[float] = []

    # ── Ignition Guard ──────────────────────────────────────────────────────

    def check_ignition_failure(self, selected_proposals: List[Any]) -> bool:
        """Return True if workspace is empty (no proposal passed ignition)."""
        return len(selected_proposals) == 0

    def get_fallback_context(self, cognition_core) -> str:
        """Return minimal safe context: Anchor + Executive only.

        Args:
            cognition_core: CognitionCore instance with .executive() method
        """
        try:
            exec_data = cognition_core.executive()
            anchor = exec_data.get("anchor", {})
            summary = exec_data.get("summary", "")
            return (
                f"[WORKSPACE FALLBACK] Ignition failed — minimal context loaded.\n"
                f"{summary}\n"
                f"Anchor: cert_rate={anchor.get('certification_rate', 0.0):.0%} "
                f"| last={anchor.get('last_topic', '--')}"
            )
        except Exception as exc:
            logger.warning("[SAFETY] Fallback context failed: %s", exc)
            return "[WORKSPACE FALLBACK] Minimal context unavailable."

    # ── Monopoly / Diversity Guard ──────────────────────────────────────────

    def track_winner(self, winner_module: Optional[str], selected_proposals: List[Any]) -> None:
        """Record winner for diversity tracking. Call after each competition."""
        self._total_cycles += 1

        if selected_proposals:
            self._ignition_hits += 1

        if winner_module is None:
            # No winner — reset consecutive counts
            self._consecutive_counts = {}
            self._last_winner = None
            return

        self._winner_history.append(winner_module)
        # Keep history bounded
        if len(self._winner_history) > self.config.diversity_window * 2:
            self._winner_history = self._winner_history[-self.config.diversity_window:]

        if winner_module == self._last_winner:
            self._consecutive_counts[winner_module] = (
                self._consecutive_counts.get(winner_module, 0) + 1
            )
        else:
            # Reset all counts on winner change
            self._consecutive_counts = {winner_module: 1}

        self._last_winner = winner_module

    def is_monopoly(self) -> Optional[str]:
        """Return module name if it has won consecutively >= max_consecutive_wins."""
        for module, count in self._consecutive_counts.items():
            if count >= self.config.max_consecutive_wins:
                logger.warning(
                    "[SAFETY] Monopoly detected: '%s' won %d consecutive times",
                    module, count,
                )
                return module
        return None

    def force_diversity_boost(self, proposals: List[Any], monopoly_module: Optional[str] = None) -> List[Any]:
        """Boost base_salience of all proposals EXCEPT the monopoly module.

        Mutates proposals in-place for efficiency.
        """
        target = monopoly_module or self.is_monopoly()
        if target is None:
            return proposals

        boosted = 0
        for p in proposals:
            if getattr(p, "module_name", None) != target:
                old = getattr(p, "base_salience", 0.5)
                new = min(1.0, round(old * self.config.monopoly_boost_factor, 3))
                p.base_salience = new
                boosted += 1

        logger.info(
            "[SAFETY] Diversity boost applied: %d proposals boosted (monopoly='%s')",
            boosted, target,
        )
        return proposals

    # ── Mood Death-Spiral Guard ─────────────────────────────────────────────

    def track_mood(self, mood_score: float) -> bool:
        """Track mood history. Return True if death-spiral condition is met.

        Death spiral = mood < threshold for N consecutive tracking calls.
        """
        self._mood_history.append(mood_score)
        # Keep bounded
        if len(self._mood_history) > self.config.mood_spiral_cycles * 2:
            self._mood_history = self._mood_history[-self.config.mood_spiral_cycles * 2:]

        # Check last N values
        recent = self._mood_history[-self.config.mood_spiral_cycles:]
        if len(recent) < self.config.mood_spiral_cycles:
            return False

        if all(m < self.config.mood_spiral_threshold for m in recent):
            logger.warning(
                "[SAFETY] Mood death-spiral detected: %d consecutive moods below %.2f (%s)",
                self.config.mood_spiral_cycles,
                self.config.mood_spiral_threshold,
                recent,
            )
            return True
        return False

    def get_spiral_override(self) -> Dict[str, Any]:
        """Return override directives when death-spiral is detected.

        Callers should:
          1. Clear workspace history
          2. Force experience module to win (learn from past failures)
          3. Suppress identity (avoid self-blame narratives)
        """
        return {
            "clear_context": True,
            "force_module": "experience",
            "suppress_module": "identity",
            "reason": "mood_death_spiral_override",
        }

    # ── Telemetry for Shadow Diagnostic ─────────────────────────────────────

    def get_telemetry(self) -> Dict[str, Any]:
        """Return workspace dynamics metrics for audit_emergence()."""
        recent = self._winner_history[-self.config.diversity_window:]
        unique_winners = len(set(recent)) if recent else 0
        total_recent = len(recent)

        return {
            "ignition_rate": round(
                self._ignition_hits / max(1, self._total_cycles), 3
            ),
            "diversity_index": round(
                unique_winners / max(1, total_recent), 3
            ),
            "total_cycles": self._total_cycles,
            "ignition_hits": self._ignition_hits,
            "consecutive_wins": dict(self._consecutive_counts),
            "last_5_winners": self._winner_history[-5:],
            "monopoly_active": self.is_monopoly() is not None,
            "mood_spiral_active": (
                len(self._mood_history) >= self.config.mood_spiral_cycles
                and all(
                    m < self.config.mood_spiral_threshold
                    for m in self._mood_history[-self.config.mood_spiral_cycles:]
                )
            ),
        }

    def reset(self) -> None:
        """Hard reset all counters. Use between sessions."""
        self._winner_history.clear()
        self._consecutive_counts.clear()
        self._last_winner = None
        self._total_cycles = 0
        self._ignition_hits = 0
        self._mood_history.clear()
