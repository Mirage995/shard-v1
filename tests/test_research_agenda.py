"""Tests for ResearchAgenda — missing skills, topic selection, and cooldown."""
import sys
import os
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))


class MockCapabilityGraph:
    def __init__(self, known=None):
        self.known = set(k.lower().strip() for k in (known or []))
    def has_capability(self, name):
        return name.lower().strip() in self.known


from research_agenda import ResearchAgenda, RESEARCH_COOLDOWN


class TestMissingSkills(unittest.TestCase):
    def test_all_missing_when_empty_graph(self):
        graph = MockCapabilityGraph()
        agenda = ResearchAgenda(graph)
        missing = agenda.missing_skills()
        self.assertEqual(len(missing), len(agenda.learning_map))

    def test_reduces_when_skills_acquired(self):
        graph = MockCapabilityGraph(known=["numerical_computation", "systematic_debugging"])
        agenda = ResearchAgenda(graph)
        missing = agenda.missing_skills()
        self.assertNotIn("numerical_computation", missing)
        self.assertNotIn("systematic_debugging", missing)
        self.assertEqual(len(missing), len(agenda.learning_map) - 2)

    def test_none_missing_when_all_acquired(self):
        graph = MockCapabilityGraph(known=list(ResearchAgenda(MockCapabilityGraph()).learning_map.keys()))
        agenda = ResearchAgenda(graph)
        self.assertEqual(len(agenda.missing_skills()), 0)


class TestChooseNextTopic(unittest.TestCase):
    def test_returns_dict_with_skill_and_topic(self):
        graph = MockCapabilityGraph()
        agenda = ResearchAgenda(graph)
        result = agenda.choose_next_topic()
        self.assertIsNotNone(result)
        self.assertIn("skill", result)
        self.assertIn("topic", result)
        self.assertIn(result["skill"], agenda.learning_map)

    def test_returns_none_when_all_acquired(self):
        all_skills = list(ResearchAgenda(MockCapabilityGraph()).learning_map.keys())
        graph = MockCapabilityGraph(known=all_skills)
        agenda = ResearchAgenda(graph)
        self.assertIsNone(agenda.choose_next_topic())


class TestCooldown(unittest.TestCase):
    def test_should_research_initially(self):
        agenda = ResearchAgenda(MockCapabilityGraph())
        self.assertTrue(agenda.should_research())

    def test_should_not_research_during_cooldown(self):
        agenda = ResearchAgenda(MockCapabilityGraph())
        agenda.last_research = time.time()  # Just researched
        self.assertFalse(agenda.should_research())

    def test_should_research_after_cooldown(self):
        agenda = ResearchAgenda(MockCapabilityGraph())
        agenda.last_research = time.time() - RESEARCH_COOLDOWN - 1
        self.assertTrue(agenda.should_research())


class TestScheduleResearch(unittest.TestCase):
    def test_schedules_when_ready(self):
        agenda = ResearchAgenda(MockCapabilityGraph())
        result = agenda.schedule_research()
        self.assertIsNotNone(result)
        self.assertIn("skill", result)
        self.assertIn("topic", result)

    def test_updates_last_research(self):
        agenda = ResearchAgenda(MockCapabilityGraph())
        before = time.time()
        agenda.schedule_research()
        self.assertGreaterEqual(agenda.last_research, before)

    def test_returns_none_during_cooldown(self):
        agenda = ResearchAgenda(MockCapabilityGraph())
        agenda.schedule_research()  # First call
        result = agenda.schedule_research()  # Immediate second call
        self.assertIsNone(result)

    def test_returns_none_when_all_skills_acquired(self):
        all_skills = list(ResearchAgenda(MockCapabilityGraph()).learning_map.keys())
        graph = MockCapabilityGraph(known=all_skills)
        agenda = ResearchAgenda(graph)
        self.assertIsNone(agenda.schedule_research())


if __name__ == '__main__':
    unittest.main()
