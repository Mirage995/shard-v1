"""
session_reflection.py -- SHARD end-of-session LLM reflection.

At the end of each NightRunner session, generates a structured LLM reflection
that identifies patterns, connections, and surprises across the session's work.
Stored in shard.db session_reflections table and injected as context into
the next session's opening prompt.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REFLECTIONS_PATH = _REPO_ROOT / "shard_memory" / "session_reflections.jsonl"
_MAX_REFLECTIONS_LOADED = 3          # how many past reflections to inject
_MAX_REFLECTION_CHARS = 1200         # truncation per reflection in prompt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_reflection(record: dict) -> None:
    """Insert a reflection record into SQLite. Falls back to .jsonl on error."""
    try:
        from shard_db import get_db
        db = get_db()
        certified = record.get("certified", [])
        failed = record.get("failed", [])
        db.execute(
            """INSERT INTO session_reflections (session_id, ts, certified, failed, text)
               VALUES (?, ?, ?, ?, ?)""",
            (
                record.get("session_id", ""),
                record.get("ts", ""),
                json.dumps(certified) if isinstance(certified, list) else str(certified),
                json.dumps(failed) if isinstance(failed, list) else str(failed),
                record.get("text", ""),
            ),
        )
        db.commit()
        # TTL pruning: keep latest 200
        db.execute(
            "DELETE FROM session_reflections WHERE id <= "
            "(SELECT id FROM session_reflections ORDER BY id DESC LIMIT 1 OFFSET 200)"
        )
        db.commit()
    except Exception:
        # Last-resort fallback
        path = _REFLECTIONS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_recent_reflections(n: int) -> list[dict]:
    """Load the N most recent session reflections from SQLite."""
    try:
        from shard_db import get_db
        rows = get_db().execute(
            "SELECT session_id, ts, certified, failed, text FROM session_reflections "
            "ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
        result = []
        for row in reversed(rows):
            r = dict(row) if isinstance(row, dict) else {
                "session_id": row[0], "ts": row[1],
                "certified": row[2], "failed": row[3], "text": row[4],
            }
            # Deserialise JSON arrays stored as strings
            for field in ("certified", "failed"):
                if isinstance(r.get(field), str):
                    try:
                        r[field] = json.loads(r[field])
                    except Exception:
                        r[field] = []
            result.append(r)
        return result
    except Exception:
        # Fallback: read from .jsonl if SQLite unavailable
        try:
            lines = _REFLECTIONS_PATH.read_text(encoding="utf-8").splitlines()
            records = []
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
                if len(records) >= n:
                    break
            return list(reversed(records))
        except Exception:
            return []


# ---------------------------------------------------------------------------
# SessionReflection
# ---------------------------------------------------------------------------


class SessionReflection:
    """
    Generates and persists end-of-session reflections for SHARD.

    Usage (inside NightRunner._post_session):
        sr = SessionReflection(llm_call_fn=self._llm_call)
        await sr.generate_and_save(session_ctx)
    """

    def __init__(
        self,
        llm_call_fn=None,
        reflections_path: Path = _REFLECTIONS_PATH,
    ) -> None:
        """
        Args:
            llm_call_fn: async callable (prompt: str) -> str
                         Used to generate the reflection text.
                         If None, reflection is skipped (no-op).
            reflections_path: where to append reflection records.
        """
        self._llm = llm_call_fn
        self._path = reflections_path

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def generate_and_save(self, ctx: dict) -> Optional[str]:
        """
        Build a reflection for the current session and save it.

        Args:
            ctx: dict with keys:
                certified_topics  list[str]
                failed_topics     list[str]
                benchmark_delta   str  (from BenchmarkTracker.get_delta_summary())
                failure_patterns  list[str]  (optional)
                session_id        str  (optional)

        Returns:
            The reflection text, or None if generation was skipped.
        """
        if self._llm is None:
            return None

        prompt = self._build_prompt(ctx)
        try:
            reflection_text = await self._llm(prompt)
        except Exception as exc:
            reflection_text = f"[reflection generation failed: {exc}]"

        record = {
            "ts": _utc_now_iso(),
            "session_id": ctx.get("session_id", ""),
            "certified": ctx.get("certified_topics", []),
            "failed": ctx.get("failed_topics", []),
            "text": reflection_text,
        }
        try:
            _save_reflection(record)
        except Exception:
            pass

        return reflection_text

    # ------------------------------------------------------------------
    # Prompt injection (for next session)
    # ------------------------------------------------------------------

    def get_context_block(self, n: int = _MAX_REFLECTIONS_LOADED) -> str:
        """
        Return a string block summarising the N most recent reflections.
        Suitable for injection at the top of NightRunner's session prompt.
        """
        records = _load_recent_reflections(n)
        if not records:
            return ""

        parts = ["[Past Session Reflections]"]
        for rec in records:
            ts = rec.get("ts", "")[:10]  # date only
            text = rec.get("text", "").strip()
            if len(text) > _MAX_REFLECTION_CHARS:
                text = text[:_MAX_REFLECTION_CHARS] + "..."
            certified = rec.get("certified", [])
            certified_line = (
                f"Certified: {', '.join(certified[:6])}"
                if isinstance(certified, list) and certified
                else ""
            )
            parts.append(f"\n--- {ts} ---")
            if certified_line:
                parts.append(certified_line)
            parts.append(text)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_prompt(self, ctx: dict) -> str:
        certified = ctx.get("certified_topics", [])
        failed = ctx.get("failed_topics", [])
        benchmark_delta = ctx.get("benchmark_delta", "N/A")
        failure_patterns = ctx.get("failure_patterns", [])

        certified_str = (
            "\n".join(f"  • {t}" for t in certified) if certified else "  (none)"
        )
        failed_str = (
            "\n".join(f"  • {t}" for t in failed) if failed else "  (none)"
        )
        patterns_str = (
            "\n".join(f"  • {p}" for p in failure_patterns[:6])
            if failure_patterns
            else "  (none recorded)"
        )

        return f"""You are SHARD's introspective reasoning module. Analyse the session below and produce a concise reflection (150-250 words).

## Session Summary

**Topics certified this session:**
{certified_str}

**Topics that failed or were not completed:**
{failed_str}

**Benchmark delta vs previous session:**
{benchmark_delta}

**Recurring failure patterns observed:**
{patterns_str}

## Instructions

Write a structured reflection with these sections (use plain text, no markdown headers):

1. PATTERNS -- What recurring themes or error types appeared across topics?
2. CONNECTIONS -- What unexpected links did you notice between different topics?
3. SURPRISES -- What worked better or worse than expected?
4. NEXT FOCUS -- One or two concrete areas to prioritise next session based on the data above.

Be specific. Reference actual topic names. Keep it under 250 words.
"""


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------


def make_session_reflection(llm_call_fn=None) -> SessionReflection:
    """Create a SessionReflection with the given LLM callable."""
    return SessionReflection(llm_call_fn=llm_call_fn)
