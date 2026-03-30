import random
from typing import List, Dict, Optional
from skill_utils import is_valid_topic

class ExperimentInventor:
    """Generates new research ideas by combining existing capabilities."""

    def __init__(self, capability_graph):
        self.capability_graph = capability_graph

    def _capabilities(self) -> List[str]:
        if not self.capability_graph:
            return []
        if hasattr(self.capability_graph, 'capabilities'):
            return list(self.capability_graph.capabilities.keys())
        return []

    def invent_experiments(self, target_skill: str) -> List[str]:
        """Create new experiment ideas combining the target skill with others."""
        caps = self._capabilities()

        # Depth guard: never nest composite topics further.
        # "Integration of X and Y" is depth-1 -- stop there.
        if target_skill.lower().startswith("integration of "):
            return []

        # Only use atomic capabilities as partners -- never composite ones.
        # This prevents "Integration of (Integration of X) and Y" chains.
        other_caps = [
            c for c in caps
            if c != target_skill and not c.lower().startswith("integration of ")
        ]
        
        # Fallback: no other capabilities available -- generate an advanced pattern
        if not other_caps:
            return [f"Advanced {target_skill} implementation patterns"]

        # Proviamo a generare fino a 3 idee combinando skill diverse
        ideas = []
        sample_size = min(3, len(other_caps))
        partners = random.sample(other_caps, sample_size)

        # Inizializza il set dei topic inventati se non esiste
        if not hasattr(self.capability_graph, "invented_topics"):
            self.capability_graph.invented_topics = set()

        for partner in partners:
            topic = f"Integration of {target_skill} and {partner}"

            # Evita combinazioni duplicate globali
            if topic in self.capability_graph.invented_topics:
                continue

            # Applica il filtro magico (Il "Buttafuori" di is_valid_topic)
            if is_valid_topic(topic):
                self.capability_graph.invented_topics.add(topic)
                ideas.append(topic)
            else:
                print(f"[INVENTOR] Discarded low-quality hypothesis: {topic}")

        if ideas:
            print(f"[EXPERIMENT INVENTOR] Generated {len(ideas)} valid hypotheses for {target_skill}")

        return ideas
