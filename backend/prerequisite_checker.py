"""prerequisite_checker.py -- Prerequisite gating for SHARD topic selection.

Before studying a hard topic (sig_difficulty >= threshold), SHARD checks
whether the required foundational skills are already certified.

Two-layer strategy:
  1. GraphRAG -- query knowledge_graph for `depends_on` / `requires` relations
     already extracted during past SYNTHESIZE phases. Zero LLM cost.
  2. LLM fallback -- if GraphRAG returns nothing, ask Gemini/Groq for 1-2
     prerequisite topics. Results are cached in SQLite to avoid repeat calls.

Integration point: called from NightRunner._select_topic() after a topic is
chosen. If prerequisites are missing, they are pushed to the front of the
improvement queue and this function returns them so NightRunner studies them
first.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("shard.prereq")

# ── Tunables ──────────────────────────────────────────────────────────────────

DIFFICULTY_GATE    = 0.7   # only gate topics above this sig_difficulty
MAX_PREREQS        = 2     # max prerequisites to inject per topic
CACHE_TABLE        = "prerequisite_cache"


# ── Schema ────────────────────────────────────────────────────────────────────

def ensure_schema() -> None:
    """Create prerequisite_cache table if missing."""
    try:
        from shard_db import execute
        execute(f"""
            CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
                topic       TEXT PRIMARY KEY,
                prereqs     TEXT NOT NULL,   -- JSON array of strings
                source      TEXT,            -- 'graphrag' | 'llm'
                created_at  TEXT NOT NULL
            )
        """)
    except Exception as e:
        logger.debug("[PREREQ] Schema init failed: %s", e)


# ── Public API ────────────────────────────────────────────────────────────────

def get_missing_prerequisites(
    topic: str,
    capability_graph,
    sig_difficulty: float = 0.5,
) -> list[str]:
    """Return a list of prerequisite topics that SHARD has not yet certified.

    Returns [] if:
    - sig_difficulty < DIFFICULTY_GATE (easy topic -- no gating needed)
    - all prerequisites are already certified
    - no prerequisites found

    Returns up to MAX_PREREQS uncertified prerequisite topic strings.
    """
    if sig_difficulty < DIFFICULTY_GATE:
        return []

    certified = set(k.lower() for k in capability_graph.capabilities.keys())

    # Layer 1: GraphRAG
    prereqs = _from_graphrag(topic)

    # Layer 2: LLM fallback if GraphRAG found nothing
    if not prereqs:
        prereqs = _from_llm_cached(topic)

    if not prereqs:
        return []

    missing = [p for p in prereqs if p.lower() not in certified]
    logger.info(
        "[PREREQ] topic=%r  prereqs=%r  missing=%d/%d",
        topic, prereqs, len(missing), len(prereqs),
    )
    return missing[:MAX_PREREQS]


# ── Layer 1: GraphRAG ─────────────────────────────────────────────────────────

def _from_graphrag(topic: str) -> list[str]:
    """Query knowledge_graph for depends_on / requires relations."""
    try:
        from shard_db import query as db_query
        keyword = topic.lower().strip()
        words   = keyword.split()[:5]

        rows = db_query("""
            SELECT source_concept, target_concept, relation_type
            FROM knowledge_graph
            WHERE relation_type IN ('depends_on', 'requires')
              AND confidence >= 0.6
            LIMIT 100
        """)

        prereqs = []
        for row in rows:
            src = row["source_concept"]
            tgt = row["target_concept"]
            combined = f"{src} {tgt}".lower()
            if any(w in combined for w in words):
                # The topic appears as the dependent side -> tgt is the prereq
                if any(w in src for w in words):
                    prereqs.append(tgt)
                else:
                    prereqs.append(src)

        seen = set()
        unique = []
        for p in prereqs:
            if p not in seen and p.lower() != keyword:
                seen.add(p)
                unique.append(p)

        if unique:
            logger.debug("[PREREQ] GraphRAG found %d prereqs for %r: %r", len(unique), topic, unique)
        return unique[:MAX_PREREQS]

    except Exception as e:
        logger.debug("[PREREQ] GraphRAG query failed: %s", e)
        return []


# ── Layer 2: LLM (cached) ─────────────────────────────────────────────────────

def _from_llm_cached(topic: str) -> list[str]:
    """Ask LLM for prerequisites, cache result in SQLite."""
    import json
    from datetime import datetime

    try:
        from shard_db import query_one
        row = query_one(f"SELECT prereqs FROM {CACHE_TABLE} WHERE topic = ?", (topic,))
        if row:
            cached = json.loads(row["prereqs"])
            logger.debug("[PREREQ] Cache hit for %r: %r", topic, cached)
            return cached
    except Exception:
        pass

    # Cache miss -- call LLM
    prereqs = _ask_llm(topic)
    if prereqs:
        try:
            from shard_db import execute
            execute(
                f"INSERT OR REPLACE INTO {CACHE_TABLE} (topic, prereqs, source, created_at) VALUES (?, ?, ?, ?)",
                (topic, json.dumps(prereqs), "llm", datetime.now().isoformat()),
            )
        except Exception as e:
            logger.debug("[PREREQ] Cache write failed: %s", e)

    return prereqs


def _ask_llm(topic: str) -> list[str]:
    """Synchronous LLM call to identify 1-2 prerequisites for a topic."""
    import asyncio
    import json

    prompt = (
        f'What are the 1-2 most essential prerequisite topics a Python developer must know '
        f'before studying "{topic}"?\n\n'
        f'Rules:\n'
        f'- Each prerequisite must be a concrete technical topic (2-5 words)\n'
        f'- Python/programming context only\n'
        f'- Return ONLY a JSON array of strings, nothing else\n'
        f'- Example: ["python functions and scope", "basic data structures python"]\n'
        f'- If no prerequisites needed, return []'
    )

    async def _call():
        try:
            from llm_router import llm_complete
            raw = await llm_complete(
                prompt=prompt,
                system="You are a computer science curriculum designer. Output only valid JSON arrays.",
                max_tokens=150,
                temperature=0.1,
                providers=["Gemini", "Groq"],
            )
            text = raw.strip()
            start = text.find("[")
            end   = text.rfind("]") + 1
            if start == -1 or end == 0:
                return []
            data = json.loads(text[start:end])
            if not isinstance(data, list):
                return []
            return [str(p).strip() for p in data if isinstance(p, str) and len(p.split()) >= 2][:MAX_PREREQS]
        except Exception as e:
            logger.debug("[PREREQ] LLM call failed: %s", e)
            return []

    # Always run in a fresh thread to avoid event-loop conflicts.
    # Timeout is short (10s) -- if LLM is slow, skip prereq detection rather than block.
    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _call())
            return future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        logger.debug("[PREREQ] LLM timeout -- skipping prereq detection for this topic")
        return []
    except Exception as e:
        logger.debug("[PREREQ] async bridge failed: %s", e)
        return []


# Run schema migration on first import
try:
    ensure_schema()
except Exception:
    pass
