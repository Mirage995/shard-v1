"""Tests for ExperimentReplay — topic queue, deduplication, and persistence."""
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import experiment_replay as _er_module
from experiment_replay import ExperimentReplay


def _make_engine(tmp_path):
    """Return an ExperimentReplay instance backed by a temp file."""
    with patch.object(_er_module, 'REPLAY_FILE', tmp_path):
        engine = ExperimentReplay()
    engine._replay_file = tmp_path  # stash for patch reuse
    return engine


class TestExperimentReplayQueue(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mktemp(suffix='.json')
        self._patcher = patch.object(_er_module, 'REPLAY_FILE', self._tmp)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    def _engine(self):
        return ExperimentReplay()

    # ── add_experiment ────────────────────────────────────────────────────────

    def test_add_valid_topic_increases_len(self):
        e = self._engine()
        e.add_experiment('Python async patterns')
        self.assertEqual(len(e), 1)

    def test_add_duplicate_ignored(self):
        e = self._engine()
        e.add_experiment('Python async patterns')
        e.add_experiment('Python async patterns')
        self.assertEqual(len(e), 1)

    def test_add_invalid_topic_ignored(self):
        """Too-short or empty topics must be rejected by is_valid_topic."""
        e = self._engine()
        e.add_experiment('x')   # too short
        e.add_experiment('')    # empty
        self.assertEqual(len(e), 0)

    def test_add_multiple_topics(self):
        e = self._engine()
        e.add_experiment('asyncio concurrency')
        e.add_experiment('Python decorators')
        self.assertEqual(len(e), 2)

    # ── remove_topic ──────────────────────────────────────────────────────────

    def test_remove_existing_topic(self):
        e = self._engine()
        e.add_experiment('asyncio concurrency')
        e.remove_topic('asyncio concurrency')
        self.assertEqual(len(e), 0)

    def test_remove_nonexistent_topic_does_not_raise(self):
        e = self._engine()
        e.remove_topic('nonexistent topic that was never added')  # must not raise

    # ── get_next_replay_topic ─────────────────────────────────────────────────

    def test_returns_none_on_empty_queue(self):
        e = self._engine()
        self.assertIsNone(e.get_next_replay_topic())

    def test_returns_topic_from_queue(self):
        e = self._engine()
        e.add_experiment('asyncio concurrency')
        result = e.get_next_replay_topic()
        self.assertEqual(result, 'asyncio concurrency')

    def test_returns_one_of_many(self):
        e = self._engine()
        topics = {'asyncio concurrency', 'Python decorators', 'pytest fixtures'}
        for t in topics:
            e.add_experiment(t)
        result = e.get_next_replay_topic()
        self.assertIn(result, topics)

    # ── persistence ───────────────────────────────────────────────────────────

    def test_topics_persist_across_instances(self):
        e1 = self._engine()
        e1.add_experiment('asyncio concurrency')
        # New instance reads from the same file
        e2 = self._engine()
        self.assertEqual(len(e2), 1)
        self.assertIn('asyncio concurrency', e2.history)

    def test_remove_persists_across_instances(self):
        e1 = self._engine()
        e1.add_experiment('asyncio concurrency')
        e1.remove_topic('asyncio concurrency')
        e2 = self._engine()
        self.assertEqual(len(e2), 0)

    def test_empty_queue_on_fresh_instance_no_file(self):
        """If REPLAY_FILE doesn't exist yet, starts empty."""
        e = self._engine()
        self.assertEqual(len(e), 0)


if __name__ == '__main__':
    unittest.main()
