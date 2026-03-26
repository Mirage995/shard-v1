"""goal_engine.py — SHARD's goal management and topic steering engine.

Goals are not decorations. They actively steer what SHARD studies.
When a goal is active, topic selection in NightRunner biases toward
topics that close the gap between current capabilities and the goal.

Goals are persisted to shard_memory/goals.json and survive across sessions.

Usage:
    engine = GoalEngine(storage, capability_graph)
    engine.create_goal("master distributed systems", domain_keywords=["distributed", "consensus", "raft", "kafka"])
    engine.set_active_goal(goal_id)

    # In NightRunner topic selection:
    ranked = engine.steer(candidates=["asyncio", "raft consensus", "sorting"])
    # → ["raft consensus", "asyncio", "sorting"]  (goal-aligned first)
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_ROOT      = Path(__file__).resolve().parents[1]
_MEMORY    = _ROOT / "shard_memory"
_GOALS_PATH = _MEMORY / "goals.json"


class Goal:
    """A persistent, steering-capable goal."""

    def __init__(
        self,
        title: str,
        description: str = "",
        priority: float = 1.0,
        goal_type: str = "skill",
        domain_keywords: Optional[List[str]] = None,
        prerequisites: Optional[List[str]] = None,
        goal_id: Optional[str] = None,
        created_at: Optional[str] = None,
        progress: float = 0.0,
        active: bool = False,
        completed: bool = False,
        completed_at: Optional[str] = None,
    ):
        self.id = goal_id or str(uuid.uuid4())
        self.title = title
        self.description = description
        self.priority = priority
        self.goal_type = goal_type
        # Keywords that define which topics are relevant to this goal
        self.domain_keywords: List[str] = domain_keywords or _infer_keywords(title)
        self.prerequisites = prerequisites or []
        self.created_at = created_at or datetime.now().isoformat()
        self.progress = progress       # 0.0–1.0, computed from capability graph
        self.active = active
        self.completed = completed
        self.completed_at = completed_at

    def alignment_score(self, topic: str) -> float:
        """How well does this topic align with the goal? 0.0–1.0."""
        topic_lower = topic.lower()
        topic_tokens = set(re.split(r"[\s\-_/]+", topic_lower))
        matches = 0
        for kw in self.domain_keywords:
            kw_lower = kw.lower()
            if kw_lower in topic_lower:
                matches += 2  # substring match is stronger
            elif any(kw_lower in tok for tok in topic_tokens):
                matches += 1
        return min(1.0, matches / max(len(self.domain_keywords), 1))

    def compute_progress(self, capability_graph) -> float:
        """What fraction of this goal's domain is certified in the capability graph?"""
        if not self.domain_keywords:
            return 0.0
        try:
            if hasattr(capability_graph, "capabilities"):
                known = set(k.lower() for k in capability_graph.capabilities.keys())
            else:
                known = set()
            aligned = sum(
                1 for kw in self.domain_keywords
                if any(kw.lower() in k for k in known)
            )
            return round(aligned / len(self.domain_keywords), 3)
        except Exception:
            return 0.0

    def dict(self) -> Dict:
        return {
            "id":              self.id,
            "title":           self.title,
            "description":     self.description,
            "priority":        self.priority,
            "goal_type":       self.goal_type,
            "domain_keywords": self.domain_keywords,
            "prerequisites":   self.prerequisites,
            "created_at":      self.created_at,
            "progress":        self.progress,
            "active":          self.active,
            "completed":       self.completed,
            "completed_at":    self.completed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        return cls(
            title=d.get("title", ""),
            description=d.get("description", ""),
            priority=d.get("priority", 1.0),
            goal_type=d.get("goal_type", "skill"),
            domain_keywords=d.get("domain_keywords"),
            prerequisites=d.get("prerequisites"),
            goal_id=d.get("id"),
            created_at=d.get("created_at"),
            progress=d.get("progress", 0.0),
            active=d.get("active", False),
            completed=d.get("completed", False),
            completed_at=d.get("completed_at"),
        )


def _infer_keywords(title: str) -> List[str]:
    """Extract meaningful keywords from a goal title."""
    stopwords = {"of", "and", "in", "the", "a", "an", "to", "for", "with", "on", "at"}
    tokens = re.split(r"[\s\-_/]+", title.lower())
    return [t for t in tokens if len(t) > 2 and t not in stopwords]


class GoalStorage:
    """Persistent goal storage backed by shard_memory/goals.json."""

    def __init__(self):
        self._goals: Dict[str, Goal] = {}
        self._load()

    def _load(self):
        if _GOALS_PATH.exists():
            try:
                raw = json.loads(_GOALS_PATH.read_text(encoding="utf-8"))
                for d in raw:
                    g = Goal.from_dict(d)
                    self._goals[g.id] = g
            except Exception:
                pass

    def _save(self):
        _GOALS_PATH.parent.mkdir(exist_ok=True)
        data = [g.dict() for g in self._goals.values()]
        _GOALS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def save_goal(self, goal: Goal):
        self._goals[goal.id] = goal
        self._save()

    def list_goals(self) -> List[Goal]:
        return list(self._goals.values())

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    def delete_goal(self, goal_id: str):
        self._goals.pop(goal_id, None)
        self._save()


class GoalEngine:
    """GoalEngine with real topic steering.

    When an active goal exists, topic selection is biased toward
    topics that advance that goal. Topics with zero alignment are
    not blocked — they just get lower priority.
    """

    def __init__(self, storage: GoalStorage, capability_graph=None):
        self.storage = storage
        self.capability_graph = capability_graph
        # Find active goal from persistent storage
        active = [g for g in storage.list_goals() if g.active and not g.completed]
        self.active_goal_id: Optional[str] = active[0].id if active else None

    # ── Goal CRUD ──────────────────────────────────────────────────────────────

    def create_goal(
        self,
        title: str,
        description: str = "",
        priority: float = 1.0,
        goal_type: str = "skill",
        domain_keywords: Optional[List[str]] = None,
        prerequisites: Optional[List[str]] = None,
    ) -> Goal:
        goal = Goal(
            title=title,
            description=description,
            priority=priority,
            goal_type=goal_type,
            domain_keywords=domain_keywords,
            prerequisites=prerequisites,
        )
        self.storage.save_goal(goal)
        return goal

    def list_goals(self) -> List[Goal]:
        return self.storage.list_goals()

    def set_active_goal(self, goal_id: str) -> Optional[Goal]:
        # Deactivate all others
        for g in self.storage.list_goals():
            if g.active:
                g.active = False
                self.storage.save_goal(g)
        goal = self.storage.get_goal(goal_id)
        if goal:
            goal.active = True
            self.active_goal_id = goal_id
            self.storage.save_goal(goal)
        return goal

    def get_active_goal(self) -> Optional[Goal]:
        if not self.active_goal_id:
            return None
        return self.storage.get_goal(self.active_goal_id)

    def complete_goal(self, goal_id: str):
        goal = self.storage.get_goal(goal_id)
        if goal:
            goal.completed = True
            goal.active = False
            goal.completed_at = datetime.now().isoformat()
            if self.active_goal_id == goal_id:
                self.active_goal_id = None
            self.storage.save_goal(goal)

    def update_progress(self) -> Optional[float]:
        """Recompute progress for active goal. Returns new progress or None."""
        goal = self.get_active_goal()
        if not goal or not self.capability_graph:
            return None
        goal.progress = goal.compute_progress(self.capability_graph)
        self.storage.save_goal(goal)
        if goal.progress >= 1.0:
            self.complete_goal(goal.id)
        return goal.progress

    # ── Topic steering ─────────────────────────────────────────────────────────

    def steer(self, candidates: List[str]) -> List[str]:
        """Reorder topic candidates so goal-aligned topics come first.

        Topics with alignment > 0 are sorted to the top, preserving
        relative order within each tier. Topics with zero alignment
        are kept but pushed to the end.
        """
        goal = self.get_active_goal()
        if not goal:
            return candidates

        def score(topic: str) -> float:
            return goal.alignment_score(topic) * goal.priority

        aligned   = sorted([t for t in candidates if score(t) > 0], key=score, reverse=True)
        unaligned = [t for t in candidates if score(t) == 0]
        return aligned + unaligned

    def best_aligned_topic(self, candidates: List[str]) -> Optional[str]:
        """Return the single best goal-aligned topic, or None if no alignment."""
        goal = self.get_active_goal()
        if not goal:
            return None
        scored = [(t, goal.alignment_score(t)) for t in candidates]
        best = max(scored, key=lambda x: x[1], default=(None, 0))
        return best[0] if best[1] > 0.1 else None

    def goal_summary(self) -> str:
        """One-line summary of the active goal for logging."""
        goal = self.get_active_goal()
        if not goal:
            return "No active goal"
        return (
            f"Goal: '{goal.title}' | "
            f"progress={round(goal.progress*100)}% | "
            f"keywords={goal.domain_keywords[:3]}"
        )

    # ── Autonomous goal generation ─────────────────────────────────────────────

    def autonomous_generate(self) -> Optional["Goal"]:
        """SHARD decides its own next goal — no human input.

        Logic:
          1. If an active non-completed goal exists with < 80% progress → keep it.
          2. Read self_model: momentum, blind_spots, certification_rate.
          3. Read world_model: top priority gaps SHARD doesn't know yet.
          4. Cross-reference blind spots with world relevance to pick the most
             urgent goal:
               - momentum=stagnating → foundational skill with highest relevance
               - momentum=accelerating → ambitious skill with highest xp_leverage
               - momentum=stable/early → highest world priority gap overall
          5. Create the goal, activate it, persist it.

        Returns the newly created (or existing) active goal.
        """
        # Keep existing active goal if meaningful progress still to make
        current = self.get_active_goal()
        if current and not current.completed:
            progress = current.compute_progress(self.capability_graph) if self.capability_graph else current.progress
            if progress < 0.8:
                return current  # still working toward it

        # Load self model
        try:
            from self_model import SelfModel
            sm = SelfModel.load_or_build()
            momentum      = sm.momentum
            blind_spots   = set(sm.blind_spots)
            known_skills  = set(sm.strengths)
            cert_rate     = sm.certification_rate
        except Exception:
            momentum, blind_spots, known_skills, cert_rate = "unknown", set(), set(), 0.0

        # Load world model
        try:
            from world_model import WorldModel, _SEED, _DOMAIN_PRIORITY
            wm = WorldModel.load_or_default()
            wm_gaps = wm.priority_gaps(known_skills, top_n=20)
        except Exception:
            wm_gaps = []

        if not wm_gaps:
            return current  # nothing to do

        # Pick strategy based on momentum
        if momentum == "stagnating":
            # Go foundational — easiest high-relevance skill to build confidence
            candidate = min(wm_gaps, key=lambda g: -(g["relevance"] - g["xp_leverage"] * 0.1))
            strategy  = "foundational (stagnating momentum - rebuild confidence)"
        elif momentum == "accelerating":
            # Go ambitious — highest leverage skill
            candidate = max(wm_gaps, key=lambda g: g["xp_leverage"] * g["relevance"])
            strategy  = "ambitious (accelerating momentum - push harder)"
        else:
            # Stable/early — highest overall priority
            candidate = wm_gaps[0]
            strategy  = "priority-driven (stable momentum - highest ROI gap)"

        skill     = candidate["skill"]
        domain    = candidate["domain"]
        relevance = candidate["relevance"]

        # Build domain keywords from the skill name + domain
        try:
            from world_model import _SEED
            seed_entry  = _SEED.get(skill, {})
        except Exception:
            seed_entry = {}

        keywords = list(set(
            re.split(r"[\s\-_]+", skill.lower()) +
            re.split(r"[\s\-_]+", domain.lower())
        ))
        keywords = [k for k in keywords if len(k) > 2][:8]

        title = f"master: {skill}"
        description = (
            f"Autonomous goal — {strategy}.\n"
            f"World relevance: {round(relevance*100)}%  domain: {domain}\n"
            f"SHARD cert_rate={round(cert_rate*100)}%  momentum={momentum}"
        )

        goal = self.create_goal(
            title=title,
            description=description,
            priority=round(relevance, 3),
            goal_type="autonomous",
            domain_keywords=keywords,
        )
        self.set_active_goal(goal.id)
        return goal

    # ── Capability graph listener (backward compat) ────────────────────────────

    def on_capability_added(self, capability_name: str):
        """Hook invoked by CapabilityGraph when a capability is added."""
        self.update_progress()
