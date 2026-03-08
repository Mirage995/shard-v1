"""Autonomous Research Agenda — Decides what SHARD should study next.

Analyzes CapabilityGraph to find missing skills, maps them to study topics,
and schedules research with a cooldown. No LLM calls — purely rule-based.
"""
import time
import json
import os
import random
from typing import Dict, List, Optional
from experiment_inventor import ExperimentInventor


# Skill → suggested study topic
DEFAULT_LEARNING_MAP: Dict[str, str] = {
    "numerical_computation": "NumPy fundamentals",
    "data_manipulation": "Pandas data analysis",
    "vectorized_algorithms": "vectorized linear algebra",
    "iterative_algorithm_design": "gradient descent algorithms",
    "recursive_algorithm_design": "recursive algorithms and dynamic programming",
    "systematic_debugging": "Python debugging techniques",
    "test_driven_development": "pytest and testing patterns",
    "performance_evaluation": "algorithm benchmarking",
    "minimal_prototyping": "rapid prototyping in Python",
    "safe_code_execution": "secure sandbox execution",
    "asynchronous_programming": "Python async/await concurrency patterns",
    "api_integration": "REST API design patterns",
    "http_communication": "HTTP protocol fundamentals",
    "data_serialization": "JSON and data serialization formats",
    "tabular_data_processing": "CSV processing and data pipelines",
    "database_querying": "SQL and database fundamentals",
    "pattern_matching": "regular expressions and text parsing",
    "object_oriented_design": "OOP design patterns in Python",
    "metaprogramming": "Python decorators and metaclasses",
    "functional_programming": "functional programming in Python",
    "containerization": "Docker containerization basics",
    "version_control": "Git advanced workflows",
    "error_handling": "Python exception handling best practices",
    "observability": "logging and monitoring patterns",
    "concurrent_programming": "Python threading and concurrency",
    "parallel_computing": "multiprocessing and parallel algorithms",
    "realtime_communication": "WebSocket communication patterns",
    "data_visualization": "data visualization with matplotlib",
    "web_scraping": "web scraping with BeautifulSoup",
    "machine_learning": "machine learning fundamentals with scikit-learn",
    "deep_learning": "neural networks and deep learning basics",
}

# Cooldown: 2 hours between autonomous studies
RESEARCH_COOLDOWN = 7200


class ResearchAgenda:
    """Analyzes capability gaps and schedules autonomous research."""

    def __init__(self, capability_graph, replay_engine=None):
        self.capability_graph = capability_graph
        self.replay_engine = replay_engine
        self.experiment_inventor = ExperimentInventor(capability_graph)
        self.learning_map: Dict[str, str] = dict(DEFAULT_LEARNING_MAP)
        self.last_research: float = 0.0  # epoch timestamp
        print(f"[RESEARCH AGENDA] Initialized with {len(self.learning_map)} skill→topic mappings")

    def missing_skills(self) -> List[str]:
        """Return skills in the learning map not yet in the capability graph."""
        return [
            skill for skill in self.learning_map
            if not self.capability_graph.has_capability(skill)
        ]

    def choose_next_topic(self) -> Optional[Dict[str, str]]:
        """Pick a random missing skill and return its study topic."""
        missing = self.missing_skills()
        if not missing:
            print("[RESEARCH AGENDA] All skills acquired! Nothing to study.")
            return None

        # Sort missing skills to iterate
        missing.sort(key=lambda s: len(s))
        
        # Parse history to detect timeouts / failures
        history_file = os.path.join(os.path.dirname(__file__), 'logs', 'experiment_history.json')
        topic_fails, topic_zeros = {}, {}
        if os.path.exists(history_file):
            try:
                with open(history_file, "r") as f:
                    lines = f.readlines()
                    for line in lines:
                        if not line.strip(): continue
                        data = json.loads(line)
                        t = data.get("topic", "")
                        score = float(data.get("score", 0.0))
                        
                        if score < 5.0:
                            topic_fails[t] = topic_fails.get(t, 0) + 1
                        else:
                            topic_fails[t] = 0  # reset if succeded
                            
                        if score == 0.0:
                            topic_zeros[t] = topic_zeros.get(t, 0) + 1
                        else:
                            topic_zeros[t] = 0
            except Exception as e:
                print(f"[RESEARCH AGENDA] History read error: {e}")

        for skill in missing:
            topic = self.learning_map[skill]
            fails = topic_fails.get(topic, 0)
            zeros = topic_zeros.get(topic, 0)
            
            if zeros >= 2:
                print(f"[RESEARCH AGENDA] Topic saltato (sandbox timeout ripetuto): {topic}")
                continue
            if fails >= 3:
                print(f"[RESEARCH AGENDA] Topic saltato (fallimenti recenti): {topic}")
                continue
                
            return {"skill": skill, "topic": topic}
            
        print("[RESEARCH AGENDA] All remaining skills are on cooldown due to recent failures.")
        return None

    def should_research(self) -> bool:
        """Check if enough time has passed since the last autonomous study."""
        return (time.time() - self.last_research) > RESEARCH_COOLDOWN

    def schedule_research(self) -> Optional[Dict[str, str]]:
        """Schedule a new autonomous research task if cooldown has elapsed.

        Priority: replay failed experiments first, then study new skills.
        Returns dict with {skill, topic} or None if not ready.
        """
        if not self.should_research():
            return None

        # Priority 1: replay failed experiments
        if self.replay_engine:
            topic = self.replay_engine.next_replay_topic()
            if topic:
                self.last_research = time.time()
                print(f"[RESEARCH AGENDA] Replaying failed experiment: {topic}")
                return {"skill": "replay", "topic": topic}

        # Priority 2: study new skills
        task = self.choose_next_topic()
        if task:
            self.last_research = time.time()
            print(f"[RESEARCH AGENDA] New autonomous research scheduled")
            print(f"  skill target: {task['skill']}")
            print(f"  topic: {task['topic']}")
            return task

        # Priority 3: Invent new experiment (combine 2 known skills)
        experiment = self.experiment_inventor.invent_experiment()
        if experiment:
            self.last_research = time.time()
            print("[RESEARCH AGENDA] Invented experiment scheduled")
            return {"skill": "invented", "topic": experiment["topic"]}

        return None
