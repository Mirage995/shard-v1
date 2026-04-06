"""memory_quality.py -- Quality scoring and pruning for the memories table.

Runs as the 4th step of run_gc() (after EXPIRY, DECAY, PRUNE).

Two operations:
  1. JUNK_PRUNE  -- delete is_latest=1 memories that fail minimum quality thresholds
  2. DEDUP       -- when two memories share >75% word overlap, delete the lower-confidence one

Quality thresholds per memory_type:
  FACT      confidence >= 0.40, entities not empty, content length >= 25
  RELATION  confidence >= 0.40, entities not empty, content length >= 25
  EPISODE   confidence >= 0.20, content length >= 20
  GOAL      confidence >= 0.30, content length >= 20
  PREFERENCE confidence >= 0.30, content length >= 20

Hard filters (always delete regardless of type):
  - confidence < 0.08
  - content length < 15
  - content contains known error artifacts ("ALL PROVIDERS FAILED", etc.)
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import List, Set

from shard_db import execute, query

logger = logging.getLogger("shard.memory_quality")

# ── Thresholds ─────────────────────────────────────────────────────────────────

# Hard floor — anything below this is garbage regardless of type
HARD_MIN_CONFIDENCE  = 0.08
HARD_MIN_CONTENT_LEN = 15

# Per-type soft floors
_TYPE_THRESHOLDS = {
    "FACT":       {"conf": 0.40, "min_len": 25, "require_entities": True},
    "RELATION":   {"conf": 0.40, "min_len": 25, "require_entities": True},
    "EPISODE":    {"conf": 0.20, "min_len": 20, "require_entities": False},
    "GOAL":       {"conf": 0.30, "min_len": 20, "require_entities": False},
    "PREFERENCE": {"conf": 0.30, "min_len": 20, "require_entities": False},
}

# Content fragments that flag a memory as a failed extraction artifact
_ERROR_FRAGMENTS = [
    "ALL PROVIDERS FAILED",
    "reflection generation failed",
    "LLM call failed",
    "TopicBudgetExceeded",
    "error extracting",
]

# Dedup: fraction of shared words to consider near-duplicate
DEDUP_OVERLAP_THRESHOLD = 0.75
DEDUP_MIN_WORDS         = 6   # Only compare memories with at least this many words


@dataclass
class QualityResult:
    junk_deleted:  int = 0   # Memories deleted by hard/soft thresholds
    dedup_deleted: int = 0   # Memories deleted by near-duplicate detection

    def __str__(self) -> str:
        return f"QUALITY: junk_deleted={self.junk_deleted} dedup_deleted={self.dedup_deleted}"


def run_quality_prune(container_tag: str = "shard") -> QualityResult:
    """Run junk pruning + dedup on is_latest=1 memories for a given container.

    Safe to call from any context. Does NOT touch is_latest=0 memories
    (those are handled by PRUNE in episode_decay.py).

    Returns QualityResult with counts.
    """
    result = QualityResult()

    # ── 1. JUNK_PRUNE ──────────────────────────────────────────────────────────
    candidates = query(
        """SELECT id, content, memory_type, entities, confidence
           FROM memories
           WHERE is_latest=1 AND container_tag=?""",
        (container_tag,),
    )

    junk_ids: List[str] = []
    for mem in candidates:
        if _is_junk(mem):
            junk_ids.append(mem["id"])

    if junk_ids:
        placeholders = ",".join("?" * len(junk_ids))
        execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            tuple(junk_ids),
        )
        result.junk_deleted = len(junk_ids)
        logger.info("[QUALITY] Junk-pruned %d memories", result.junk_deleted)

    # ── 2. DEDUP ───────────────────────────────────────────────────────────────
    # Re-load after junk prune
    live = query(
        """SELECT id, content, confidence
           FROM memories
           WHERE is_latest=1 AND container_tag=?
           ORDER BY confidence DESC""",
        (container_tag,),
    )

    to_delete: Set[str] = set()
    for i, a in enumerate(live):
        if a["id"] in to_delete:
            continue
        words_a = _tokenize(a["content"])
        if len(words_a) < DEDUP_MIN_WORDS:
            continue
        set_a = set(words_a)

        for b in live[i + 1:]:
            if b["id"] in to_delete:
                continue
            words_b = _tokenize(b["content"])
            if len(words_b) < DEDUP_MIN_WORDS:
                continue

            overlap = len(set_a & set(words_b))
            union   = len(set_a | set(words_b))
            if union == 0:
                continue
            jaccard = overlap / union
            if jaccard >= DEDUP_OVERLAP_THRESHOLD:
                # Keep a (higher confidence, comes first in sorted list), delete b
                to_delete.add(b["id"])
                logger.debug(
                    "[QUALITY] Dedup: keep '%s...' (%.2f), drop '%s...' (%.2f) jaccard=%.2f",
                    a["content"][:40], a["confidence"],
                    b["content"][:40], b["confidence"],
                    jaccard,
                )

    if to_delete:
        placeholders = ",".join("?" * len(to_delete))
        execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            tuple(to_delete),
        )
        result.dedup_deleted = len(to_delete)
        logger.info("[QUALITY] Dedup-removed %d near-duplicate memories", result.dedup_deleted)

    return result


# ── Internal helpers ───────────────────────────────────────────────────────────

def _is_junk(mem: dict) -> bool:
    """Return True if the memory should be deleted."""
    content    = mem.get("content", "") or ""
    conf       = mem.get("confidence", 1.0) or 1.0
    mtype      = mem.get("memory_type", "FACT")
    entities_raw = mem.get("entities", "[]") or "[]"

    # Hard floor
    if conf < HARD_MIN_CONFIDENCE:
        return True
    if len(content.strip()) < HARD_MIN_CONTENT_LEN:
        return True

    # Error artifact check
    content_upper = content.upper()
    for frag in _ERROR_FRAGMENTS:
        if frag.upper() in content_upper:
            return True

    # Per-type soft thresholds
    thresh = _TYPE_THRESHOLDS.get(mtype, {"conf": 0.30, "min_len": 20, "require_entities": False})

    if conf < thresh["conf"]:
        return True
    if len(content.strip()) < thresh["min_len"]:
        return True

    if thresh["require_entities"]:
        try:
            entities = json.loads(entities_raw) if isinstance(entities_raw, str) else entities_raw
        except (json.JSONDecodeError, TypeError):
            entities = []
        if not entities:
            return True

    return False


def _tokenize(text: str) -> List[str]:
    """Lowercase word tokens, strip punctuation. Same logic as memory_extractor."""
    return re.findall(r"[a-z0-9]+", text.lower())


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))

    from shard_db import query as _q

    before = _q("SELECT COUNT(*) as n FROM memories WHERE is_latest=1", ())[0]["n"]
    print(f"Memories before: {before}")

    result = run_quality_prune()
    print(f"Junk deleted:  {result.junk_deleted}")
    print(f"Dedup removed: {result.dedup_deleted}")

    after = _q("SELECT COUNT(*) as n FROM memories WHERE is_latest=1", ())[0]["n"]
    print(f"Memories after: {after}  (removed {before - after})")

    # Stats by type
    rows = _q(
        """SELECT memory_type, COUNT(*) as n, ROUND(AVG(confidence),3) as avg_conf
           FROM memories WHERE is_latest=1 GROUP BY memory_type ORDER BY n DESC""",
        (),
    )
    print("\nBy type:")
    for r in rows:
        print(f"  {r['memory_type']:<12} n={r['n']:<6} avg_conf={r['avg_conf']}")
