"""Experiment Replay Engine — Re-attempts failed studies when new skills are available.

Records all experiment outcomes to a JSON file. When SHARD acquires new
capabilities, it can replay previously failed experiments to improve scores.
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

HISTORY_DIR = os.path.join(os.path.dirname(__file__), '..', 'shard_memory')
DEFAULT_FILE = os.path.join(HISTORY_DIR, 'experiment_history.json')

# Score threshold: experiments below this are considered "failed"
from constants import SUCCESS_SCORE_THRESHOLD


class ExperimentReplay:
    """Tracks experiment history and replays failed ones."""

    def __init__(self, file_path: str = DEFAULT_FILE):
        self.file_path = file_path
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        if not os.path.exists(self.file_path):
            self._save([])
        print(f"[REPLAY] Engine initialized (history: {self.file_path})")

    def _load(self) -> List[Dict]:
        """Load experiment history from disk."""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save(self, history: List[Dict]):
        """Persist experiment history to disk."""
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

    def log_experiment(self, topic: str, score: float, success: bool):
        """Record an experiment outcome."""
        history = self._load()
        entry = {
            "topic": topic,
            "score": score,
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }
        history.append(entry)
        self._save(history)
        print(f"[REPLAY] logged experiment: {topic} (score={score})")

    def failed_experiments(self) -> List[Dict]:
        """Return all experiments with score < SUCCESS_SCORE_THRESHOLD."""
        history = self._load()
        return [e for e in history if e.get("score", 0) < SUCCESS_SCORE_THRESHOLD]

    def choose_replay(self) -> Optional[Dict]:
        """Select the experiment with the lowest score for replay."""
        failed = self.failed_experiments()
        if not failed:
            return None
        failed.sort(key=lambda e: e.get("score", 0))
        return failed[0]

    def next_replay_topic(self) -> Optional[str]:
        """Return the topic of the next experiment to retry, or None."""
        replay = self.choose_replay()
        if replay:
            topic = replay["topic"]
            score = replay.get("score", 0)
            print(f"[REPLAY] retrying experiment '{topic}' (previous score: {score})")
            return topic
        return None
