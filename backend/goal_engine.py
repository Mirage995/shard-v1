from typing import Dict, List, Optional

from goal_storage import GoalStorage, Goal


class GoalEngine:
    """Minimal GoalEngine stub compatible with server/shard/study_agent usage.

    Responsibilities:
    - create/list goals
    - track an active goal id
    - expose a capability_graph slot (injected by StudyAgent when present)
    - provide on_capability_added hook to satisfy listener registration
    """

    def __init__(self, storage: GoalStorage, capability_graph=None):
        self.storage = storage
        self.capability_graph = capability_graph
        self.active_goal_id: Optional[str] = None

    # --- Goal CRUD ---------------------------------------------------------
    def create_goal(
        self,
        title: str,
        description: str = "",
        priority: float = 0.0,
        goal_type: str = "general",
        prerequisites: Optional[List[str]] = None,
    ) -> Goal:
        goal = Goal(
            title=title,
            description=description,
            priority=priority,
            goal_type=goal_type,
            prerequisites=prerequisites or [],
        )
        self.storage.save_goal(goal)
        return goal

    def list_goals(self) -> List[Goal]:
        return self.storage.list_goals()

    def set_active_goal(self, goal_id: str) -> Optional[Goal]:
        goal = self.storage.get_goal(goal_id)
        if goal:
            self.active_goal_id = goal_id
            goal.active = True
        return goal

    # --- Capability graph listener ----------------------------------------
    def on_capability_added(self, capability_name: str):
        """Hook invoked by CapabilityGraph when a capability is added.

        For now we no-op but keep signature for compatibility.
        """
        # Placeholder: real logic could link goals to new capability.
        return None

