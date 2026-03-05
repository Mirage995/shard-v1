import random
from typing import List, Dict

class ExperimentInventor:
    """
    Generates new research ideas by combining existing capabilities.
    """

    def __init__(self, capability_graph):
        self.capability_graph = capability_graph

    def _capabilities(self) -> List[str]:
        if not self.capability_graph:
            return []
        return list(self.capability_graph.capabilities.keys())

    def invent_experiment(self) -> Dict | None:
        """
        Create a new experiment idea combining two capabilities.
        """
        caps = self._capabilities()

        # Requires a minimum knowledge base to start combining
        if len(caps) < 3:
            return None

        cap_a, cap_b = random.sample(caps, 2)

        topic = f"{cap_a} applied to {cap_b}"

        # Evita combinazioni duplicate
        if topic in getattr(self.capability_graph, "invented_topics", set()):
            print(f"[EXPERIMENT INVENTOR] Skipping duplicate idea: {topic}")
            return None

        self.capability_graph.invented_topics = getattr(
            self.capability_graph, "invented_topics", set()
        )
        self.capability_graph.invented_topics.add(topic)

        experiment = {
            "type": "invented",
            "topic": topic,
            "capabilities": [cap_a, cap_b],
            "tier": 2
        }

        print("[EXPERIMENT INVENTOR] Generated hypothesis")
        print(f"  combine: {cap_a} + {cap_b}")
        print(f"  topic: {topic}")

        return experiment
