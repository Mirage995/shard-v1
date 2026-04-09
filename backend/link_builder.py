"""link_builder.py -- Cross-reference graph for the memories table.

Builds bidirectional entity-overlap links between memories stored in shard.db.
Called automatically after each MemoryExtractor.save() to wire new memories
into the existing knowledge graph.

Links are stored in the `memory_links` table (schema v7):
    source_id, target_id, link_type, weight (= shared entity count), created_at

Design decisions:
- Threshold:  overlap >= 1 required; weight encodes strength (query-time filtering)
- Self-links:  skipped (source_id == target_id)
- Duplicates:  ON CONFLICT DO NOTHING via PK (source_id, target_id)
- Bidirectional: both (A→B) and (B→A) inserted so queries on either end work
- Intra-topic:  allowed — two memories on the same topic can also be linked

Usage:
    # Called internally by MemoryExtractor.save()
    MemoryLinkBuilder.build_links(memory, container_tag)

    # Query
    links = MemoryLinkBuilder.get_linked(memory_id, min_weight=1)
    cross  = MemoryLinkBuilder.get_cross_topic_links(topic, min_weight=2)
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from shard_db import execute, executemany, query

logger = logging.getLogger("shard.link_builder")


class MemoryLinkBuilder:
    """Builds and queries cross-reference links between memories."""

    # Minimum shared-entity count required to create a link.
    # Keeping it at 1 preserves all information; callers can filter by weight.
    MIN_OVERLAP: int = 1

    # How many candidate memories to scan per new memory (performance guard).
    CANDIDATE_LIMIT: int = 200

    # Max outgoing links per node — prevents high-degree "python" hubs.
    # New links are only inserted if the node has fewer than this many already.
    MAX_LINKS_PER_NODE: int = 20

    # ── Build API ─────────────────────────────────────────────────────────────

    @classmethod
    def build_links(
        cls,
        memory_id: str,
        entities: List[str],
        container_tag: str = "shard",
    ) -> int:
        """Find existing memories that share entities with this one and link them.

        Args:
            memory_id:     ID of the newly saved memory.
            entities:      Entity list from the new memory.
            container_tag: Scope filter.

        Returns:
            Number of new link pairs inserted (each pair = 2 rows).
        """
        if not entities:
            return 0

        new_ent_set = {e.lower().strip() for e in entities if e.strip()}
        if not new_ent_set:
            return 0

        # Look up memory_type of the new memory for failure-failure boost
        new_type_rows = query(
            "SELECT memory_type FROM memories WHERE id=? LIMIT 1",
            (memory_id,),
        )
        new_is_failure = (
            new_type_rows[0]["memory_type"] == "EPISODE_FAILURE"
            if new_type_rows else False
        )

        # Load recent is_latest memories from same container (excluding self)
        candidates = query(
            """SELECT id, entities, memory_type
               FROM memories
               WHERE is_latest = 1
               AND container_tag = ?
               AND id != ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (container_tag, memory_id, cls.CANDIDATE_LIMIT),
        )

        rows: List[tuple] = []
        now = datetime.now().isoformat()

        for cand in candidates:
            try:
                cand_entities = json.loads(cand.get("entities") or "[]")
            except (json.JSONDecodeError, TypeError):
                continue

            cand_ent_set = {e.lower().strip() for e in cand_entities if e.strip()}
            shared = new_ent_set & cand_ent_set
            overlap = len(shared)

            if overlap < cls.MIN_OVERLAP:
                continue

            # Failure-failure boost: two failure memories on same topic cluster tighter
            both_are_failures = new_is_failure and cand.get("memory_type") == "EPISODE_FAILURE"
            weight = float(overlap) + (1.0 if both_are_failures else 0.0)

            # Bidirectional: both directions, ON CONFLICT DO NOTHING via PK
            rows.append((memory_id, cand["id"], "entity_overlap", weight, now))
            rows.append((cand["id"], memory_id, "entity_overlap", weight, now))

        if not rows:
            return 0

        # Degree cap: don't insert if this node already has MAX_LINKS_PER_NODE links.
        # Check current degree first (one cheap COUNT query).
        cur_degree_rows = query(
            "SELECT COUNT(*) as n FROM memory_links WHERE source_id = ?",
            (memory_id,),
        )
        cur_degree = cur_degree_rows[0]["n"] if cur_degree_rows else 0
        if cur_degree >= cls.MAX_LINKS_PER_NODE:
            # Keep only the highest-weight pairs not already present
            rows.sort(key=lambda r: -r[3])  # sort by weight desc
            cap_budget = cls.MAX_LINKS_PER_NODE - cur_degree
            if cap_budget <= 0:
                logger.debug("[LINKS] Degree cap reached for %s — skipping", memory_id[:8])
                return 0
            # Keep both directions for each pair; cap_budget counts pairs
            rows = rows[: cap_budget * 2]

        executemany(
            """INSERT OR IGNORE INTO memory_links
               (source_id, target_id, link_type, weight, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )

        pairs = len(rows) // 2
        if pairs:
            logger.debug("[LINKS] Built %d link pair(s) for memory %s", pairs, memory_id[:8])
        return pairs

    # ── Query API ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_linked(
        memory_id: str,
        min_weight: float = 1.0,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return memories directly linked to a given memory ID.

        Args:
            memory_id:  Source memory ID.
            min_weight: Minimum shared-entity count (default 1 = all links).
            limit:      Max results.

        Returns:
            List of dicts: {id, content, memory_type, entities, confidence, weight, source_ref}
        """
        return query(
            """SELECT m.id, m.content, m.memory_type, m.entities,
                      m.confidence, m.source_ref, ml.weight
               FROM memory_links ml
               JOIN memories m ON ml.target_id = m.id
               WHERE ml.source_id = ?
               AND ml.weight >= ?
               AND m.is_latest = 1
               ORDER BY ml.weight DESC, m.confidence DESC
               LIMIT ?""",
            (memory_id, min_weight, limit),
        )

    @staticmethod
    def get_cross_topic_links(
        topic: str,
        min_weight: float = 1.0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return memories from OTHER topics that are linked to any memory of this topic.

        This is the "tunnel" pattern from MemPalace: cross-topic knowledge connections.

        Args:
            topic:      source_ref of the topic whose memories we're checking.
            min_weight: Minimum shared-entity count.
            limit:      Max results.

        Returns:
            List of dicts with {id, content, memory_type, source_ref, weight, confidence}
        """
        return query(
            """SELECT m2.id, m2.content, m2.memory_type,
                      m2.source_ref, m2.confidence, ml.weight
               FROM memories m1
               JOIN memory_links ml ON ml.source_id = m1.id
               JOIN memories m2    ON ml.target_id  = m2.id
               WHERE m1.source_ref = ?
               AND m2.source_ref  != ?
               AND ml.weight >= ?
               AND m1.is_latest = 1
               AND m2.is_latest = 1
               ORDER BY ml.weight DESC, m2.confidence DESC
               LIMIT ?""",
            (topic, topic, min_weight, limit),
        )

    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """Return link graph statistics."""
        total = query("SELECT COUNT(*) as n FROM memory_links", ())[0]["n"]
        strong = query(
            "SELECT COUNT(*) as n FROM memory_links WHERE weight >= 2", ()
        )[0]["n"]
        avg_w = query(
            "SELECT AVG(weight) as w FROM memory_links", ()
        )[0]["w"] or 0.0
        return {
            "total_links": total,
            "strong_links": strong,
            "avg_weight": round(avg_w, 2),
        }
