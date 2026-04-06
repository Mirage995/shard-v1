"""episode_decay.py -- Garbage collection and confidence decay for the memories table.

Runs periodically (called by NightRunner at session end, or manually).

Three operations:
  1. EXPIRY    -- mark is_latest=0 for memories past their expires_at
  2. DECAY     -- halve confidence of EPISODE memories older than half_life_days
                  (half-life default: 7 days). Remove if confidence < min_confidence.
  3. PRUNE     -- hard-delete is_latest=0 memories older than prune_after_days (default: 90)

All operations are logged and return a GCResult summary.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from shard_db import execute, query

logger = logging.getLogger("shard.episode_decay")

# ── Defaults ──────────────────────────────────────────────────────────────────

HALF_LIFE_DAYS     = 7     # EPISODE confidence halves every 7 days
MIN_CONFIDENCE     = 0.05  # Below this → delete EPISODE
PRUNE_AFTER_DAYS   = 90    # Hard-delete superseded memories after 90 days


@dataclass
class GCResult:
    expired:  int = 0   # Memories marked is_latest=0 due to expires_at
    decayed:  int = 0   # EPISODE memories whose confidence was reduced
    deleted:  int = 0   # EPISODE memories deleted (confidence < min)
    pruned:   int = 0   # Old superseded memories hard-deleted
    total_memories_before: int = 0
    total_memories_after:  int = 0

    def __str__(self) -> str:
        return (
            f"GC: expired={self.expired} decayed={self.decayed} "
            f"deleted={self.deleted} pruned={self.pruned} | "
            f"memories: {self.total_memories_before} -> {self.total_memories_after}"
        )


def run_gc(
    half_life_days:   int   = HALF_LIFE_DAYS,
    min_confidence:   float = MIN_CONFIDENCE,
    prune_after_days: int   = PRUNE_AFTER_DAYS,
) -> GCResult:
    """Run all GC operations synchronously. Safe to call from any context.

    Returns a GCResult with counts of each operation.
    """
    result = GCResult()
    now = datetime.now()
    now_iso = now.isoformat()

    # Count before
    rows = query("SELECT COUNT(*) as n FROM memories", ())
    result.total_memories_before = rows[0]["n"] if rows else 0

    # ── 1. EXPIRY ─────────────────────────────────────────────────────────────
    # Mark memories past expires_at as is_latest=0
    expired_rows = query(
        """SELECT id FROM memories
           WHERE is_latest=1 AND expires_at IS NOT NULL AND expires_at < ?""",
        (now_iso,),
    )
    if expired_rows:
        for row in expired_rows:
            execute(
                "UPDATE memories SET is_latest=0, updated_at=? WHERE id=?",
                (now_iso, row["id"]),
            )
        result.expired = len(expired_rows)
        logger.info("[GC] Expired %d memories past expires_at", result.expired)

    # ── 2. DECAY ─────────────────────────────────────────────────────────────
    # Reduce confidence of EPISODE memories based on age
    episodes = query(
        """SELECT id, confidence, created_at FROM memories
           WHERE is_latest=1 AND memory_type='EPISODE'""",
        (),
    )
    for ep in episodes:
        try:
            created = datetime.fromisoformat(ep["created_at"])
            age_days = (now - created).days
            if age_days <= 0:
                continue
            # Exponential decay: C(t) = C0 * 0.5^(t / half_life)
            new_conf = ep["confidence"] * (0.5 ** (age_days / half_life_days))
            if new_conf < min_confidence:
                # Delete — too stale to be useful
                execute("DELETE FROM memories WHERE id=?", (ep["id"],))
                result.deleted += 1
                logger.debug(
                    "[GC] Deleted EPISODE (conf=%.3f after %dd): id=%s",
                    new_conf, age_days, ep["id"][:8],
                )
            elif abs(new_conf - ep["confidence"]) > 0.01:
                # Update if decay is meaningful (>1% change)
                execute(
                    "UPDATE memories SET confidence=?, updated_at=? WHERE id=?",
                    (round(new_conf, 4), now_iso, ep["id"]),
                )
                result.decayed += 1
        except Exception as exc:
            logger.debug("[GC] Decay failed for %s: %s", ep.get("id", "?")[:8], exc)

    if result.decayed or result.deleted:
        logger.info(
            "[GC] EPISODE decay: %d updated, %d deleted",
            result.decayed, result.deleted,
        )

    # ── 3. PRUNE ─────────────────────────────────────────────────────────────
    # Hard-delete superseded (is_latest=0) memories older than prune_after_days
    cutoff = (now - timedelta(days=prune_after_days)).isoformat()
    pruned = query(
        """SELECT COUNT(*) as n FROM memories
           WHERE is_latest=0 AND updated_at < ?""",
        (cutoff,),
    )
    if pruned and pruned[0]["n"] > 0:
        execute(
            "DELETE FROM memories WHERE is_latest=0 AND updated_at < ?",
            (cutoff,),
        )
        result.pruned = pruned[0]["n"]
        logger.info("[GC] Pruned %d old superseded memories", result.pruned)

    # Count after
    rows_after = query("SELECT COUNT(*) as n FROM memories", ())
    result.total_memories_after = rows_after[0]["n"] if rows_after else 0

    logger.info("[GC] %s", result)
    return result
