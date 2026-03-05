"""Tests for SkillDiscovery — pattern-based skill detection."""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Use a simple mock for CapabilityGraph to isolate SkillDiscovery tests
class MockCapabilityGraph:
    def __init__(self):
        self.capabilities = {}
    def has_capability(self, name):
        return name.lower().strip() in self.capabilities
    def add_capability(self, name, requires=None, source_topic=""):
        self.capabilities[name.lower().strip()] = {"requires": requires or [], "source_topic": source_topic}

from skill_discovery import SkillDiscovery


class TestAnalyzeStrategy(unittest.TestCase):
    def setUp(self):
        self.graph = MockCapabilityGraph()
        self.sd = SkillDiscovery(self.graph)

    def test_empty_strategy(self):
        self.assertEqual(self.sd.analyze_strategy(""), [])
        self.assertEqual(self.sd.analyze_strategy(None), [])

    def test_single_keyword(self):
        result = self.sd.analyze_strategy("Used numpy for matrix ops")
        self.assertIn("numerical_computation", result)

    def test_multiple_keywords(self):
        result = self.sd.analyze_strategy("Used numpy vectorized loop benchmark")
        self.assertIn("numerical_computation", result)
        self.assertIn("vectorized_algorithms", result)
        self.assertIn("iterative_algorithm_design", result)
        self.assertIn("performance_evaluation", result)

    def test_case_insensitive(self):
        result = self.sd.analyze_strategy("NUMPY and DEBUG and Docker")
        self.assertIn("numerical_computation", result)
        self.assertIn("systematic_debugging", result)
        self.assertIn("containerization", result)

    def test_deduplicated(self):
        # async and await both map to asynchronous_programming
        result = self.sd.analyze_strategy("async await pattern")
        self.assertEqual(result.count("asynchronous_programming"), 1)

    def test_no_match(self):
        result = self.sd.analyze_strategy("something completely unrelated xyz")
        self.assertEqual(result, [])

    def test_no_false_positive_on_partial_word(self):
        """'loopback' should NOT match 'loop'."""
        result = self.sd.analyze_strategy("configured loopback interface")
        self.assertNotIn("iterative_algorithm_design", result)


class TestDiscoverFromExperiment(unittest.TestCase):
    def setUp(self):
        self.graph = MockCapabilityGraph()
        self.sd = SkillDiscovery(self.graph)

    def test_discovers_new_skills(self):
        new = self.sd.discover_from_experiment("Python", "Used numpy and test framework")
        self.assertIn("numerical_computation", new)
        self.assertIn("test_driven_development", new)
        # Should now be in the graph
        self.assertTrue(self.graph.has_capability("numerical_computation"))

    def test_skips_existing_skills(self):
        self.graph.add_capability("numerical_computation")
        new = self.sd.discover_from_experiment("Python", "Used numpy for computation")
        self.assertNotIn("numerical_computation", new)

    def test_registers_with_topic_as_prerequisite(self):
        self.sd.discover_from_experiment("Data Science", "Used pandas for analysis")
        cap = self.graph.capabilities.get("data_manipulation")
        self.assertIsNotNone(cap)
        self.assertIn("Data Science", cap["requires"])

    def test_returns_empty_for_no_matches(self):
        new = self.sd.discover_from_experiment("Topic", "nothing special here")
        self.assertEqual(new, [])


if __name__ == '__main__':
    unittest.main()
