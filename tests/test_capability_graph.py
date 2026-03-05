"""Tests for CapabilityGraph — capability registration, querying, and strategy updates."""
import sys
import os
import json
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Patch the CAPABILITY_FILE to a temp location for isolated testing
_temp_dir = tempfile.mkdtemp()
_temp_file = os.path.join(_temp_dir, 'test_cap_graph.json')

import capability_graph
capability_graph.CAPABILITY_FILE = _temp_file


class TestCapabilityGraph(unittest.TestCase):
    def setUp(self):
        # Clear the temp file before each test
        if os.path.exists(_temp_file):
            os.remove(_temp_file)

    def _make_graph(self):
        from capability_graph import CapabilityGraph
        return CapabilityGraph()

    def test_empty_graph(self):
        g = self._make_graph()
        self.assertEqual(len(g.get_all()), 0)

    def test_add_capability(self):
        g = self._make_graph()
        g.add_capability("Python Async", source_topic="async study")
        self.assertTrue(g.has_capability("Python Async"))
        self.assertTrue(g.has_capability("python async"))  # Case insensitive

    def test_no_duplicate(self):
        g = self._make_graph()
        g.add_capability("Git")
        g.add_capability("Git")  # Should not duplicate
        self.assertEqual(len(g.get_all()), 1)

    def test_missing_requirements(self):
        g = self._make_graph()
        g.add_capability("Flask", requires=["Python", "HTTP"])
        g.add_capability("Python")
        missing = g.missing_requirements("Flask")
        self.assertEqual(missing, ["HTTP"])

    def test_missing_requirements_unknown_capability(self):
        g = self._make_graph()
        missing = g.missing_requirements("Unknown")
        self.assertEqual(missing, ["Unknown"])

    def test_persistence(self):
        g1 = self._make_graph()
        g1.add_capability("Docker")
        # Create a new instance — should load from disk
        g2 = self._make_graph()
        self.assertTrue(g2.has_capability("Docker"))

    def test_update_from_strategy(self):
        g = self._make_graph()
        strategy = "[Python] Concepts: asyncio, coroutines, event loops | Sandbox: SUCCESS"
        g.update_from_strategy("Python Async", strategy)
        self.assertTrue(g.has_capability("Python Async"))
        self.assertTrue(g.has_capability("asyncio"))
        self.assertTrue(g.has_capability("coroutines"))
        self.assertTrue(g.has_capability("event loops"))

    def test_update_from_strategy_no_concepts(self):
        g = self._make_graph()
        strategy = "[Rust] Sandbox: FAILED — compiler error"
        g.update_from_strategy("Rust Basics", strategy)
        self.assertTrue(g.has_capability("Rust Basics"))
        # No sub-capabilities since no "Concepts:" section
        self.assertEqual(len(g.get_all()), 1)

    def test_caps_concepts_at_5(self):
        g = self._make_graph()
        concepts = ", ".join([f"concept{i}" for i in range(10)])
        strategy = f"[Test] Concepts: {concepts} | Done"
        g.update_from_strategy("Test Topic", strategy)
        # Should have: topic + 5 concepts = 6
        self.assertLessEqual(len(g.get_all()), 6)


if __name__ == '__main__':
    unittest.main()
