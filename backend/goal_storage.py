import uuid
from typing import Dict, List, Optional


class Goal:
    """Lightweight Goal record used by the stub GoalStorage/GoalEngine.

    This keeps the existing server/shard APIs working while the legacy
    goal modules are deprecated in favour of the new cognition stack.
    """

    def __init__(
        self,
        title: str,
        description: str = "",
        priority: float = 0.0,
        goal_type: str = "general",
        prerequisites: Optional[List[str]] = None,
    ):
        self.id: str = str(uuid.uuid4())
        self.title = title
        self.description = description
        self.priority = priority
        self.goal_type = goal_type
        self.prerequisites = prerequisites or []
        self.active: bool = False

    def dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "goal_type": self.goal_type,
            "prerequisites": list(self.prerequisites),
            "active": self.active,
        }


class GoalStorage:
    """In-memory goal storage stub.

    Provides the minimal API surface expected by GoalEngine and server/shard
    without requiring the old persistence layer.
    """

    def __init__(self):
        self._goals: Dict[str, Goal] = {}

    def save_goal(self, goal: Goal):
        self._goals[goal.id] = goal

    def list_goals(self) -> List[Goal]:
        return list(self._goals.values())

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

