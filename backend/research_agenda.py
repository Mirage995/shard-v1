import random
from typing import Dict, List, Optional
from experiment_inventor import ExperimentInventor
from frontier_detector import FrontierDetector
from skill_utils import is_valid_topic

# Exploration probability: occasionally attempt harder topics to avoid local minima
EXPLORATION_PROBABILITY = 0.2  # 20% chance to explore difficulty + 2

# Skill -> suggested study topic
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

    def __init__(self, capability_graph, replay_engine=None, goal_engine=None):
        self.capability_graph = capability_graph
        self.replay_engine = replay_engine
        self.goal_engine = goal_engine
        self.experiment_inventor = ExperimentInventor(capability_graph)
        self.frontier_detector = FrontierDetector(capability_graph, goal_engine=goal_engine)
        self.learning_map: Dict[str, str] = dict(DEFAULT_LEARNING_MAP)
        self.last_research: float = 0.0  # epoch timestamp
        
        # Coda prioritaria e Set per deduplicazione ultra-veloce
        self.priority_topics: List[str] = []
        self._priority_set = set()
        print(f"[RESEARCH AGENDA] Initialized with {len(self.learning_map)} skill->topic mappings")

    def add_priority_topic(self, topic: str):
        # Filtro all'ingresso (Evita spazzatura)
        if not is_valid_topic(topic):
            print(f"[AGENDA] Ignoring invalid priority topic: {topic}")
            return
            
        # Deduplicazione sicura
        if topic not in self._priority_set:
            self.priority_topics.append(topic)
            self._priority_set.add(topic)

    def choose_next_topic(self, goal_prereqs: Optional[List[str]] = None) -> Optional[Dict[str, str]]:
        """Pick a random missing skill and return its study topic."""

        topic_data = None

        # Priority 0: Critic feedback (Highest priority)
        if self.priority_topics:
            topic = self.priority_topics.pop(0)
            self._priority_set.discard(topic)  # Libera il set per il futuro
            print(f"[RESEARCH] Using priority topic from critic feedback: {topic}")
            topic_data = {"skill": topic, "topic": topic, "difficulty": 1}

        # Priority 1: Replay topics (Waterfall Fallback)
        if not topic_data and self.replay_engine:
            replay_topic = self.replay_engine.get_next_replay_topic()
            if replay_topic and is_valid_topic(replay_topic):
                # Skip and evict if already certified
                _caps = getattr(self.capability_graph, "capabilities", {})
                if replay_topic.lower() in {c.lower() for c in _caps}:
                    print(f"[RESEARCH AGENDA] Replay topic '{replay_topic}' already certified -- evicting")
                    self.replay_engine.remove_topic(replay_topic)
                    replay_topic = None
            if replay_topic:
                print(f"[RESEARCH AGENDA] Selected replay topic: {replay_topic}")
                topic_data = {"skill": replay_topic, "topic": replay_topic, "difficulty": 1}

        # Priority 2: Goal gaps
        if not topic_data and goal_prereqs:
            try:
                _all_caps = {c.lower() for c in getattr(self.capability_graph, "capabilities", {}).keys()}
                goal_missing = [s for s in goal_prereqs if s.lower() not in _all_caps]
                if goal_missing:
                    skill = random.choice(goal_missing)
                    topic = self.learning_map.get(skill) or skill
                    print(f"[RESEARCH AGENDA] Selected goal prerequisite: {skill} -> {topic}")
                    topic_data = {"skill": skill, "topic": topic, "difficulty": 1}
            except Exception as e:
                print(f"[RESEARCH AGENDA] Could not extract goal gaps: {e}")

        # Priority 3: FRONTIER DETECTOR & EXPERIMENT INVENTOR
        if not topic_data:
            try:
                # Trova i confini della conoscenza di SHARD
                if hasattr(self.frontier_detector, "get_frontier_skills"):
                    frontier_skills = self.frontier_detector.get_frontier_skills()
                else:
                    frontier_skills = []

                if frontier_skills:
                    target_skill = random.choice(frontier_skills)
                    # Usa l'inventore per creare un topic complesso
                    invented_topics = self.experiment_inventor.invent_experiments(target_skill)
                    
                    # Controllo di tipo robusto
                    if isinstance(invented_topics, list) and invented_topics:
                        chosen_topic = random.choice(invented_topics)
                        
                        # Lancio dei dadi stocastico per la difficoltà (20% chance per diff 3)
                        difficulty = 3 if random.random() < EXPLORATION_PROBABILITY else 2
                        
                        print(f"[RESEARCH AGENDA] INVENTED new topic on frontier: {target_skill} -> {chosen_topic} (Diff: {difficulty})")
                        topic_data = {"skill": target_skill, "topic": chosen_topic, "difficulty": difficulty}
                    else:
                        print(f"[RESEARCH AGENDA] Inventor failed to return a valid list for: {target_skill}")
            except Exception as e:
                print(f"[RESEARCH AGENDA] Frontier/Inventor skipped: {e}")

        # Priority 4: Absolute Fallback (uncertified skills from learning_map)
        if not topic_data:
            try:
                _all_caps = {c.lower() for c in getattr(self.capability_graph, "capabilities", {}).keys()}
                _uncert = [s for s in self.learning_map if s.lower() not in _all_caps]
                if _uncert:
                    skill = random.choice(_uncert)
                    topic = self.learning_map.get(skill) or skill
                    topic_data = {"skill": skill, "topic": topic, "difficulty": 1}
            except Exception:
                pass

        # --- VALIDAZIONE FINALE (L'Exit Gate) ---
        if topic_data:
            if not is_valid_topic(topic_data["topic"]):
                print(f"[AGENDA] Discarding invalid topic at exit gate: {topic_data['topic']}")
                return None
            return topic_data

        return None

    def get_frontier_topics(self, limit: int = 5) -> List[str]:
        """Return top frontier topics for capability introspection."""
        topics: List[str] = []

        try:
            if hasattr(self.frontier_detector, "get_frontier_skills"):
                skills = self.frontier_detector.get_frontier_skills() or []
            else:
                skills = []

            for skill in skills:
                mapped = self.learning_map.get(skill) or skill
                topics.append(mapped)
                if len(topics) >= limit:
                    break
        except Exception:
            pass

        if not topics:
            try:
                missing = self.capability_graph.get_frontier_capabilities()
                for skill in missing[:limit]:
                    topics.append(self.learning_map.get(skill) or skill)
            except Exception:
                pass

        return topics[:limit]
