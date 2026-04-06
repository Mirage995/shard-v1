"""derivation_engine.py -- Infers new facts from existing memories.

The most novel piece of SHARD.MEMORY: takes a set of is_latest memories
and asks the LLM to infer new facts that are strongly implied but not
explicitly stated.

Examples:
  "SHARD certified asyncio.sleep() is non-blocking" +
  "SHARD certified threading is for CPU-bound tasks" →
  DERIVED: "For I/O-bound concurrent code, asyncio is preferred over threading"

  "SHARD failed asyncio 3 times" +
  "SHARD certified coroutines successfully" →
  DERIVED: "SHARD's asyncio gap is likely in event loop management, not coroutine syntax"

Derived memories:
  - get confidence * DERIVATION_PENALTY (default 0.8)
  - have source_type="derivation"
  - carry derived_from list in their source_ref
  - are stored as FACT or RELATION type only (never EPISODE)

Usage:
    engine = DerivationEngine(think_fn=agent._think_fast)
    new_memories = await engine.derive(container_tag="shard", limit=30)
    engine.save(new_memories)
"""
import json
import logging
from typing import Any, Callable, List, Optional

from memory_extractor import Memory, MemoryExtractor, _parse_memory_list
from shard_db import query

logger = logging.getLogger("shard.derivation_engine")

DERIVATION_CONFIDENCE_PENALTY = 0.8
MAX_SOURCE_MEMORIES            = 30   # Max memories to pass to LLM per derivation call
MAX_NEW_DERIVATIONS            = 5    # Max new facts per call

_SYSTEM_PROMPT = (
    "You are an inference engine for an AI learning system called SHARD. "
    "Your job is to find NEW facts that are STRONGLY IMPLIED by the known facts, "
    "but NOT explicitly stated. Be conservative — only high-confidence inferences. "
    "OUTPUT ONLY VALID JSON. No markdown, no backticks."
)

_DERIVATION_PROMPT = """\
Given these known facts about SHARD (an autonomous AI learning system):

{facts_block}

Infer NEW facts that are strongly implied but NOT explicitly stated.
Focus on:
- Patterns in what SHARD succeeds/fails at (e.g. "SHARD is stronger at parsing than concurrency")
- Gaps between certified skills and related uncertified ones
- Behavioral tendencies (e.g. "SHARD tends to over-engineer solutions at retry 2")
- Knowledge connections not yet explicit

Rules:
- Only infer facts with confidence > 0.6
- Do NOT restate existing facts
- Do NOT infer vague generalities
- Maximum {max_derivations} new facts
- Types: FACT or RELATION only (no EPISODE, no GOAL)

Return JSON array:
[
  {{
    "content": "...",
    "memory_type": "FACT|RELATION",
    "entities": ["entity1", "entity2"],
    "confidence": 0.0,
    "reasoning": "one sentence: why this is implied"
  }}
]
"""


class DerivationEngine:
    """Infers new typed memories from existing ones via LLM reasoning.

    Args:
        think_fn: Async callable ``(prompt, system, json_mode) -> str``.
    """

    def __init__(self, think_fn: Optional[Callable[..., Any]] = None):
        self._think    = think_fn
        self._extractor = MemoryExtractor(think_fn=think_fn)

    # ── Public API ────────────────────────────────────────────────────────────

    async def derive(
        self,
        container_tag: str = "shard",
        memory_types:  Optional[List[str]] = None,
        limit:         int = MAX_SOURCE_MEMORIES,
    ) -> List[Memory]:
        """Run one derivation pass on existing memories.

        Args:
            container_tag: Which memory container to use.
            memory_types:  Filter source memories by type (default: all).
            limit:         Max source memories to pass to LLM.

        Returns:
            List of new derived Memory objects (not yet saved).
        """
        if not self._think:
            return []

        # Load recent is_latest memories
        source_memories = self._load_source(container_tag, memory_types, limit)
        if len(source_memories) < 3:
            logger.info("[DERIVATION] Not enough source memories (%d) — skipping", len(source_memories))
            return []

        facts_block = _format_facts(source_memories)
        source_ids  = [m["id"] for m in source_memories]

        prompt = _DERIVATION_PROMPT.format(
            facts_block=facts_block,
            max_derivations=MAX_NEW_DERIVATIONS,
        )

        try:
            raw = await self._think(prompt, _SYSTEM_PROMPT, json_mode=True)
        except Exception as exc:
            logger.warning("[DERIVATION] LLM call failed: %s", exc)
            return []

        raw_list = _parse_memory_list(raw)
        if not raw_list:
            logger.info("[DERIVATION] No new derivations found")
            return []

        # Filter: FACT or RELATION only, apply confidence penalty
        derived: List[Memory] = []
        for item in raw_list:
            if item["memory_type"] not in ("FACT", "RELATION"):
                continue
            # Skip if content is too similar to an existing memory
            if self._is_redundant(item["content"], source_memories):
                logger.debug("[DERIVATION] Skipped redundant: %s", item["content"][:60])
                continue

            penalized_conf = round(item["confidence"] * DERIVATION_CONFIDENCE_PENALTY, 3)
            reasoning = item.pop("reasoning", "")  # not stored in Memory dataclass

            derived.append(Memory(
                content=item["content"],
                memory_type=item["memory_type"],
                entities=item.get("entities", []),
                confidence=penalized_conf,
                source_type="derivation",
                source_ref=json.dumps(source_ids[:5]),  # store first 5 source IDs
                container_tag=container_tag,
            ))
            if reasoning:
                logger.debug(
                    "[DERIVATION] New %s (%.2f): %s | reason: %s",
                    item["memory_type"], penalized_conf,
                    item["content"][:70], reasoning[:80],
                )

        logger.info(
            "[DERIVATION] Derived %d new memories from %d source memories",
            len(derived), len(source_memories),
        )
        return derived

    def save(self, memories: List[Memory]) -> int:
        """Store derived memories. Delegates to MemoryExtractor.save()."""
        return self._extractor.save(memories)

    async def derive_and_save(
        self,
        container_tag: str = "shard",
        limit:         int = MAX_SOURCE_MEMORIES,
    ) -> int:
        """Convenience: derive + save in one call. Returns count saved."""
        new_memories = await self.derive(container_tag=container_tag, limit=limit)
        if not new_memories:
            return 0
        return self.save(new_memories)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _load_source(
        container_tag: str,
        memory_types:  Optional[List[str]],
        limit:         int,
    ) -> List[dict]:
        """Load diverse source memories for derivation."""
        if memory_types:
            placeholders = ",".join("?" * len(memory_types))
            return query(
                f"""SELECT id, content, memory_type, entities, confidence
                    FROM memories
                    WHERE is_latest=1 AND container_tag=?
                    AND memory_type IN ({placeholders})
                    AND confidence >= 0.5
                    ORDER BY created_at DESC LIMIT ?""",
                (container_tag, *memory_types, limit),
            )
        return query(
            """SELECT id, content, memory_type, entities, confidence
               FROM memories
               WHERE is_latest=1 AND container_tag=?
               AND confidence >= 0.5
               ORDER BY created_at DESC LIMIT ?""",
            (container_tag, limit),
        )

    @staticmethod
    def _is_redundant(new_content: str, existing: List[dict], threshold: int = 5) -> bool:
        """Simple word-overlap check to avoid re-deriving existing facts."""
        from memory_extractor import _tokenize
        new_words = set(_tokenize(new_content))
        if len(new_words) < 3:
            return False
        for mem in existing:
            existing_words = set(_tokenize(mem.get("content", "")))
            overlap = len(new_words & existing_words)
            if overlap >= threshold:
                return True
        return False


# ── Module-level helpers ───────────────────────────────────────────────────────

def _format_facts(memories: List[dict]) -> str:
    """Format memories as a numbered list for the prompt."""
    lines = []
    for i, m in enumerate(memories, 1):
        mtype = m.get("memory_type", "FACT")
        conf  = m.get("confidence", 1.0)
        lines.append(
            f"{i}. [{mtype}] ({conf:.2f}) {m.get('content', '')}"
        )
    return "\n".join(lines)
