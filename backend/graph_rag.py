"""graph_rag.py -- GraphRAG: causal knowledge graph over SQLite.

During SYNTHESIZE, SHARD extracts causal relations between concepts and saves them.
During MAP/BENCHMARK, SHARD can query these relations to inject warnings.

Example:
  "asyncio -> threading: causes_conflict -- Using Thread with asyncio causes race conditions"

This transforms SHARD from "student who studied" to "senior with experience".
"""
import json
import logging
from datetime import datetime
from typing import Optional

from constants import PROVIDERS_PRIMARY

logger = logging.getLogger("shard.graph_rag")

_VALID_RELATION_TYPES = {
    "causes_conflict", "depends_on", "replaces", "improves", "breaks",
    "extends", "requires", "incompatible_with",
}


# ── Schema migration (run once on first import) ───────────────────────────────

def ensure_schema():
    """Create knowledge_graph table if it doesn't exist (migration-safe)."""
    try:
        from shard_db import execute
        execute("""
            CREATE TABLE IF NOT EXISTS knowledge_graph (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source_concept  TEXT    NOT NULL,
                target_concept  TEXT    NOT NULL,
                relation_type   TEXT    NOT NULL,
                confidence      REAL    DEFAULT 0.7,
                context         TEXT,
                topic_origin    TEXT,
                created_at      TEXT    NOT NULL
            )
        """)
        execute("CREATE INDEX IF NOT EXISTS idx_kg_source ON knowledge_graph(source_concept)")
        execute("CREATE INDEX IF NOT EXISTS idx_kg_target ON knowledge_graph(target_concept)")
        execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_pair
            ON knowledge_graph(source_concept, target_concept, relation_type)
        """)
    except Exception as e:
        logger.warning("[GRAPH_RAG] Schema init failed: %s", e)


# ── Extraction (called during SYNTHESIZE) ─────────────────────────────────────

async def extract_and_store_relations(
    topic: str,
    concepts: list[dict],
    raw_text: str,
) -> int:
    """Extract causal relations from concepts + raw text, store in SQLite.

    Returns number of new relations stored.
    """
    if not concepts or len(concepts) < 2:
        return 0

    concept_names = [c.get("name", "") for c in concepts if c.get("name")]
    if len(concept_names) < 2:
        return 0

    # Build lightweight prompt -- only concept names + snippet of raw text
    names_str = ", ".join(concept_names[:20])
    snippet = raw_text[:3000] if raw_text else ""

    prompt = f"""Analyze the following concepts from a study on "{topic}" and identify CAUSAL relations between them.

Concepts: {names_str}

Text snippet:
{snippet}

Respond ONLY with a JSON array of objects. Each object must have:
- "source": concept name (from the list above)
- "target": concept name (from the list above)
- "relation_type": one of: causes_conflict, depends_on, replaces, improves, breaks, extends, requires, incompatible_with
- "confidence": float 0.0-1.0
- "context": brief explanation (max 100 chars)

Return [] if no clear causal relations exist.
Example: [{{"source": "asyncio", "target": "threading", "relation_type": "causes_conflict", "confidence": 0.9, "context": "Mixing asyncio with raw threads causes race conditions"}}]"""

    try:
        from llm_router import llm_complete
        raw_json = await llm_complete(
            prompt=prompt,
            system="You are a knowledge graph extractor. Output only valid JSON arrays, nothing else.",
            max_tokens=1000,
            temperature=0.1,
            providers=PROVIDERS_PRIMARY,
        )

        # Parse response
        relations = _parse_relations(raw_json)
        if not relations:
            return 0

        # Store in SQLite
        stored = _store_relations(relations, topic)
        logger.info("[GRAPH_RAG] Stored %d new causal relations for topic: %s", stored, topic)
        return stored

    except Exception as e:
        logger.warning("[GRAPH_RAG] Extraction failed: %s", e)
        return 0


def _parse_relations(raw: str) -> list[dict]:
    """Parse LLM response into validated relation dicts."""
    try:
        # Strip markdown fences
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Find JSON array
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            return []

        data = json.loads(text[start:end])
        if not isinstance(data, list):
            return []

        valid = []
        for item in data:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip().lower()
            target = str(item.get("target", "")).strip().lower()
            rtype  = str(item.get("relation_type", "")).strip().lower()
            if not source or not target or source == target:
                continue
            if rtype not in _VALID_RELATION_TYPES:
                continue
            valid.append({
                "source": source,
                "target": target,
                "relation_type": rtype,
                "confidence": float(item.get("confidence", 0.7)),
                "context": str(item.get("context", ""))[:200],
            })
        return valid

    except Exception:
        return []


def _store_relations(relations: list[dict], topic: str) -> int:
    """Insert relations into SQLite, skip duplicates. Returns count inserted."""
    try:
        from shard_db import execute
        now = datetime.now().isoformat()
        count = 0
        for r in relations:
            try:
                execute("""
                    INSERT OR IGNORE INTO knowledge_graph
                        (source_concept, target_concept, relation_type,
                         confidence, context, topic_origin, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["source"], r["target"], r["relation_type"],
                    r["confidence"], r["context"], topic, now,
                ))
                count += 1
            except Exception as e:
                logger.debug("[GRAPH_RAG] Insert skip: %s", e)
        return count
    except Exception as e:
        logger.warning("[GRAPH_RAG] Store failed: %s", e)
        return 0


# ── Query (called during MAP or benchmark context injection) ──────────────────

def query_causal_context(topic_or_concept: str, max_hops: int = 2) -> str:
    """Return causal warnings relevant to a topic.

    Returns a formatted string ready to inject into prompts, or "" if nothing found.
    """
    try:
        from shard_db import query as db_query

        # Normalize: search by substring match on source/target
        keyword = topic_or_concept.lower().strip()
        words = keyword.split()[:5]  # max 5 words for matching

        rows = db_query("""
            SELECT source_concept, target_concept, relation_type, context, confidence
            FROM knowledge_graph
            WHERE confidence >= 0.6
              AND (verified_status IS NULL OR verified_status != 'disputed')
            ORDER BY confidence DESC
            LIMIT 50
        """)

        if not rows:
            return ""

        # Filter rows that mention any keyword word
        relevant = []
        for row in rows:
            combined = f"{row['source_concept']} {row['target_concept']} {row['context'] or ''}".lower()
            if any(w in combined for w in words):
                relevant.append(row)

        if not relevant:
            return ""

        lines = ["[WARN]️  CAUSAL KNOWLEDGE (from previous studies):"]
        for r in relevant[:8]:
            rel_icon = {
                "causes_conflict": "⚡",
                "breaks": "[!]",
                "incompatible_with": "🚫",
                "depends_on": "🔗",
                "requires": "🔗",
                "replaces": "↩️",
                "improves": "✅",
                "extends": "➕",
            }.get(r["relation_type"], "->")
            lines.append(
                f"  {rel_icon} {r['source_concept']} {r['relation_type'].replace('_', ' ')} "
                f"{r['target_concept']}: {r['context'] or ''}"
            )

        return "\n".join(lines)

    except Exception as e:
        logger.warning("[GRAPH_RAG] Query failed: %s", e)
        return ""


def get_related_topics(topic: str, relation_types: list[str] | None = None, limit: int = 5) -> list[str]:
    """Return target concepts related to `topic` via the given relation types.

    Used by desire_engine to find adjacent unexplored topics for curiosity propagation.
    Defaults to 'extends' and 'improves' -- the forward-learning relations.
    """
    if relation_types is None:
        relation_types = ["extends", "improves"]
    try:
        from shard_db import query as db_query
        keyword = topic.lower().strip()
        words = keyword.split()[:5]
        placeholders = ",".join("?" * len(relation_types))
        rows = db_query(
            f"""
            SELECT target_concept
            FROM knowledge_graph
            WHERE relation_type IN ({placeholders})
              AND confidence >= 0.6
              AND (verified_status IS NULL OR verified_status != 'disputed')
            ORDER BY confidence DESC
            LIMIT 100
            """,
            tuple(relation_types),
        )
        results = []
        for r in rows:
            src_matches = any(
                w in topic.lower()
                for w in r["target_concept"].lower().split()[:5]
            )
            # Match rows where source_concept mentions our topic keywords
            if src_matches:
                results.append(r["target_concept"])
                if len(results) >= limit:
                    break

        # Fallback: also include rows where source_concept contains topic keywords
        if not results:
            rows2 = db_query(
                f"""
                SELECT source_concept, target_concept
                FROM knowledge_graph
                WHERE relation_type IN ({placeholders})
                  AND confidence >= 0.6
                  AND (verified_status IS NULL OR verified_status != 'disputed')
                ORDER BY confidence DESC
                LIMIT 100
                """,
                tuple(relation_types),
            )
            for r in rows2:
                combined = f"{r['source_concept']}".lower()
                if any(w in combined for w in words):
                    results.append(r["target_concept"])
                    if len(results) >= limit:
                        break

        return list(dict.fromkeys(results))  # deduplicate, preserve order
    except Exception:
        return []


def count_causal_hits(topic_or_concept: str) -> int:
    """Return the number of causal relations relevant to a topic.

    Same matching logic as query_causal_context but returns a count (int).
    Used by NightRunner to populate sig_graphrag in activation_log.
    """
    try:
        from shard_db import query as db_query
        keyword = topic_or_concept.lower().strip()
        words = keyword.split()[:5]
        rows = db_query("""
            SELECT source_concept, target_concept, context
            FROM knowledge_graph
            WHERE confidence >= 0.6
              AND (verified_status IS NULL OR verified_status != 'disputed')
            LIMIT 50
        """)
        return sum(
            1 for r in rows
            if any(
                w in f"{r['source_concept']} {r['target_concept']} {r.get('context') or ''}".lower()
                for w in words
            )
        )
    except Exception:
        return 0


def get_graph_stats() -> dict:
    """Stats for /health endpoint."""
    try:
        from shard_db import query as db_query
        rows = db_query("""
            SELECT relation_type, COUNT(*) as cnt
            FROM knowledge_graph
            GROUP BY relation_type
            ORDER BY cnt DESC
        """)
        total_row = db_query("SELECT COUNT(*) as total FROM knowledge_graph")
        total = total_row[0]["total"] if total_row else 0
        return {
            "total_relations": total,
            "by_type": {r["relation_type"]: r["cnt"] for r in rows},
        }
    except Exception:
        return {"total_relations": 0, "by_type": {}}


def get_epistemic_profile(topic: str) -> dict:
    """Return epistemic quality metrics for a topic's causal subgraph.

    freshness = (verified*1.0 + untested*0.6 + unsure*0.3) / total
    Only counts relations with confidence >= 0.6 that are not disputed.
    """
    try:
        from shard_db import query as db_query
        keyword = topic.lower().strip()
        rows = db_query("""
            SELECT verified_status
            FROM knowledge_graph
            WHERE confidence >= 0.6
              AND (verified_status IS NULL OR verified_status != 'disputed')
              AND (
                  LOWER(source_concept) LIKE ?
                  OR LOWER(target_concept) LIKE ?
                  OR LOWER(topic_origin) = ?
              )
        """, (f"%{keyword}%", f"%{keyword}%", keyword))

        total = len(rows)
        if total == 0:
            return {"freshness": 1.0, "status": "unknown", "total": 0,
                    "verified": 0, "unsure": 0, "untested": 0}

        verified = sum(1 for r in rows if r["verified_status"] == "verified")
        unsure   = sum(1 for r in rows if r["verified_status"] == "unsure")
        untested = sum(1 for r in rows if r["verified_status"] is None)

        freshness = (verified * 1.0 + untested * 0.6 + unsure * 0.3) / total

        if freshness >= 0.7:
            status = "strong"
        elif freshness >= 0.5:
            status = "moderate"
        else:
            status = "weak"

        return {
            "freshness": round(freshness, 3),
            "status": status,
            "total": total,
            "verified": verified,
            "unsure": unsure,
            "untested": untested,
        }
    except Exception:
        return {"freshness": 1.0, "status": "unknown", "total": 0,
                "verified": 0, "unsure": 0, "untested": 0}


_VALIDATION_TIER_WEIGHT: dict = {
    "code_runs":           (0.20, "verified_provisional"),
    "sandbox_replicated":  (0.35, "verified_provisional"),
    "gpu_replicated":      (0.75, "verified"),
    "benchmark_validated": (0.85, "verified"),
    "external_replicated": (0.90, "verified"),
}


def insert_verified_relation(
    source_concept: str,
    target_concept: str,
    relation_type: str,
    context: str,
    verified_status: str,
    confidence: float = 0.9,
    topic_origin: str = "",
    experiment_id: str = "",
    validation_tier: Optional[str] = None,
) -> bool:
    """Upsert a causally verified (or refuted) relation into knowledge_graph.

    Uses ON CONFLICT DO UPDATE so duplicate triples are updated in-place.
    Requires the UNIQUE INDEX idx_kg_pair on (source_concept, target_concept, relation_type).

    If validation_tier is provided and the relation is being marked "verified",
    the tier overrides both confidence and verified_status according to
    _VALIDATION_TIER_WEIGHT. Refuted relations keep caller-supplied values.
    """
    # Apply tier-based confidence/status override for verified (CONFIRMED) results.
    if validation_tier and verified_status in ("verified", "verified_provisional"):
        tier_conf, tier_status = _VALIDATION_TIER_WEIGHT.get(
            validation_tier, (confidence, verified_status)
        )
        confidence      = tier_conf
        verified_status = tier_status

    try:
        from shard_db import execute
        execute("""
            INSERT INTO knowledge_graph
                (source_concept, target_concept, relation_type, context,
                 confidence, verified_status, topic_origin, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(source_concept, target_concept, relation_type) DO UPDATE SET
                context         = excluded.context,
                confidence      = excluded.confidence,
                verified_status = excluded.verified_status,
                topic_origin    = excluded.topic_origin,
                created_at      = datetime('now')
        """, (source_concept, target_concept, relation_type,
              context, confidence, verified_status, topic_origin))
        logger.info(
            "[GRAPH_RAG] insert_verified_relation: %s → %s (%s) [%s] experiment=%s",
            source_concept, target_concept, relation_type, verified_status, experiment_id,
        )
        return True
    except Exception as e:
        logger.warning("[GRAPH_RAG] insert_verified_relation failed: %s", e)
        return False


# Run schema migration on first import
try:
    ensure_schema()
except Exception:
    pass
