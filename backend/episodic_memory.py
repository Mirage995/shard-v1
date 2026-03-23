"""episodic_memory.py — SHARD experience memory.

Stores and retrieves structured study episodes so that SHARD can learn
not just *what* a topic contains, but *how it experienced studying it*:
which approaches failed, which scored near-miss, what score was reached.

Storage: shard_memory/shard.db (experiments table).
Retrieval: SQL queries + word-overlap similarity for ranking.

Key API:
    EpisodicMemory.retrieve_context(topic, k=3) -> list[dict]
    EpisodicMemory.get_context_prompt(topic, k=3) -> str   # ready for LLM injection
    EpisodicMemory.record(episode: dict)                   # INSERT into experiments
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("shard.episodic_memory")

_ROOT = Path(__file__).resolve().parent.parent
_HISTORY_FILE = _ROOT / "shard_memory" / "experiment_history.json"  # fallback only


def _get_db():
    from shard_db import get_db
    return get_db()


def _word_overlap(a: str, b: str) -> float:
    """Jaccard similarity between word sets of two topic strings."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class EpisodicMemory:
    """Read/write interface over the experiments table in shard.db."""

    def __init__(self, history_path: Path = _HISTORY_FILE):
        self._path = history_path  # kept for fallback only

    # ── Read ──────────────────────────────────────────────────────────────────

    def _load(self) -> List[dict]:
        """Load experiments from SQLite, fallback to JSON."""
        try:
            conn = _get_db()
            rows = conn.execute(
                "SELECT topic, score, certified as success, timestamp, "
                "failure_reason, source, previous_score, "
                "strategies_reused, skills_unlocked, duration_min as duration_minutes "
                "FROM experiments ORDER BY timestamp"
            ).fetchall()
            result = []
            for r in rows:
                ep = dict(r)
                # Parse JSON arrays back to lists
                for key in ("strategies_reused", "skills_unlocked"):
                    val = ep.get(key)
                    if isinstance(val, str):
                        try:
                            ep[key] = json.loads(val)
                        except Exception:
                            ep[key] = []
                result.append(ep)
            logger.info("[DB] Loaded %d episodes from SQLite", len(result))
            return result
        except Exception as exc:
            logger.warning("[DB] Episodic SQLite load failed (%s), falling back to JSON", exc)

        # Fallback: legacy JSON
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("[EPISODIC] Could not load history: %s", exc)
            return []

    def retrieve_context(self, topic: str, k: int = 3,
                         similarity_threshold: float = 0.25) -> List[dict]:
        """Return up to k past episodes relevant to *topic*.

        Matching strategy:
          1. Exact topic match (case-insensitive)
          2. Word-overlap >= similarity_threshold
        Results are sorted by recency (newest first).
        """
        history = self._load()
        topic_lower = topic.lower().strip()

        scored: List[tuple] = []
        for ep in history:
            ep_topic = ep.get("topic", "").lower().strip()
            if ep_topic == topic_lower:
                sim = 1.0
            else:
                sim = _word_overlap(topic_lower, ep_topic)
            if sim >= similarity_threshold:
                scored.append((sim, ep))

        # Sort by (similarity desc, timestamp desc)
        scored.sort(key=lambda x: (x[0], x[1].get("timestamp", "")), reverse=True)
        return [ep for _, ep in scored[:k]]

    def get_context_prompt(self, topic: str, k: int = 3) -> Optional[str]:
        """Return a formatted string ready to inject into an LLM prompt.

        Returns None if no relevant past episodes exist.
        """
        episodes = self.retrieve_context(topic, k=k)
        if not episodes:
            return None

        lines = [f"Past experience with '{topic}' ({len(episodes)} relevant attempt(s)):"]
        for ep in episodes:
            date = ep.get("timestamp", "")[:10]
            score = ep.get("score") or 0  # guard: DB NULL → None → 0
            reason = ep.get("failure_reason") or "unknown"
            strats = ", ".join(ep.get("strategies_reused") or []) or "none"
            success = "CERTIFIED" if ep.get("success") else f"FAILED ({reason})"
            lines.append(f"  - {date} | score={score:.1f}/10 | {success} | strategies: {strats}")

        # Derive actionable hint from failure pattern
        reasons = [ep.get("failure_reason", "") for ep in episodes if not ep.get("success")]
        if "near_miss" in reasons:
            lines.append("Hint: previous attempt was a near-miss -- focus on depth, "
                         "complete runnable code, and edge-case coverage to push score above 7.5.")
        elif "low_score" in reasons or "crash" in reasons:
            lines.append("Hint: previous attempts failed hard -- simplify the approach, "
                         "start with a minimal working example before adding complexity.")
        elif "phase_error" in reasons:
            lines.append("Hint: previous attempt crashed in a pipeline phase -- "
                         "ensure the topic is concrete enough to produce executable Python code.")

        return "\n".join(lines)

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(self, episode: dict) -> None:
        """Insert an episode into the experiments table.

        episode should have at minimum: topic, score, success, timestamp.
        """
        try:
            conn = _get_db()
            conn.execute(
                """INSERT INTO experiments
                   (topic, score, certified, timestamp, failure_reason, source,
                    previous_score, strategies_reused, skills_unlocked, duration_min)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    episode.get("topic", ""),
                    episode.get("score"),
                    1 if episode.get("success") or episode.get("certified") else 0,
                    episode.get("timestamp", datetime.now().isoformat()),
                    episode.get("failure_reason"),
                    episode.get("source"),
                    episode.get("previous_score"),
                    json.dumps(episode.get("strategies_reused", [])),
                    json.dumps(episode.get("skills_unlocked", [])),
                    episode.get("duration_minutes"),
                ),
            )
            conn.commit()
            logger.info("[DB] Episodic record: '%s' score=%s", episode.get("topic"), episode.get("score"))
        except Exception as exc:
            logger.error("[DB] Episodic record failed: %s", exc)


# ── Module-level singleton ────────────────────────────────────────────────────
_instance: Optional[EpisodicMemory] = None

def get_episodic_memory() -> EpisodicMemory:
    global _instance
    if _instance is None:
        _instance = EpisodicMemory()
    return _instance


# ── Backwards-compat shim (replaces the stub in shard/memory/episodic_memory.py) ──

def store_episode(episode: dict) -> None:
    """Drop-in replacement for the stub imported by study_agent."""
    get_episodic_memory().record(episode)
