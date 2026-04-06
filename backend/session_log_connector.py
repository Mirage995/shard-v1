"""session_log_connector.py -- Imports SHARD session history into the memories table.

Reads session_reflections.jsonl and session_snapshots.jsonl, extracts typed
memories from each entry, and stores them in shard.db.

This is the "backfill" connector: run once to import all history, then
incrementally on each new session. Already-imported sessions are skipped
(idempotent via session_id tracking in kv_store).

Usage:
    # One-time backfill (run from backend/ dir):
    python session_log_connector.py

    # Programmatic (e.g. after each session in NightRunner):
    from session_log_connector import SessionLogConnector
    connector = SessionLogConnector(think_fn=agent._think_fast)
    await connector.sync_new()
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, List, Optional

from memory_extractor import Memory, MemoryExtractor
from shard_db import execute, query

logger = logging.getLogger("shard.session_log_connector")

_ROOT            = Path(__file__).resolve().parent.parent
_MEMORY_DIR      = _ROOT / "shard_memory"
_REFLECTIONS     = _MEMORY_DIR / "session_reflections.jsonl"
_SNAPSHOTS       = _MEMORY_DIR / "session_snapshots.jsonl"

# kv_store key prefix for tracking imported sessions
_KV_PREFIX = "session_log_imported:"


class SessionLogConnector:
    """Imports session history into the typed memories table.

    Args:
        think_fn: Async callable for LLM-based extraction.
                  If None, only rule-based memories are created (no LLM).
    """

    def __init__(self, think_fn: Optional[Callable[..., Any]] = None):
        self._extractor = MemoryExtractor(think_fn=think_fn)

    # ── Public API ────────────────────────────────────────────────────────────

    async def sync_all(self) -> dict:
        """Import ALL session history. Skips already-imported sessions."""
        reflections = _load_jsonl(_REFLECTIONS)
        snapshots   = _load_jsonl_indexed(_SNAPSHOTS, key="session_id")

        total_imported = 0
        total_skipped  = 0
        total_memories = 0

        for entry in reflections:
            session_id = entry.get("session_id") or entry.get("ts", "")[:19]
            if not session_id:
                continue

            if self._already_imported(session_id):
                total_skipped += 1
                continue

            memories = await self._extract_from_reflection(
                entry, snapshots.get(session_id)
            )
            if memories:
                saved = self._extractor.save(memories)
                total_memories += saved

            self._mark_imported(session_id)
            total_imported += 1

        logger.info(
            "[SESSION_CONNECTOR] sync_all: imported=%d skipped=%d memories=%d",
            total_imported, total_skipped, total_memories,
        )
        return {
            "imported":  total_imported,
            "skipped":   total_skipped,
            "memories":  total_memories,
        }

    async def sync_new(self) -> dict:
        """Import only sessions not yet in the memories table. Alias for sync_all."""
        return await self.sync_all()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _extract_from_reflection(
        self,
        entry: dict,
        snapshot: Optional[dict],
    ) -> List[Memory]:
        """Build Memory objects from one session_reflections entry."""
        session_id = entry.get("session_id") or entry.get("ts", "")[:19]
        ts         = entry.get("ts", "")[:19]
        certified  = entry.get("certified", [])
        failed     = entry.get("failed", [])
        text       = str(entry.get("text", "") or "").strip()

        memories: List[Memory] = []

        # ── Rule-based memories (no LLM needed) ──────────────────────────────

        # Certified topics → FACT memories
        if isinstance(certified, list):
            for topic in certified:
                if topic and isinstance(topic, str):
                    memories.append(Memory(
                        content=f"SHARD certified '{topic}' in session {session_id[:10]}",
                        memory_type="EPISODE",
                        entities=["SHARD", topic],
                        confidence=0.95,
                        source_type="session_log",
                        source_ref=session_id,
                        container_tag="shard",
                    ))

        # Failed topics → EPISODE memories
        if isinstance(failed, list):
            for topic in failed[:5]:  # cap at 5 to avoid noise
                if topic and isinstance(topic, str):
                    memories.append(Memory(
                        content=f"SHARD failed to certify '{topic}' in session {session_id[:10]}",
                        memory_type="EPISODE",
                        entities=["SHARD", topic],
                        confidence=0.90,
                        source_type="session_log",
                        source_ref=session_id,
                        container_tag="shard",
                    ))

        # Session metrics from snapshot → EPISODE
        if snapshot:
            cert_rate  = snapshot.get("cert_rate", 0.0) or 0.0
            avg_score  = snapshot.get("avg_score", 0.0) or 0.0
            cycles     = snapshot.get("completed_cycles", 0) or 0
            risk_score = snapshot.get("risk_score", 0.0) or 0.0
            flags      = snapshot.get("flags", []) or []

            if cycles > 0:
                memories.append(Memory(
                    content=(
                        f"Session {session_id[:10]}: {cycles} cycles, "
                        f"cert_rate={cert_rate:.0%}, avg_score={avg_score:.1f}"
                    ),
                    memory_type="EPISODE",
                    entities=["SHARD", "session_metrics"],
                    confidence=1.0,
                    source_type="session_log",
                    source_ref=session_id,
                    container_tag="shard",
                ))

            if risk_score > 0.5 and flags:
                memories.append(Memory(
                    content=(
                        f"Perverse behavior detected in session {session_id[:10]}: "
                        f"risk={risk_score:.2f} flags={flags}"
                    ),
                    memory_type="EPISODE",
                    entities=["SHARD", "perverse_detection"] + list(flags),
                    confidence=0.95,
                    source_type="session_log",
                    source_ref=session_id,
                    container_tag="shard",
                ))

        # ── LLM-based extraction from reflection text ─────────────────────────
        # Only if text is meaningful (not an error message, not empty)
        if (text
                and len(text) > 80
                and "ALL PROVIDERS FAILED" not in text
                and "reflection generation failed" not in text.lower()):
            llm_memories = await self._extractor.extract_from_session_log(
                log_text=text,
                session_id=session_id,
            )
            memories.extend(llm_memories)

        return memories

    @staticmethod
    def _already_imported(session_id: str) -> bool:
        rows = query(
            "SELECT value FROM kv_store WHERE key=?",
            (f"{_KV_PREFIX}{session_id}",),
        )
        return bool(rows)

    @staticmethod
    def _mark_imported(session_id: str) -> None:
        execute(
            "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
            (f"{_KV_PREFIX}{session_id}", "1"),
        )


# ── Module-level helpers ───────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return result


def _load_jsonl_indexed(path: Path, key: str) -> dict:
    """Load jsonl and index by a specific key."""
    rows = _load_jsonl(path)
    return {str(r.get(key, "")): r for r in rows if r.get(key)}


# ── CLI entry point ───────────────────────────────────────────────────────────

async def _main():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")

    from study_agent import StudyAgent
    print("Inizializzando StudyAgent per LLM extraction...")
    agent = StudyAgent()
    connector = SessionLogConnector(think_fn=agent._think_fast)

    print("Avvio sync_all — importazione storia sessioni...")
    result = await connector.sync_all()
    print(f"\nRisultato:")
    print(f"  Sessioni importate: {result['imported']}")
    print(f"  Sessioni skippate:  {result['skipped']}")
    print(f"  Memories salvate:   {result['memories']}")

    from memory_extractor import MemoryExtractor
    stats = MemoryExtractor.stats()
    print(f"\nMemories table:")
    print(f"  Total: {stats['total']}  Latest: {stats['latest']}")
    for row in stats["by_type"]:
        print(f"  {row['memory_type']}: {row['n']} (avg_conf={row['avg_conf']:.2f})")


if __name__ == "__main__":
    asyncio.run(_main())
