"""Semantic Experiment Cache — skip failed topics until SHARD learns new skills.

Storage: shard_memory/shard.db (failed_cache table).
Fallback: reads legacy failed_cache.json if DB is unavailable.
"""
import logging

logger = logging.getLogger("shard.experiment_cache")


def _get_db():
    """Lazy import to avoid circular deps at module load time."""
    from shard_db import get_db
    return get_db()


class SemanticExperimentCache:
    """Stores failed experiments to avoid repeating them
    UNLESS the agent has acquired new capabilities.
    """

    def __init__(self, filepath="shard_memory/failed_cache.json"):
        self.filepath = filepath  # kept for fallback only
        self.failed_cache = self._load_cache()

    def _load_cache(self):
        """Load from SQLite, fallback to JSON."""
        try:
            conn = _get_db()
            rows = conn.execute("SELECT topic, skill_count_at_fail FROM failed_cache").fetchall()
            cache = {r["topic"]: r["skill_count_at_fail"] for r in rows}
            logger.info("[DB] Loaded %d failed_cache entries from SQLite", len(cache))
            return cache
        except Exception as exc:
            logger.warning("[DB] failed_cache SQLite load failed (%s), falling back to JSON", exc)
            import json, os
            if os.path.exists(self.filepath):
                try:
                    with open(self.filepath, "r") as f:
                        return json.load(f)
                except Exception:
                    return {}
            return {}

    def _save_cache(self):
        """Write to SQLite (INSERT OR REPLACE for upsert)."""
        try:
            conn = _get_db()
            from datetime import datetime
            topic_key = list(self.failed_cache.keys())[-1] if self.failed_cache else None
            if topic_key is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO failed_cache (topic, skill_count_at_fail, last_failed_at) "
                    "VALUES (?, ?, ?)",
                    (topic_key, self.failed_cache[topic_key], datetime.now().isoformat()),
                )
                conn.commit()
        except Exception as exc:
            logger.error("[DB] failed_cache write failed: %s", exc)

    def register_failure(self, topic: str, current_skill_count: int):
        """Store a failed experiment mapped to the number of skills SHARD had at the time."""
        topic_key = topic.lower().strip()
        self.failed_cache[topic_key] = current_skill_count
        # Write directly to DB (more reliable than _save_cache for single entry)
        try:
            conn = _get_db()
            from datetime import datetime
            conn.execute(
                "INSERT OR REPLACE INTO failed_cache (topic, skill_count_at_fail, last_failed_at) "
                "VALUES (?, ?, ?)",
                (topic_key, current_skill_count, datetime.now().isoformat()),
            )
            conn.commit()
            logger.info("[DB] Registered failed experiment: '%s' (skills=%d)", topic, current_skill_count)
        except Exception as exc:
            logger.error("[DB] failed_cache register_failure write failed: %s — in-memory only", exc)
        print(f"[CACHE] Registered failed experiment: '{topic}' (Skills at failure: {current_skill_count})")

    def should_skip(self, topic: str, current_skill_count: int) -> bool:
        """Skip ONLY IF the topic failed previously AND no new skills were learned."""
        topic_key = topic.lower().strip()

        if topic_key in self.failed_cache:
            skills_at_failure = self.failed_cache[topic_key]
            if current_skill_count <= skills_at_failure:
                print(f"[CACHE] Skipping '{topic}': Already failed and no new skills acquired.")
                return True
            else:
                print(f"[CACHE] Allowing retry for '{topic}': {current_skill_count - skills_at_failure} new skills acquired!")
                return False

        return False
