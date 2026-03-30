"""Automatic Skill Discovery -- Pattern-based skill detection from strategies.

Analyzes successful strategy text to discover implicit skills via keyword
matching. No LLM calls -- purely lightweight pattern detection.
Discovered skills are registered in the CapabilityGraph.
"""
import re
from typing import Dict, List


# Default keyword -> skill mapping
DEFAULT_PATTERN_MAP: Dict[str, str] = {
    "numpy": "numerical_computation",
    "pandas": "data_manipulation",
    "vectorized": "vectorized_algorithms",
    "loop": "iterative_algorithm_design",
    "recursion": "recursive_algorithm_design",
    "debug": "systematic_debugging",
    "sandbox": "safe_code_execution",
    "minimal": "minimal_prototyping",
    "test": "test_driven_development",
    "benchmark": "performance_evaluation",
    "async": "asynchronous_programming",
    "await": "asynchronous_programming",
    "api": "api_integration",
    "http": "http_communication",
    "json": "data_serialization",
    "csv": "tabular_data_processing",
    "sql": "database_querying",
    "regex": "pattern_matching",
    "class": "object_oriented_design",
    "inherit": "object_oriented_design",
    "decorator": "metaprogramming",
    "lambda": "functional_programming",
    "docker": "containerization",
    "git": "version_control",
    "exception": "error_handling",
    "logging": "observability",
    "threading": "concurrent_programming",
    "multiprocess": "parallel_computing",
    "websocket": "realtime_communication",
    "matplotlib": "data_visualization",
    "plotly": "data_visualization",
    "scraping": "web_scraping",
    "beautifulsoup": "web_scraping",
    "machine learning": "machine_learning",
    "neural": "deep_learning",
    "pytorch": "deep_learning",
    "tensorflow": "deep_learning",
}


class SkillDiscovery:
    """Discovers implicit skills from strategy text using keyword matching."""

    def __init__(self, capability_graph):
        self.capability_graph = capability_graph
        self.pattern_map: Dict[str, str] = dict(DEFAULT_PATTERN_MAP)
        print(f"[SKILL DISCOVERY] Initialized with {len(self.pattern_map)} patterns")

    def analyze_strategy(self, strategy: str) -> List[str]:
        """Detect skills from strategy text via keyword matching.

        Returns deduplicated list of skill names found.
        """
        if not strategy:
            return []

        text = strategy.lower()
        found: dict = {}  # skill -> True, preserves insertion order, deduplicates
        for keyword, skill in self.pattern_map.items():
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, text):
                found[skill] = True
        return list(found.keys())

    def discover_from_experiment(self, topic: str, strategy: str) -> List[str]:
        """Analyze strategy and register new skills in the capability graph.

        Returns list of newly discovered skill names.
        """
        skills = self.analyze_strategy(strategy)
        new_skills = []

        for skill in skills:
            if not self.capability_graph.has_capability(skill):
                self.capability_graph.add_capability(
                    skill,
                    requires=[topic],
                    source_topic=topic,
                )
                print(f"[SKILL DISCOVERY] new capability unlocked: {skill}")
                new_skills.append(skill)

        if not new_skills and skills:
            print(f"[SKILL DISCOVERY] No new skills -- {len(skills)} already known")

        return new_skills
