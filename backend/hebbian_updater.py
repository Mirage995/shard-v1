"""hebbian_updater.py — Synaptic plasticity for SHARD.

Implements Hebbian learning over the synaptic_weights table:
  - LTP (Long-Term Potentiation): neurons that fire TOGETHER on a certified cycle
    get stronger (+delta).
  - LTD (Long-Term Depression): neurons that fire together on a FAILED cycle
    get weaker (-delta).
  - Decay: inactive pairs drift toward baseline over time.

Usage (NightRunner calls this after every cycle):
    from hebbian_updater import HebbianUpdater
    updater = HebbianUpdater()
    updater.update(signals, certified=True)

Seed from historical data:
    updater.seed_from_activation_log()
"""
import logging
import math
from datetime import datetime
from typing import Dict

logger = logging.getLogger("shard.hebbian")

# ── Tunables ──────────────────────────────────────────────────────────────────

CITIZENS = [
    "sig_episodic",
    "sig_strategy",
    "sig_near_miss",
    "sig_first_try",
    "sig_graphrag",
    "sig_improvement",
    "sig_desire",
    "sig_difficulty",
]

LTP_DELTA   = 0.05   # weight increase on co-activation + certified
LTD_DELTA   = 0.03   # weight decrease on co-activation + failed
WEIGHT_MIN  = 0.05   # floor
WEIGHT_MAX  = 2.0    # ceiling
WEIGHT_INIT = 1.0    # default weight for unseen pairs
ACTIVE_THRESHOLD = 0.5  # signal must exceed this to count as "active"


class HebbianUpdater:
    """Update synaptic_weights after every NightRunner cycle."""

    def __init__(self):
        self._ensure_schema()

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, signals: Dict[str, float], certified: bool) -> int:
        """Apply LTP or LTD for all co-active citizen pairs.

        signals: dict of {citizen_name: float 0.0-1.0}
        certified: True if the cycle was certified (score >= threshold)

        Returns number of synaptic pairs updated.
        """
        active = [c for c in CITIZENS if signals.get(c, 0.0) > ACTIVE_THRESHOLD]
        if len(active) < 2:
            return 0

        updated = 0
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                self._apply_plasticity(a, b, certified)
                updated += 1

        return updated

    def seed_from_activation_log(self) -> int:
        """Bootstrap synaptic_weights from all existing activation_log rows.

        Called once to initialise weights from collected data.
        Safe to call multiple times — uses ltp_count/ltd_count to avoid
        double-counting rows that were already processed.

        Returns number of pairs seeded/updated.
        """
        try:
            from shard_db import query as db_query
            rows = db_query("SELECT * FROM activation_log ORDER BY timestamp")
            if not rows:
                logger.info("[HEBBIAN] No activation_log data to seed from.")
                return 0

            total_updates = 0
            for row in rows:
                signals = {c: row.get(c, 0.0) for c in CITIZENS}
                certified = bool(row.get("certified", 0))
                n = self.update(signals, certified)
                total_updates += n

            logger.info("[HEBBIAN] Seeded from %d activation_log rows, %d pair updates", len(rows), total_updates)
            return total_updates
        except Exception as e:
            logger.warning("[HEBBIAN] seed_from_activation_log failed: %s", e)
            return 0

    def get_weights(self) -> list[dict]:
        """Return all synaptic weights sorted by weight descending."""
        try:
            from shard_db import query as db_query
            return db_query(
                "SELECT * FROM synaptic_weights ORDER BY weight DESC"
            )
        except Exception:
            return []

    def get_weight(self, citizen_a: str, citizen_b: str) -> float:
        """Return weight for a specific pair (canonical order)."""
        a, b = sorted([citizen_a, citizen_b])
        try:
            from shard_db import query_one
            row = query_one(
                "SELECT weight FROM synaptic_weights WHERE source_citizen=? AND target_citizen=?",
                (a, b),
            )
            return float(row["weight"]) if row else WEIGHT_INIT
        except Exception:
            return WEIGHT_INIT

    def get_stats(self) -> dict:
        """Stats for /health endpoint."""
        try:
            from shard_db import query as db_query, query_one
            total = query_one("SELECT COUNT(*) as n FROM synaptic_weights")
            top = db_query(
                "SELECT source_citizen, target_citizen, weight, ltp_count, ltd_count "
                "FROM synaptic_weights ORDER BY weight DESC LIMIT 5"
            )
            bottom = db_query(
                "SELECT source_citizen, target_citizen, weight, ltp_count, ltd_count "
                "FROM synaptic_weights ORDER BY weight ASC LIMIT 5"
            )
            return {
                "total_pairs": total["n"] if total else 0,
                "strongest":   top,
                "weakest":     bottom,
            }
        except Exception as e:
            return {"error": str(e)}

    # ── CognitionCore interface ───────────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to events from other modules."""
        if event_type == "mood_shift":
            if data.get("to") == "frustrated":
                # Frustration → decay all synaptic weights 5% toward baseline (WEIGHT_INIT).
                # Simulates "clearing the pattern" — same effect as the prompt hint
                # "Start from zero". Pairs > 1.0 drop slightly; pairs < 1.0 rise slightly.
                n = self._frustration_decay()
                logger.info("[HEBBIAN] mood_shift(frustrated) → decayed %d pair(s) toward baseline", n)

    def _frustration_decay(self, decay_rate: float = 0.05) -> int:
        """Decay all synaptic weights 5% toward WEIGHT_INIT on frustration."""
        try:
            from shard_db import query as db_query, execute as db_exec
            pairs = db_query("SELECT source, target, weight FROM synaptic_weights")
            updated = 0
            for p in pairs:
                w = p["weight"]
                new_w = round(w + decay_rate * (WEIGHT_INIT - w), 4)
                new_w = max(WEIGHT_MIN, min(WEIGHT_MAX, new_w))
                if abs(new_w - w) > 0.001:
                    db_exec(
                        "UPDATE synaptic_weights SET weight=? WHERE source=? AND target=?",
                        (new_w, p["source"], p["target"]),
                    )
                    updated += 1
            return updated
        except Exception as e:
            logger.debug("[HEBBIAN] frustration_decay error: %s", e)
            return 0

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply_plasticity(self, a: str, b: str, certified: bool) -> None:
        """LTP if certified, LTD if not. Creates pair if missing."""
        # Canonical order: always store (smaller, larger) alphabetically
        src, tgt = sorted([a, b])
        now = datetime.now().isoformat()

        try:
            from shard_db import query_one, execute

            row = query_one(
                "SELECT weight, ltp_count, ltd_count FROM synaptic_weights "
                "WHERE source_citizen=? AND target_citizen=?",
                (src, tgt),
            )

            if row is None:
                # First time this pair co-activates — initialise
                weight = WEIGHT_INIT + LTP_DELTA if certified else WEIGHT_INIT - LTD_DELTA
                weight = max(WEIGHT_MIN, min(WEIGHT_MAX, weight))
                ltp = 1 if certified else 0
                ltd = 0 if certified else 1
                execute(
                    """INSERT INTO synaptic_weights
                       (source_citizen, target_citizen, weight, ltp_count, ltd_count, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (src, tgt, weight, ltp, ltd, now),
                )
            else:
                delta  = LTP_DELTA if certified else -LTD_DELTA
                weight = float(row["weight"]) + delta
                weight = max(WEIGHT_MIN, min(WEIGHT_MAX, weight))
                ltp = row["ltp_count"] + (1 if certified else 0)
                ltd = row["ltd_count"] + (0 if certified else 1)
                execute(
                    """UPDATE synaptic_weights
                       SET weight=?, ltp_count=?, ltd_count=?, last_updated=?
                       WHERE source_citizen=? AND target_citizen=?""",
                    (weight, ltp, ltd, now, src, tgt),
                )
        except Exception as e:
            logger.debug("[HEBBIAN] _apply_plasticity error: %s", e)

    def _ensure_schema(self) -> None:
        """synaptic_weights table is created by shard_db migrations — just verify."""
        try:
            from shard_db import query_one
            query_one("SELECT COUNT(*) FROM synaptic_weights")
        except Exception as e:
            logger.warning("[HEBBIAN] synaptic_weights not accessible: %s — run shard_db.get_db() first", e)
