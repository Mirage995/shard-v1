"""Tests for ResearchAgenda — topic selection, priority queue, and frontier."""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from research_agenda import ResearchAgenda, DEFAULT_LEARNING_MAP


class MockCapabilityGraph:
    """Minimal capability graph stub that matches the interface ResearchAgenda calls."""

    def __init__(self, known=None):
        self._known = set(k.lower().strip() for k in (known or []))
        self._all = set(DEFAULT_LEARNING_MAP.keys())

    def get_missing_skills(self):
        return list(self._all - self._known)

    def has_capability(self, name):
        return name.lower().strip() in self._known

    def get_frontier_capabilities(self):
        return self.get_missing_skills()[:3]


def _make_agenda(known=None, replay_engine=None):
    """Build a ResearchAgenda with mocked ExperimentInventor and FrontierDetector."""
    graph = MockCapabilityGraph(known=known)
    with patch('research_agenda.ExperimentInventor'), \
         patch('research_agenda.FrontierDetector'):
        agenda = ResearchAgenda(graph, replay_engine=replay_engine)
    return agenda


# ── choose_next_topic ─────────────────────────────────────────────────────────

class TestChooseNextTopic(unittest.TestCase):

    def test_returns_dict_with_skill_and_topic(self):
        agenda = _make_agenda()
        result = agenda.choose_next_topic()
        self.assertIsNotNone(result)
        self.assertIn('skill', result)
        self.assertIn('topic', result)

    def test_skill_comes_from_learning_map(self):
        agenda = _make_agenda()
        result = agenda.choose_next_topic()
        self.assertIn(result['skill'], DEFAULT_LEARNING_MAP)

    def test_returns_none_when_all_skills_acquired(self):
        all_skills = list(DEFAULT_LEARNING_MAP.keys())
        agenda = _make_agenda(known=all_skills)
        result = agenda.choose_next_topic()
        self.assertIsNone(result)

    def test_result_has_difficulty(self):
        agenda = _make_agenda()
        result = agenda.choose_next_topic()
        self.assertIn('difficulty', result)
        self.assertIsInstance(result['difficulty'], int)

    def test_prefers_replay_topic_over_random(self):
        """If replay_engine returns a topic, choose_next_topic uses it."""
        replay = MagicMock()
        replay.get_next_replay_topic.return_value = 'asyncio concurrency patterns'
        agenda = _make_agenda(replay_engine=replay)
        result = agenda.choose_next_topic()
        self.assertIsNotNone(result)
        self.assertEqual(result['topic'], 'asyncio concurrency patterns')

    def test_falls_back_when_replay_empty(self):
        replay = MagicMock()
        replay.get_next_replay_topic.return_value = None
        agenda = _make_agenda(replay_engine=replay)
        result = agenda.choose_next_topic()
        # Falls through to learning_map fallback
        self.assertIsNotNone(result)


# ── add_priority_topic ────────────────────────────────────────────────────────

class TestAddPriorityTopic(unittest.TestCase):

    def test_priority_topic_returned_first(self):
        agenda = _make_agenda()
        agenda.add_priority_topic('asyncio concurrency patterns')
        result = agenda.choose_next_topic()
        self.assertEqual(result['topic'], 'asyncio concurrency patterns')

    def test_duplicate_priority_topic_ignored(self):
        agenda = _make_agenda()
        agenda.add_priority_topic('asyncio concurrency patterns')
        agenda.add_priority_topic('asyncio concurrency patterns')
        self.assertEqual(len(agenda.priority_topics), 1)

    def test_invalid_priority_topic_rejected(self):
        agenda = _make_agenda()
        agenda.add_priority_topic('x')   # too short
        agenda.add_priority_topic('')
        self.assertEqual(len(agenda.priority_topics), 0)

    def test_priority_topics_consumed_in_order(self):
        agenda = _make_agenda()
        agenda.add_priority_topic('asyncio concurrency patterns')
        agenda.add_priority_topic('Python decorator advanced usage')
        r1 = agenda.choose_next_topic()
        r2 = agenda.choose_next_topic()
        self.assertEqual(r1['topic'], 'asyncio concurrency patterns')
        self.assertEqual(r2['topic'], 'Python decorator advanced usage')


# ── get_frontier_topics ───────────────────────────────────────────────────────

class TestGetFrontierTopics(unittest.TestCase):

    def test_returns_list(self):
        agenda = _make_agenda()
        result = agenda.get_frontier_topics()
        self.assertIsInstance(result, list)

    def test_respects_limit(self):
        agenda = _make_agenda()
        result = agenda.get_frontier_topics(limit=2)
        self.assertLessEqual(len(result), 2)

    def test_default_limit_is_five(self):
        agenda = _make_agenda()
        result = agenda.get_frontier_topics()
        self.assertLessEqual(len(result), 5)


# ── learning_map ──────────────────────────────────────────────────────────────

class TestLearningMap(unittest.TestCase):

    def test_initialized_with_default_map(self):
        agenda = _make_agenda()
        self.assertEqual(len(agenda.learning_map), len(DEFAULT_LEARNING_MAP))

    def test_all_map_values_are_non_empty_strings(self):
        for skill, topic in DEFAULT_LEARNING_MAP.items():
            self.assertIsInstance(topic, str)
            self.assertTrue(len(topic) > 0, f"Empty topic for skill: {skill}")


if __name__ == '__main__':
    unittest.main()
