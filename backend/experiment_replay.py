import json
import logging
import os
import random
import tempfile
from typing import Optional

from skill_utils import is_valid_topic

logger = logging.getLogger("shard.experiment_replay")

REPLAY_FILE = os.path.join(
    os.path.dirname(__file__), '..', 'shard_memory', 'experiment_replay.json'
)


class ExperimentReplay:
    """Manages replay of past experiments that scored in the 6.0–7.4 range.

    State is persisted to disk so the PHOENIX Protocol backlog survives restarts.
    Write strategy: atomic rename, same as CapabilityGraph.
    """

    def __init__(self):
        self.history: list[str] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        try:
            if os.path.exists(REPLAY_FILE):
                with open(REPLAY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.history = [t for t in data if isinstance(t, str)]
                    logger.info(
                        "[REPLAY] Loaded %d topics from disk.", len(self.history)
                    )
        except Exception as e:
            logger.warning("[REPLAY] Could not load replay history: %s — starting fresh.", e)
            self.history = []

    def _save(self):
        try:
            target = os.path.realpath(REPLAY_FILE)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8',
                dir=os.path.dirname(target), suffix='.tmp', delete=False
            ) as tf:
                json.dump(self.history, tf, indent=2, ensure_ascii=False)
                tmp_path = tf.name
            os.replace(tmp_path, target)
        except Exception as e:
            logger.error("[REPLAY] Could not save replay history: %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_next_replay_topic(self) -> Optional[str]:
        """Return a random topic from the replay backlog, or None if empty."""
        if not self.history:
            return None
        return random.choice(self.history)

    def add_experiment(self, topic: str):
        """Enqueue a topic for future replay if it passes the quality gate."""
        if not is_valid_topic(topic):
            logger.debug("[REPLAY] Skipping invalid replay topic: %s", topic)
            return
        if topic in self.history:
            return  # already queued — avoid duplicates
        self.history.append(topic)
        self._save()
        logger.debug("[REPLAY] Added replay topic: %s (backlog: %d)", topic, len(self.history))

    def remove_topic(self, topic: str):
        """Remove a topic after it has been successfully replayed."""
        try:
            self.history.remove(topic)
            self._save()
        except ValueError:
            pass

    def __len__(self) -> int:
        return len(self.history)
