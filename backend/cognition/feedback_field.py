"""feedback_field.py -- GWT Phase 3+4: Reentrant Loop bid modulation with optional persistence.

After each competition cycle, winners decay (0.95) and losers boost (1.05,
capped at 1.5x). This creates emergent coalitions where modules alternate and
cooperate across cycles, preventing static winner-take-all dynamics.

Phase 4: with persist=True, multipliers are loaded from SQLite on init and
saved after each update(), so module reputations survive across sessions.
"""
from __future__ import annotations

from typing import Dict, List


class FeedbackField:
    """Historical bid multipliers updated after each competition cycle.

    Multipliers start at 1.0 (neutral). Winners decay below 1.0 over time;
    losers accumulate boost up to max_multiplier. No artificial floor on
    winner multipliers — chronic dominance results in chronic suppression.

    With persist=True, state is loaded from feedback_field_state (SQLite)
    on init and flushed after every update().
    """

    def __init__(
        self,
        decay: float = 0.95,
        boost: float = 1.05,
        max_multiplier: float = 1.5,
        persist: bool = False,
    ):
        self.decay = decay
        self.boost = boost
        self.max_multiplier = max_multiplier
        self._multipliers: Dict[str, float] = {}
        self._persist = persist

        if self._persist:
            self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def _get_shard_db():
        """Return the already-loaded shard_db module (avoids dual-singleton on dual sys.path)."""
        import sys
        for name in ("shard_db", "backend.shard_db"):
            if name in sys.modules:
                return sys.modules[name]
        try:
            import shard_db
            return shard_db
        except ImportError:
            import backend.shard_db as _m
            return _m

    def _load(self) -> None:
        """Load multipliers from SQLite on init (Phase 4)."""
        try:
            db = self._get_shard_db()
            rows = db.query("SELECT module_name, multiplier FROM feedback_field_state")
            for row in rows:
                self._multipliers[row["module_name"]] = row["multiplier"]
        except Exception:
            pass  # DB unavailable at test time or first run — start fresh

    def _save(self) -> None:
        """Persist current multipliers to SQLite (Phase 4)."""
        if not self._multipliers:
            return
        try:
            db = self._get_shard_db()
            data = list(self._multipliers.items())
            db.executemany(
                "INSERT OR REPLACE INTO feedback_field_state "
                "(module_name, multiplier, updated_at) VALUES (?, ?, datetime('now'))",
                data,
            )
        except Exception:
            pass  # non-fatal: in-memory state is still correct

    # ── Core logic (Phase 3) ──────────────────────────────────────────────────

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

        if self._persist:
            self._save()

    def apply(self, module_name: str, base_bid: float) -> float:
        """Return base_bid scaled by this module's current multiplier."""
        return base_bid * self._multipliers.get(module_name, 1.0)

    def get_multipliers(self) -> Dict[str, float]:
        """Return a copy of current multipliers (for telemetry/tests)."""
        return dict(self._multipliers)

    def reset(self) -> None:
        """Hard reset all multipliers (use between sessions if needed)."""
        self._multipliers.clear()
