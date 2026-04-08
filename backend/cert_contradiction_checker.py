"""cert_contradiction_checker.py -- Knowledge-level contradiction gate at certification time.

Fires when SHARD certifies a new topic. Compares the newly synthesized knowledge
against existing ChromaDB entries to detect contradictions before they pollute
the knowledge base.

Contradiction types (inspired by APEX ContradictionDetector):
  - explicit:    Direct factual conflict ("X is Y" vs "X is NOT Y")
  - semantic:    Same concept described inconsistently (same recommendation, opposite direction)
  - logical:     A implies B, but A also implies NOT B
  - transitive:  Dependency chain creates a cycle (A->B->C->NOT A)

Severity: LOW | MEDIUM | HIGH | CRITICAL

Resolution candidates:
  - KEEP_NEW:       New knowledge supersedes old (updated concept, version change)
  - KEEP_OLD:       Existing knowledge is more reliable
  - MERGE:          Both valid in different contexts
  - DEPRECATE_BOTH: Conflict too deep — neither can be trusted
  - PENDING:        Cannot resolve automatically, needs review

Output is written to shard_memory/self_inconsistencies.jsonl (severity >= MEDIUM)
and returned as a structured dict for use in study_phases.py.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("shard.cert_contradiction_checker")

_ROOT        = Path(__file__).resolve().parent.parent
_MEMORY_DIR  = _ROOT / "shard_memory"
_INCONS_PATH = _MEMORY_DIR / "self_inconsistencies.jsonl"

_LOG_SEVERITY = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_LOG_MIN      = "MEDIUM"   # log to disk only if severity >= this

_SYSTEM_PROMPT = (
    "You are a knowledge consistency auditor for an AI learning system. "
    "Your job is to detect REAL contradictions between knowledge statements — "
    "not superficial wording differences, but genuine logical or factual conflicts. "
    "Be strict: flag only genuine contradictions, not complementary or context-dependent statements. "
    "OUTPUT ONLY VALID JSON. No markdown, no backticks, no explanations."
)

_CHECK_TEMPLATE = """\
A learning system just certified new knowledge on a topic.
Check whether the NEW knowledge contradicts any of the EXISTING knowledge chunks.

TOPIC: {topic}

NEW KNOWLEDGE (just certified):
{new_knowledge}

EXISTING KNOWLEDGE CHUNKS (retrieved by similarity):
{existing_chunks}

Respond with a JSON object:
{{
  "has_contradiction": true | false,
  "contradiction_type": "explicit" | "semantic" | "logical" | "transitive" | null,
  "severity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null,
  "resolution": "KEEP_NEW" | "KEEP_OLD" | "MERGE" | "DEPRECATE_BOTH" | "PENDING" | null,
  "conflicting_chunk_id": "<id of the existing chunk that conflicts, or null>",
  "explanation": "<one sentence: what exactly conflicts and why>",
  "confidence": 0.0
}}

Rules:
- has_contradiction must be false unless there is a GENUINE factual or logical conflict.
- Complementary knowledge (e.g. "use X for Y" and "use Z for W") is NOT a contradiction.
- Context-dependent statements (e.g. "use threads for I/O" vs "use asyncio for I/O") are NOT contradictions — they are MERGE candidates only if directly conflicting.
- severity CRITICAL: opposite recommendations on the same exact operation.
- severity HIGH: same subject, clearly conflicting advice or definition.
- severity MEDIUM: partial conflict, or conflict visible only in specific contexts.
- severity LOW: framing inconsistency but no actionable conflict.
- If has_contradiction is false, all other fields must be null except explanation (empty string).
"""


class CertContradictionChecker:
    """Checks newly certified knowledge against existing ChromaDB entries.

    Args:
        think_fn:  Async callable ``(prompt, system, json_mode) -> str``.
                   Typically ``StudyAgent._think_fast``.
        kb:        ChromaDB collection (``agent.kb``).
        n_results: Number of similar chunks to retrieve for comparison.
    """

    def __init__(
        self,
        think_fn: Optional[Callable[..., Any]] = None,
        kb=None,
        n_results: int = 3,
    ):
        self._think    = think_fn
        self._kb       = kb
        self._n        = n_results

    # ── Main async API ───────────────────────────────���─────────────────────────

    async def check(
        self,
        topic: str,
        structured: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Check new knowledge for contradictions against ChromaDB.

        Args:
            topic:      The topic just certified.
            structured: ctx.structured dict (concepts, shard_opinion, etc.)

        Returns:
            {
              "checked":           bool,
              "has_contradiction": bool,
              "contradiction_type": str | None,
              "severity":          str | None,
              "resolution":        str | None,
              "explanation":       str,
              "conflicting_chunk_id": str | None,
              "confidence":        float,
              "existing_chunks_n": int,
            }
        """
        if not self._think or not self._kb:
            return _no_check("no LLM or KB configured")

        # Build a compact representation of the new knowledge
        new_knowledge = _summarize_structured(topic, structured)
        if not new_knowledge.strip():
            return _no_check("no synthesized knowledge to compare")

        # Query ChromaDB for the most similar existing chunks
        try:
            query_text = topic + " " + " ".join(
                c.get("name", "") for c in structured.get("concepts", [])[:4]
            )
            results = self._kb.query(
                query_texts=[query_text],
                n_results=self._n,
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            logger.warning("[CERT_CONTRADICTION] ChromaDB query failed: %s", exc)
            return _no_check(f"ChromaDB query failed: {exc}")

        docs  = (results.get("documents")  or [[]])[0]
        metas = (results.get("metadatas")  or [[]])[0]
        # IDs are always returned by ChromaDB queries (not part of include)
        ids   = (results.get("ids")        or [[]])[0]

        if not docs:
            return _no_check("no existing knowledge to compare against")

        # Filter out chunks from the SAME topic (we'd always find similarity with ourselves)
        filtered = [
            (doc, meta, chunk_id)
            for doc, meta, chunk_id in zip(docs, metas, ids)
            if str(meta.get("topic", "")).lower() != topic.lower()
        ]
        if not filtered:
            return _no_check("only found chunks from the same topic — skipping")

        # Build the existing chunks block for the prompt
        chunks_text = _format_chunks(filtered)

        prompt = _CHECK_TEMPLATE.format(
            topic=topic,
            new_knowledge=new_knowledge[:1200],
            existing_chunks=chunks_text,
        )

        try:
            raw = await self._think(prompt, _SYSTEM_PROMPT, json_mode=True)
        except Exception as exc:
            logger.warning("[CERT_CONTRADICTION] LLM call failed: %s", exc)
            return _no_check(f"LLM call failed: {exc}")

        data = _parse_json(raw)
        if data is None:
            return _no_check("LLM returned unparseable response")

        has_contradiction = bool(data.get("has_contradiction"))
        contradiction_type = data.get("contradiction_type")
        severity   = data.get("severity")
        resolution = data.get("resolution")
        explanation = str(data.get("explanation") or "")
        conflicting_id = data.get("conflicting_chunk_id")
        confidence = float(data.get("confidence") or 0.5)

        result = {
            "checked":              True,
            "has_contradiction":    has_contradiction,
            "contradiction_type":   contradiction_type,
            "severity":             severity,
            "resolution":           resolution,
            "explanation":          explanation,
            "conflicting_chunk_id": conflicting_id,
            "confidence":           confidence,
            "existing_chunks_n":    len(filtered),
            # Keep new_knowledge and conflicting_doc for auto-resolution
            "_new_knowledge":       new_knowledge,
            "_conflicting_doc":     next(
                (doc for doc, _, cid in filtered if cid == conflicting_id),
                None,
            ) if conflicting_id else None,
        }

        if has_contradiction:
            logger.info(
                "[CERT_CONTRADICTION] Detected %s/%s on topic '%s': %s",
                contradiction_type, severity, topic, explanation[:120],
            )
            # Persist to self_inconsistencies.jsonl if severity is significant
            if severity in _LOG_SEVERITY and _severity_rank(severity) >= _severity_rank(_LOG_MIN):
                _persist_inconsistency(topic, result)
        else:
            logger.debug("[CERT_CONTRADICTION] No contradiction found for '%s'.", topic)

        return result

    async def resolve(
        self,
        topic: str,
        check_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute the suggested resolution against ChromaDB.

        Acts on ``check_result["resolution"]``:
          - KEEP_OLD:       delete the NEW knowledge chunk if it was already stored
                            (caller should avoid storing it — this is a safety net)
          - KEEP_NEW:       delete the conflicting OLD chunk from ChromaDB
          - MERGE:          generate a unified chunk via LLM, replace old chunk with it
          - DEPRECATE_BOTH: delete both old and new chunks
          - PENDING:        no action — log and return

        Args:
            topic:        The topic just certified.
            check_result: The dict returned by ``check()``.

        Returns:
            {
              "resolved":   bool,
              "action":     str,
              "detail":     str,
            }
        """
        if not check_result.get("has_contradiction"):
            return {"resolved": False, "action": "none", "detail": "no contradiction to resolve"}

        resolution     = check_result.get("resolution", "PENDING")
        conflicting_id = check_result.get("conflicting_chunk_id")
        new_knowledge  = check_result.get("_new_knowledge", "")
        conflicting_doc = check_result.get("_conflicting_doc", "")
        severity       = check_result.get("severity", "?")
        explanation    = check_result.get("explanation", "")

        if resolution == "PENDING":
            logger.info("[CERT_RESOLUTION] PENDING — no action for '%s'", topic)
            return {"resolved": False, "action": "pending", "detail": "resolution deferred to manual review"}

        if resolution == "KEEP_OLD":
            # The new knowledge is wrong — it shouldn't be stored.
            # We can't delete it if it was never added, but log the intent.
            logger.info(
                "[CERT_RESOLUTION] KEEP_OLD for '%s' — new knowledge discarded. %s",
                topic, explanation[:100],
            )
            _persist_resolution(topic, resolution, conflicting_id, explanation, "new_knowledge_not_stored")
            return {"resolved": True, "action": "keep_old", "detail": "new knowledge flagged as incorrect — not persisted"}

        if not self._kb:
            return {"resolved": False, "action": "error", "detail": "no KB configured for resolution"}

        if resolution == "KEEP_NEW":
            if not conflicting_id:
                return {"resolved": False, "action": "error", "detail": "KEEP_NEW but no conflicting_chunk_id"}
            try:
                self._kb.delete(ids=[conflicting_id])
                logger.info(
                    "[CERT_RESOLUTION] KEEP_NEW — deleted old chunk '%s' for topic '%s'",
                    conflicting_id, topic,
                )
                _persist_resolution(topic, resolution, conflicting_id, explanation, f"deleted_chunk:{conflicting_id}")
                return {"resolved": True, "action": "keep_new", "detail": f"old chunk {conflicting_id} deleted from KB"}
            except Exception as exc:
                logger.warning("[CERT_RESOLUTION] KEEP_NEW delete failed: %s", exc)
                return {"resolved": False, "action": "error", "detail": str(exc)}

        if resolution == "MERGE":
            if not self._think or not conflicting_doc:
                return {"resolved": False, "action": "error", "detail": "MERGE needs LLM + conflicting doc"}
            merged = await self._generate_merged_chunk(topic, new_knowledge, conflicting_doc, explanation)
            if not merged:
                return {"resolved": False, "action": "error", "detail": "MERGE LLM call failed"}
            try:
                # Replace old chunk with the merged version
                if conflicting_id:
                    self._kb.delete(ids=[conflicting_id])
                self._kb.add(
                    documents=[merged],
                    metadatas=[{"topic": topic, "source": "merge_resolution", "merged": True}],
                    ids=[f"merged_{topic}_{datetime.now().strftime('%Y%m%d%H%M%S')}"],
                )
                logger.info("[CERT_RESOLUTION] MERGE — unified chunk stored for '%s'", topic)
                _persist_resolution(topic, resolution, conflicting_id, explanation, "merged_chunk_stored")
                return {"resolved": True, "action": "merge", "detail": "merged knowledge chunk stored in KB"}
            except Exception as exc:
                logger.warning("[CERT_RESOLUTION] MERGE store failed: %s", exc)
                return {"resolved": False, "action": "error", "detail": str(exc)}

        if resolution == "DEPRECATE_BOTH":
            deleted = []
            if conflicting_id:
                try:
                    self._kb.delete(ids=[conflicting_id])
                    deleted.append(conflicting_id)
                except Exception as exc:
                    logger.warning("[CERT_RESOLUTION] DEPRECATE_BOTH old delete failed: %s", exc)
            logger.info(
                "[CERT_RESOLUTION] DEPRECATE_BOTH for '%s' — deleted %d chunk(s). New knowledge also discarded.",
                topic, len(deleted),
            )
            _persist_resolution(topic, resolution, conflicting_id, explanation, f"deprecated:{','.join(deleted) or 'none'}")
            return {
                "resolved": True,
                "action":   "deprecate_both",
                "detail":   f"deleted {len(deleted)} old chunk(s); new knowledge not persisted",
            }

        return {"resolved": False, "action": "unknown", "detail": f"unknown resolution: {resolution}"}

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _generate_merged_chunk(
        self,
        topic: str,
        new_knowledge: str,
        old_knowledge: str,
        conflict_explanation: str,
    ) -> Optional[str]:
        """Ask LLM to produce a single unified knowledge chunk from two conflicting ones."""
        prompt = f"""Two knowledge chunks about '{topic}' conflict.
Produce ONE unified, accurate knowledge chunk that resolves the conflict.
Be precise and context-aware: if both are correct in different contexts, say so explicitly.

CONFLICT: {conflict_explanation}

CHUNK A (existing):
{old_knowledge[:600]}

CHUNK B (new):
{new_knowledge[:600]}

Write ONLY the unified knowledge chunk text (no JSON, no headers, no explanation).
The chunk must be factually accurate, concise (max 200 words), and usable as a standalone reference.
"""
        try:
            result = await self._think(prompt, "You are a precise technical knowledge editor.", json_mode=False)
            return result.strip() if result and result.strip() else None
        except Exception as exc:
            logger.warning("[CERT_RESOLUTION] Merge LLM call failed: %s", exc)
            return None


# ── Module-level helpers ───────────────────────────────────────────────────────

def _summarize_structured(topic: str, structured: Dict[str, Any]) -> str:
    """Build a compact text summary of the newly synthesized knowledge."""
    parts = [f"Topic: {topic}"]

    concepts = structured.get("concepts", [])
    if concepts:
        names = [c.get("name", "") for c in concepts[:6] if c.get("name")]
        if names:
            parts.append(f"Key concepts: {', '.join(names)}")
        # Include definitions/explanations from the first 3 concepts
        for c in concepts[:3]:
            name = c.get("name", "")
            explanation = c.get("explanation", "") or c.get("definition", "") or c.get("description", "")
            if name and explanation:
                parts.append(f"- {name}: {str(explanation)[:200]}")

    opinion = structured.get("shard_opinion", "")
    if opinion:
        parts.append(f"SHARD stance: {str(opinion)[:300]}")

    critical_q = structured.get("critical_questions", [])
    if isinstance(critical_q, list) and critical_q:
        parts.append(f"Critical questions: {'; '.join(str(q) for q in critical_q[:2])}")

    return "\n".join(parts)


def _format_chunks(filtered: list) -> str:
    """Format retrieved chunks for the prompt."""
    parts = []
    for i, (doc, meta, chunk_id) in enumerate(filtered, 1):
        chunk_topic = meta.get("topic", "unknown") if meta else "unknown"
        parts.append(
            f"[Chunk {i} | id={chunk_id} | topic={chunk_topic}]\n"
            f"{str(doc)[:400]}"
        )
    return "\n\n".join(parts)


def _parse_json(raw: Any) -> Optional[Dict]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    import re
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _severity_rank(severity: Optional[str]) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(severity or "", -1)


def _no_check(reason: str) -> Dict[str, Any]:
    return {
        "checked":              False,
        "has_contradiction":    False,
        "contradiction_type":   None,
        "severity":             None,
        "resolution":           None,
        "explanation":          "",
        "conflicting_chunk_id": None,
        "confidence":           0.0,
        "existing_chunks_n":    0,
        "reason":               reason,
    }


def _persist_resolution(
    topic: str,
    resolution: str,
    conflicting_id: Optional[str],
    explanation: str,
    action_taken: str,
) -> None:
    """Persist resolution record to SQLite self_inconsistencies table."""
    try:
        from shard_db import get_db
        db = get_db()
        db.execute(
            """INSERT INTO self_inconsistencies
               (topic, event_type, resolution, explanation, extra, ts)
               VALUES (?, 'resolution', ?, ?, ?, ?)""",
            (
                topic,
                resolution,
                explanation,
                json.dumps({"conflicting_id": conflicting_id, "action_taken": action_taken}),
                datetime.now().isoformat(),
            ),
        )
        db.commit()
    except Exception as exc:
        logger.warning("[CERT_RESOLUTION] Failed to persist resolution record: %s", exc)


def _persist_inconsistency(topic: str, result: Dict[str, Any]) -> None:
    """Persist inconsistency to SQLite self_inconsistencies table."""
    try:
        from shard_db import get_db
        db = get_db()
        db.execute(
            """INSERT INTO self_inconsistencies
               (topic, event_type, severity, resolution, explanation, extra, ts)
               VALUES (?, 'contradiction', ?, ?, ?, ?, ?)""",
            (
                topic,
                result.get("severity"),
                result.get("resolution"),
                result.get("explanation"),
                json.dumps({
                    "contradiction_type": result.get("contradiction_type"),
                    "conflicting_chunk_id": result.get("conflicting_chunk_id"),
                    "confidence": result.get("confidence"),
                }),
                datetime.now().isoformat(),
            ),
        )
        db.commit()
        logger.info("[CERT_CONTRADICTION] Inconsistency logged to SQLite")
    except Exception as exc:
        logger.warning("[CERT_CONTRADICTION] Failed to persist inconsistency: %s", exc)
