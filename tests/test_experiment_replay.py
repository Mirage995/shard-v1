"""Tests for ExperimentReplay — logging, failed detection, and replay selection."""
import sys
import os
import json
import unittest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from experiment_replay import ExperimentReplay


class TestExperimentReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix='.json')
        self.engine = ExperimentReplay(file_path=self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_creates_file_on_init(self):
        self.assertTrue(os.path.exists(self.tmp))
        with open(self.tmp, 'r') as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_log_experiment(self):
        self.engine.log_experiment("Python basics", score=9.0, success=True)
        with open(self.tmp, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["topic"], "Python basics")
        self.assertEqual(data[0]["score"], 9.0)
        self.assertTrue(data[0]["success"])
        self.assertIn("timestamp", data[0])

    def test_log_multiple(self):
        self.engine.log_experiment("Topic A", score=5.0, success=False)
        self.engine.log_experiment("Topic B", score=9.0, success=True)
        with open(self.tmp, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_failed_experiments(self):
        self.engine.log_experiment("Good", score=9.0, success=True)
        self.engine.log_experiment("Bad", score=5.0, success=False)
        self.engine.log_experiment("Meh", score=7.5, success=False)
        failed = self.engine.failed_experiments()
        self.assertEqual(len(failed), 2)
        topics = [e["topic"] for e in failed]
        self.assertIn("Bad", topics)
        self.assertIn("Meh", topics)
        self.assertNotIn("Good", topics)

    def test_failed_experiments_threshold(self):
        """Score exactly 8.0 should NOT be considered failed."""
        self.engine.log_experiment("Edge", score=8.0, success=True)
        self.assertEqual(len(self.engine.failed_experiments()), 0)

    def test_choose_replay_lowest_first(self):
        self.engine.log_experiment("Low", score=3.0, success=False)
        self.engine.log_experiment("Mid", score=6.0, success=False)
        replay = self.engine.choose_replay()
        self.assertIsNotNone(replay)
        self.assertEqual(replay["topic"], "Low")

    def test_choose_replay_none_when_all_pass(self):
        self.engine.log_experiment("Good", score=9.0, success=True)
        self.assertIsNone(self.engine.choose_replay())

    def test_choose_replay_empty_history(self):
        self.assertIsNone(self.engine.choose_replay())

    def test_next_replay_topic(self):
        self.engine.log_experiment("Fail", score=4.0, success=False)
        topic = self.engine.next_replay_topic()
        self.assertEqual(topic, "Fail")

    def test_next_replay_topic_none(self):
        self.engine.log_experiment("Pass", score=9.0, success=True)
        self.assertIsNone(self.engine.next_replay_topic())

    def test_persistence_across_instances(self):
        self.engine.log_experiment("Data", score=6.0, success=False)
        engine2 = ExperimentReplay(file_path=self.tmp)
        failed = engine2.failed_experiments()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["topic"], "Data")


if __name__ == '__main__':
    unittest.main()
