"""affordance_filter.py -- Affordance-based topic feasibility gating for SHARD.

Complementary to prerequisite_checker (which gates hard topics >= 0.7 difficulty),
this module gates medium-difficulty topics that exceed SHARD's current concept
coverage. If SHARD knows less than FEASIBILITY_THRESHOLD of the concepts a topic
requires, the topic is decomposed into 2-3 simpler sub-topics.

Algorithm:
  Step 1 -- Feasibility score (zero LLM)
    feasibility = |topic_tokens ∩ certified_concept_tokens| / |topic_tokens|
    - Topic with no certified-concept data → 0.5 (neutral, let it through)
    - Tokens: meaningful words in the topic + in certified capability names

  Step 2 -- Decomposition (1 LLM call, cached, only if infeasible)
    "Split this topic into 2-3 simpler sub-topics that build toward it step-by-step."

  Step 3 -- Integration
    Sub-topics enqueued in improvement_queue; caller studies the first one.

Integration point: NightRunner main loop, after the prerequisite gate.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("shard.afford")

# ── Tunables ──────────────────────────────────────────────────────────────────

FEASIBILITY_THRESHOLD = 0.35   # below this → decompose
CACHE_TABLE           = "affordance_cache"
MAX_SUB_TOPICS        = 3

# Words that carry no semantic weight for overlap matching
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
    "with", "by", "from", "is", "are", "be", "as", "it", "its",
    "python", "advanced", "basic", "introduction", "overview", "fundamentals",
})


# ── Public result type ────────────────────────────────────────────────────────

@dataclass
class AffordanceResult:
    feasible:    bool
    feasibility: float
    sub_topics:  list[str] = field(default_factory=list)


# ── Schema ────────────────────────────────────────────────────────────────────

def ensure_schema() -> None:
    try:
        from shard_db import execute
        execute(f"""
            CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
                topic       TEXT PRIMARY KEY,
                sub_topics  TEXT NOT NULL,   -- JSON array of strings
                created_at  TEXT NOT NULL
            )
        """)
    except Exception as e:
        logger.debug("[AFFORD] Schema init failed: %s", e)


# ── Public API ────────────────────────────────────────────────────────────────

def check_affordance(topic: str, capability_graph) -> AffordanceResult:
    """Return an AffordanceResult for *topic* given current certified capabilities.

    This is synchronous and safe to call from the NightRunner main loop.
    """
    certified_keys = set(capability_graph.capabilities.keys())

    # Fresh system with no certified capabilities: neutral pass-through
    if not certified_keys:
        return AffordanceResult(feasible=True, feasibility=0.5)

    feasibility = _compute_feasibility(topic, certified_keys)

    if feasibility >= FEASIBILITY_THRESHOLD:
        return AffordanceResult(feasible=True, feasibility=feasibility)

    # Below threshold: attempt decomposition
    sub_topics = _decompose_cached(topic)
    return AffordanceResult(feasible=False, feasibility=feasibility, sub_topics=sub_topics)


# ── Step 1: feasibility (zero LLM) ───────────────────────────────────────────

def _meaningful_tokens(text: str) -> list[str]:
    """Split *text* into lowercase tokens, dropping stopwords and short words."""
    raw = text.lower().replace("-", " ").replace("_", " ").split()
    return [t for t in raw if t not in _STOPWORDS and len(t) >= 3]


def _compute_feasibility(topic: str, certified_keys: set[str]) -> float:
    """Return fraction of topic tokens covered by certified capability names."""
    topic_tokens = _meaningful_tokens(topic)
    if not topic_tokens:
        return 0.5  # degenerate topic → neutral

    # Build a flat token pool from all certified capability names
    cert_token_pool: set[str] = set()
    for key in certified_keys:
        cert_token_pool.update(_meaningful_tokens(key))

    matched = sum(1 for t in topic_tokens if t in cert_token_pool)
    score = matched / len(topic_tokens)

    logger.debug(
        "[AFFORD] topic=%r  tokens=%r  matched=%d/%d  feasibility=%.2f",
        topic, topic_tokens, matched, len(topic_tokens), score,
    )
    return round(score, 3)


# ── Step 2: decomposition (1 LLM call, cached) ───────────────────────────────

def _decompose_cached(topic: str) -> list[str]:
    """Return cached or freshly generated sub-topics for *topic*."""
    try:
        from shard_db import query_one
        row = query_one(f"SELECT sub_topics FROM {CACHE_TABLE} WHERE topic = ?", (topic,))
        if row:
            cached = json.loads(row["sub_topics"])
            logger.debug("[AFFORD] Cache hit for %r: %r", topic, cached)
            return cached
    except Exception:
        pass

    sub_topics = _ask_llm_decompose(topic)

    if sub_topics:
        try:
            from datetime import datetime
            from shard_db import execute
            execute(
                f"INSERT OR REPLACE INTO {CACHE_TABLE} (topic, sub_topics, created_at) VALUES (?, ?, ?)",
                (topic, json.dumps(sub_topics), datetime.now().isoformat()),
            )
        except Exception as e:
            logger.debug("[AFFORD] Cache write failed: %s", e)

    return sub_topics


def _ask_llm_decompose(topic: str) -> list[str]:
    """Synchronous LLM call: decompose *topic* into 2-3 simpler sub-topics."""
    import asyncio
    import concurrent.futures

    from constants import PROVIDERS_PRIMARY

    prompt = (
        f'The topic "{topic}" is too broad or advanced to study directly.\n\n'
        f'Break it down into 2-3 simpler sub-topics that build the necessary skills '
        f'step-by-step toward mastering it.\n\n'
        f'Rules:\n'
        f'- Each sub-topic must be a concrete technical topic (2-6 words)\n'
        f'- Python/programming context only\n'
        f'- Order from simplest to most advanced\n'
        f'- Return ONLY a JSON array of strings, nothing else\n'
        f'- Example: ["asyncio task groups", "asyncio cancellation patterns", '
        f'"asyncio supervisor trees"]\n'
    )

    async def _call() -> list[str]:
        try:
            from llm_router import llm_complete
            raw = await llm_complete(
                prompt=prompt,
                system="You are a computer science curriculum designer. Output only valid JSON arrays.",
                max_tokens=150,
                temperature=0.1,
                providers=PROVIDERS_PRIMARY,
            )
            text  = raw.strip()
            start = text.find("[")
            end   = text.rfind("]") + 1
            if start == -1 or end == 0:
                return []
            data = json.loads(text[start:end])
            if not isinstance(data, list):
                return []
            return [
                str(s).strip() for s in data
                if isinstance(s, str) and 2 <= len(s.split()) <= 8
            ][:MAX_SUB_TOPICS]
        except Exception as e:
            logger.debug("[AFFORD] LLM decompose failed: %s", e)
            return []

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _call())
            return future.result(timeout=12)
    except concurrent.futures.TimeoutError:
        logger.debug("[AFFORD] LLM timeout -- skipping decomposition for %r", topic)
        return []
    except Exception as e:
        logger.debug("[AFFORD] async bridge failed: %s", e)
        return []


# Run schema migration on first import
try:
    ensure_schema()
except Exception:
    pass
