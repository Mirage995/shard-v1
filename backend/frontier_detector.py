from typing import List


class FrontierDetector:
    def __init__(self, capability_graph, goal_engine=None):
        self.capability_graph = capability_graph
        self.goal_engine = goal_engine

    def get_frontier_skills(self) -> List[str]:
        """
        Return capability frontier candidates.
        Uses capability graph frontier if available, otherwise empty list.
        """
        if not self.capability_graph:
            return []

        if hasattr(self.capability_graph, "get_frontier_capabilities"):
            try:
                skills = self.capability_graph.get_frontier_capabilities() or []
                return [s for s in skills if isinstance(s, str)]
            except Exception:
                return []

        return []
