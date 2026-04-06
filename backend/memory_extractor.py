"""memory_extractor.py -- Typed memory extraction from any text source.

Converts free-form content (study synthesis, session logs, free text) into
structured Memory objects stored in the `memories` table of shard.db.

Memory types:
  FACT        Stable factual knowledge ("asyncio.sleep() is non-blocking")
  PREFERENCE  Behavioral preference ("SHARD prefers Groq for fast inference")
  EPISODE     Time-bound event ("SHARD failed asyncio 3 times in session SSJ26")
  GOAL        Active objective ("Build cross-task transfer layer #22")
  RELATION    Relationship between entities ("asyncio supersedes time.sleep in async")

Usage:
    extractor = MemoryExtractor(think_fn=agent._think_fast)
    memories = await extractor.extract_from_study(topic, structured, score)
    extractor.save(memories)
"""
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from shard_db import execute, executemany, query

logger = logging.getLogger("shard.memory_extractor")

# ── Memory types ──────────────────────────────────────────────────────────────

MEMORY_TYPES = {"FACT", "PREFERENCE", "EPISODE", "GOAL", "RELATION"}

# Episodes expire after 30 days by default (can be overridden)
EPISODE_TTL_DAYS = 30

# Derivation penalty: derived memories get confidence * this factor
DERIVATION_CONFIDENCE_PENALTY = 0.8

_SYSTEM_PROMPT = (
    "You are a memory extraction engine for an autonomous AI learning system called SHARD. "
    "Your job is to extract discrete, precise facts from content. "
    "Be conservative: extract only real, non-obvious facts. "
    "Do NOT extract generic truisms (e.g. 'Python is a programming language'). "
    "OUTPUT ONLY VALID JSON. No markdown, no backticks."
)

_STUDY_EXTRACTION_PROMPT = """\
SHARD just certified a topic. Extract the most important discrete memories from this synthesis.

TOPIC: {topic}
SCORE: {score}/10
CERTIFIED: {certified}

SYNTHESIZED KNOWLEDGE:
{knowledge_text}

Extract 3-7 memories. For each memory:
- content: the fact in 1 sentence, precise and actionable
- memory_type: FACT | PREFERENCE | EPISODE | GOAL | RELATION
- entities: named entities involved (list of strings)
- confidence: 0.0-1.0

Rules:
- FACT: timeless technical knowledge (e.g. "asyncio.sleep() is non-blocking")
- PREFERENCE: what SHARD should prefer/avoid (e.g. "prefer asyncio over threading for I/O")
- EPISODE: what happened this session (e.g. "SHARD certified Python asyncio with score 8.5")
- GOAL: active objective derived from the study
- RELATION: causal/structural link between two concepts
- Skip generic facts (e.g. "Python has loops") — extract insights
- EPISODE memories about this specific certification are always useful

Return JSON array:
[
  {{
    "content": "...",
    "memory_type": "FACT|PREFERENCE|EPISODE|GOAL|RELATION",
    "entities": ["entity1", "entity2"],
    "confidence": 0.0
  }}
]
"""

_SESSION_LOG_EXTRACTION_PROMPT = """\
Extract discrete memories from this SHARD session log entry.

SESSION LOG:
{log_text}

Extract 2-5 memories about what happened, what was learned, what failed, what succeeded.
Focus on EPISODE and GOAL types for session logs.

Return JSON array:
[
  {{
    "content": "...",
    "memory_type": "FACT|PREFERENCE|EPISODE|GOAL|RELATION",
    "entities": ["entity1", "entity2"],
    "confidence": 0.0
  }}
]
"""

_FREEFORM_EXTRACTION_PROMPT = """\
Extract discrete memories from this content about SHARD or its domain.

SOURCE TYPE: {source_type}
CONTENT:
{content}

Return 2-6 memories as JSON array:
[
  {{
    "content": "...",
    "memory_type": "FACT|PREFERENCE|EPISODE|GOAL|RELATION",
    "entities": ["entity1", "entity2"],
    "confidence": 0.0
  }}
]
"""


@dataclass
class Memory:
    content:      str
    memory_type:  str
    entities:     List[str]       = field(default_factory=list)
    confidence:   float           = 1.0
    source_type:  str             = "study"
    source_ref:   str             = ""
    container_tag: str            = "shard"
    expires_at:   Optional[str]   = None
    updates:      Optional[str]   = None
    id:           str             = field(default_factory=lambda: str(uuid.uuid4()))
    created_at:   str             = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        # Validate memory_type
        if self.memory_type not in MEMORY_TYPES:
            self.memory_type = "FACT"
        # Clamp confidence
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        # Auto-set expiry for EPISODE memories
        if self.memory_type == "EPISODE" and self.expires_at is None:
            self.expires_at = (
                datetime.now() + timedelta(days=EPISODE_TTL_DAYS)
            ).isoformat()


class MemoryExtractor:
    """Extracts typed Memory objects from any text source and stores them in shard.db.

    Args:
        think_fn: Async callable ``(prompt, system, json_mode) -> str``.
                  Typically ``StudyAgent._think_fast``.
    """

    def __init__(self, think_fn: Optional[Callable[..., Any]] = None):
        self._think = think_fn

    # ── Public extraction API ─────────────────────────────────────────────────

    async def extract_from_study(
        self,
        topic: str,
        structured: Dict[str, Any],
        score: float = 0.0,
        certified: bool = False,
    ) -> List[Memory]:
        """Extract memories from a study phase synthesis dict."""
        knowledge_text = _summarize_structured(topic, structured)
        if not knowledge_text.strip():
            return []

        prompt = _STUDY_EXTRACTION_PROMPT.format(
            topic=topic,
            score=round(score, 1),
            certified="YES" if certified else "NO",
            knowledge_text=knowledge_text[:2000],
        )

        raw_memories = await self._call_llm(prompt)
        return [
            Memory(
                **m,
                source_type="study",
                source_ref=topic,
                container_tag="shard",
            )
            for m in raw_memories
        ]

    async def extract_from_session_log(
        self,
        log_text: str,
        session_id: str = "",
    ) -> List[Memory]:
        """Extract memories from a session log entry (SSJ logs)."""
        if not log_text.strip():
            return []

        prompt = _SESSION_LOG_EXTRACTION_PROMPT.format(
            log_text=log_text[:2000],
        )

        raw_memories = await self._call_llm(prompt)
        return [
            Memory(
                **m,
                source_type="session_log",
                source_ref=session_id,
                container_tag="shard",
            )
            for m in raw_memories
        ]

    async def extract_from_text(
        self,
        content: str,
        source_type: str = "connector",
        source_ref: str = "",
        container_tag: str = "shard",
    ) -> List[Memory]:
        """Generic extraction from free-form text."""
        if not content.strip():
            return []

        prompt = _FREEFORM_EXTRACTION_PROMPT.format(
            source_type=source_type,
            content=content[:2000],
        )

        raw_memories = await self._call_llm(prompt)
        return [
            Memory(
                **m,
                source_type=source_type,
                source_ref=source_ref,
                container_tag=container_tag,
            )
            for m in raw_memories
        ]

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, memories: List[Memory]) -> int:
        """Store memories in shard.db, handling is_latest supersession.

        For each new memory:
        - If it shares entities + memory_type with an existing is_latest memory,
          mark the old one as is_latest=0 and set updates=old_id.
        - Insert the new memory.

        Returns the number of memories saved.
        """
        if not memories:
            return 0

        saved = 0
        for mem in memories:
            try:
                # Find existing latest memories with entity overlap
                old_id = self._find_superseded(mem)
                if old_id:
                    execute(
                        "UPDATE memories SET is_latest=0, updated_at=? WHERE id=?",
                        (datetime.now().isoformat(), old_id),
                    )
                    mem.updates = old_id
                    logger.debug(
                        "[MEMORY] Superseded %s with new %s memory for '%s'",
                        old_id[:8], mem.memory_type, mem.content[:60],
                    )

                execute(
                    """INSERT INTO memories
                       (id, content, memory_type, entities, confidence, is_latest,
                        expires_at, updates, source_type, source_ref, container_tag,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        mem.id,
                        mem.content,
                        mem.memory_type,
                        json.dumps(mem.entities, ensure_ascii=False),
                        mem.confidence,
                        mem.expires_at,
                        mem.updates,
                        mem.source_type,
                        mem.source_ref,
                        mem.container_tag,
                        mem.created_at,
                        datetime.now().isoformat(),
                    ),
                )
                saved += 1
            except Exception as exc:
                logger.warning("[MEMORY] Failed to save memory: %s — %s", mem.content[:60], exc)

        logger.info(
            "[MEMORY] Saved %d/%d memories (source=%s ref=%s)",
            saved, len(memories),
            memories[0].source_type if memories else "?",
            memories[0].source_ref[:40] if memories else "?",
        )
        return saved

    # ── Query API ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_latest(
        container_tag: str = "shard",
        memory_type: Optional[str] = None,
        min_confidence: float = 0.3,
        limit: int = 50,
    ) -> List[Dict]:
        """Return the most recent is_latest=1 memories."""
        if memory_type:
            return query(
                """SELECT * FROM memories
                   WHERE is_latest=1 AND container_tag=? AND memory_type=?
                   AND confidence >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (container_tag, memory_type, min_confidence, limit),
            )
        return query(
            """SELECT * FROM memories
               WHERE is_latest=1 AND container_tag=?
               AND confidence >= ?
               ORDER BY created_at DESC LIMIT ?""",
            (container_tag, min_confidence, limit),
        )

    @staticmethod
    def get_for_topic(topic: str) -> List[Dict]:
        """Return all is_latest memories extracted from a specific topic."""
        return query(
            """SELECT * FROM memories
               WHERE source_ref=? AND is_latest=1
               ORDER BY confidence DESC""",
            (topic,),
        )

    @staticmethod
    def stats() -> Dict[str, Any]:
        """Return memory table statistics."""
        rows = query(
            """SELECT memory_type, COUNT(*) as n, AVG(confidence) as avg_conf
               FROM memories WHERE is_latest=1
               GROUP BY memory_type ORDER BY n DESC""",
            (),
        )
        total = query("SELECT COUNT(*) as n FROM memories", ())[0]["n"]
        latest = query("SELECT COUNT(*) as n FROM memories WHERE is_latest=1", ())[0]["n"]
        return {
            "total":      total,
            "latest":     latest,
            "superseded": total - latest,
            "by_type":    rows,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _call_llm(self, prompt: str) -> List[Dict]:
        """Call LLM and parse JSON array response."""
        if not self._think:
            return []
        try:
            raw = await self._think(prompt, _SYSTEM_PROMPT, json_mode=True)
            return _parse_memory_list(raw)
        except Exception as exc:
            logger.warning("[MEMORY] LLM extraction failed: %s", exc)
            return []

    def _find_superseded(self, mem: Memory) -> Optional[str]:
        """Find an existing is_latest memory that this one supersedes.

        Criteria: same memory_type AND at least one entity in common AND
        content similarity > threshold (simple word overlap check — no embedding).
        We avoid false positives by requiring at least 2 words in common.
        """
        if not mem.entities:
            return None
        try:
            # Get recent same-type memories with any shared entity
            candidates = query(
                """SELECT id, content, entities FROM memories
                   WHERE is_latest=1 AND memory_type=? AND container_tag=?
                   AND source_ref=?
                   ORDER BY created_at DESC LIMIT 20""",
                (mem.memory_type, mem.container_tag, mem.source_ref),
            )
            if not candidates:
                return None

            new_words = set(_tokenize(mem.content))
            new_entities = set(e.lower() for e in mem.entities)

            for candidate in candidates:
                old_entities = set(
                    e.lower() for e in json.loads(candidate.get("entities") or "[]")
                )
                entity_overlap = new_entities & old_entities
                if not entity_overlap:
                    continue
                old_words = set(_tokenize(candidate["content"]))
                word_overlap = len(new_words & old_words)
                if word_overlap >= 3:
                    return candidate["id"]
        except Exception as exc:
            logger.debug("[MEMORY] Supersession check failed: %s", exc)
        return None


# ── Module-level helpers ───────────────────────────────────────────────────────

def _summarize_structured(topic: str, structured: Dict[str, Any]) -> str:
    """Build a text summary of ctx.structured for extraction."""
    parts = [f"Topic: {topic}"]
    concepts = structured.get("concepts", [])
    for c in concepts[:6]:
        name = c.get("name", "")
        expl = c.get("explanation", "") or c.get("definition", "") or ""
        if name and expl:
            parts.append(f"- {name}: {str(expl)[:200]}")
    opinion = structured.get("shard_opinion", "")
    if opinion:
        parts.append(f"SHARD stance: {str(opinion)[:300]}")
    connections = structured.get("connections", [])
    if connections:
        parts.append(f"Connections: {', '.join(str(c) for c in connections[:4])}")
    return "\n".join(parts)


def _parse_memory_list(raw: Any) -> List[Dict]:
    """Parse LLM response into a list of memory dicts."""
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, str):
        import re
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                return []
    else:
        return []

    if not isinstance(data, list):
        return []

    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        mtype = str(item.get("memory_type", "FACT")).upper().strip()
        if not content or mtype not in MEMORY_TYPES:
            continue
        result.append({
            "content":     content,
            "memory_type": mtype,
            "entities":    [str(e) for e in (item.get("entities") or [])],
            "confidence":  float(item.get("confidence") or 0.8),
        })
    return result


def _tokenize(text: str) -> List[str]:
    """Simple word tokenizer for overlap check."""
    import re
    stop = {"is", "are", "the", "a", "an", "in", "for", "of", "to", "and",
            "or", "not", "with", "that", "this", "it", "as", "be", "has",
            "have", "was", "were", "by", "on", "at", "from", "use", "used"}
    words = re.findall(r"[a-z0-9]{3,}", text.lower())
    return [w for w in words if w not in stop]
