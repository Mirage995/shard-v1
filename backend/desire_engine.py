"""desire_engine.py -- SHARD's want layer.

Four mechanisms that approximate "wanting" rather than pure optimization:

1. Goal persistence   -- active goals resist replacement until mature (sessions_active threshold)
2. Frustration drive  -- non-junk failures increase desire_score, not just quarantine
3. Lateral curiosity  -- certification triggers semantic search for adjacent unexplored topics
4. Process reward     -- engagement_score tracks session richness independent of certification

State persisted in shard_memory/desire_state.json.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_ROOT         = Path(__file__).resolve().parents[1]
_STATE_PATH   = _ROOT / "shard_memory" / "desire_state.json"

# Weights for composite desire score
_W_BASE        = 0.35   # world-model relevance / priority
_W_FRUSTRATION = 0.30   # normalized frustration hits
_W_CURIOSITY   = 0.20   # semantic adjacency pull from recent certs
_W_UNCERTAINTY = 0.15   # epistemic fragility of certified knowledge

# Junk regex -- same logic as self_model, prevents frustration boost on nonsense
_JUNK_RE = re.compile(
    r"integration of .+ and .+|"
    r"\b(potrei|vorrei|penso|chiedo|facendo|dovrei|riflessione|energia|lealt[àa])\b|"
    r"impossib",
    re.IGNORECASE,
)


def _is_junk(topic: str) -> bool:
    return bool(_JUNK_RE.search(topic))


def _now() -> str:
    return datetime.now().isoformat()


class DesireState:
    """Per-topic desire state."""

    def __init__(
        self,
        topic: str,
        base_priority: float = 0.5,
        frustration_hits: int = 0,
        curiosity_pull: float = 0.0,
        engagement_scores: Optional[List[float]] = None,
        last_updated: Optional[str] = None,
        uncertainty_signal: float = 0.0,
    ):
        self.topic = topic
        self.base_priority = base_priority
        self.frustration_hits = frustration_hits
        self.curiosity_pull = curiosity_pull
        self.engagement_scores: List[float] = engagement_scores or []
        self.last_updated = last_updated or _now()
        self.uncertainty_signal: float = uncertainty_signal

    @property
    def avg_engagement(self) -> float:
        if not self.engagement_scores:
            return 0.0
        return sum(self.engagement_scores[-5:]) / len(self.engagement_scores[-5:])

    def desire_score(self) -> float:
        """Composite desire score 0–1.

        Four signals:
          base_priority    -- world-model relevance
          frustration_norm -- how often this topic blocked SHARD
          curiosity_pull   -- semantic adjacency from recent certifications
          uncertainty      -- epistemic fragility (certified but shaky knowledge)
        """
        frustration_norm = min(1.0, self.frustration_hits / 5.0)
        return round(
            _W_BASE        * self.base_priority
            + _W_FRUSTRATION * frustration_norm
            + _W_CURIOSITY   * self.curiosity_pull
            + _W_UNCERTAINTY * self.uncertainty_signal,
            4,
        )

    def dict(self) -> dict:
        return {
            "topic": self.topic,
            "base_priority": self.base_priority,
            "frustration_hits": self.frustration_hits,
            "curiosity_pull": self.curiosity_pull,
            "engagement_scores": self.engagement_scores,
            "last_updated": self.last_updated,
            "uncertainty_signal": self.uncertainty_signal,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DesireState":
        return cls(
            topic=d["topic"],
            base_priority=d.get("base_priority", 0.5),
            frustration_hits=d.get("frustration_hits", 0),
            curiosity_pull=d.get("curiosity_pull", 0.0),
            engagement_scores=d.get("engagement_scores", []),
            last_updated=d.get("last_updated"),
            uncertainty_signal=d.get("uncertainty_signal", 0.0),
        )


class DesireEngine:
    """Manages SHARD's desire state across sessions."""

    def __init__(self):
        self._state: Dict[str, DesireState] = {}
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        if _STATE_PATH.exists():
            try:
                raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                for d in raw.values() if isinstance(raw, dict) else raw:
                    ds = DesireState.from_dict(d)
                    self._state[ds.topic] = ds
            except Exception:
                pass

    def _save(self):
        _STATE_PATH.parent.mkdir(exist_ok=True)
        data = {k: v.dict() for k, v in self._state.items()}
        _STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _get_or_create(self, topic: str) -> DesireState:
        if topic not in self._state:
            # Seed base_priority from WorldModel if available
            base = 0.5
            try:
                from world_model import WorldModel
                wm = WorldModel.load_or_default()
                base = wm.relevance(topic)
            except Exception:
                pass
            # Seed uncertainty_signal from UncertaintyTracker if topic is certified
            uncertainty = 0.0
            try:
                try:
                    from uncertainty_tracker import get_uncertainty
                except ImportError:
                    from backend.uncertainty_tracker import get_uncertainty
                uncertainty = get_uncertainty(topic)
            except Exception:
                pass
            self._state[topic] = DesireState(
                topic=topic,
                base_priority=base,
                uncertainty_signal=uncertainty,
            )
        return self._state[topic]

    # ── Frustration drive ──────────────────────────────────────────────────────

    def update_frustration(self, topic: str) -> int:
        """Called on every non-junk study failure. Returns new frustration_hits."""
        if _is_junk(topic):
            return 0
        ds = self._get_or_create(topic)
        ds.frustration_hits += 1
        ds.last_updated = _now()
        self._save()
        return ds.frustration_hits

    def clear_frustration(self, topic: str):
        """Called on certification -- topic is no longer blocked."""
        if topic in self._state:
            self._state[topic].frustration_hits = 0
            self._state[topic].curiosity_pull = 0.0
            self._state[topic].last_updated = _now()
            self._save()

    def get_frustration(self, topic: str) -> int:
        return self._state.get(topic, DesireState(topic=topic)).frustration_hits

    # ── Curiosity (lateral attraction from recent certs) ──────────────────────

    def update_curiosity(self, certified_topic: str, n_adjacent: int = 3):
        """After certifying a topic, find adjacent unexplored topics and boost their pull.

        Uses GraphRAG extends/improves relations first, falls back to SemanticMemory.
        Certified topics (both capability names and skill_library entries) are excluded.
        """
        try:
            from semantic_memory import get_semantic_memory
            from capability_graph import CapabilityGraph
            sem = get_semantic_memory()
            cap = CapabilityGraph()
            certified_skills = set(k.lower() for k in cap.capabilities.keys())

            # Also exclude topics already certified in skill_library
            try:
                from skill_library import SkillLibrary
                sl = SkillLibrary()
                certified_skills |= set(t.lower() for t in sl.get_all_certified())
            except Exception:
                pass

            # WorldModel relevance floor -- only boost topics with real learning ROI
            wm = None
            try:
                from world_model import WorldModel
                wm = WorldModel.load_or_default()
            except Exception:
                pass

            adjacent = []

            # Priority 1: GraphRAG extends/improves -- these are the best next steps
            try:
                from graph_rag import GraphRAG
                rag = GraphRAG()
                rag_relations = rag.get_related_topics(
                    certified_topic, relation_types=["extends", "improves"], limit=n_adjacent + 3
                )
                for t in rag_relations:
                    t = t.strip()
                    if not t or t.lower() in certified_skills or t.lower() == certified_topic.lower():
                        continue
                    if wm is not None and wm.relevance(t) < 0.3:
                        continue
                    adjacent.append(t)
                    if len(adjacent) >= n_adjacent:
                        break
            except Exception:
                pass

            # Priority 2: SemanticMemory similarity -- fill remaining slots
            if len(adjacent) < n_adjacent:
                results = sem.query(certified_topic, collection="knowledge", n_results=n_adjacent + 5)
                for r in results:
                    t = r.get("metadata", {}).get("title") or r.get("document", "")[:60]
                    t = t.strip()
                    if not t or t.lower() in certified_skills or t.lower() == certified_topic.lower():
                        continue
                    if t in adjacent:
                        continue
                    if wm is not None and wm.relevance(t) < 0.3:
                        continue
                    adjacent.append(t)
                    if len(adjacent) >= n_adjacent:
                        break

            for adj_topic in adjacent:
                ds = self._get_or_create(adj_topic)
                # Decay existing pull and add new attraction
                ds.curiosity_pull = round(min(1.0, ds.curiosity_pull * 0.7 + 0.3), 4)
                ds.last_updated = _now()

            if adjacent:
                self._save()
        except Exception:
            pass  # non-fatal: curiosity is a bonus, not required

    def get_curiosity_candidates(self, top_n: int = 3) -> List[str]:
        """Return topics with highest curiosity_pull, for use in NightRunner topic selection."""
        pulled = [(t, ds.curiosity_pull) for t, ds in self._state.items() if ds.curiosity_pull > 0.1]
        pulled.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in pulled[:top_n]]

    # ── Process reward (engagement) ────────────────────────────────────────────

    def record_engagement(self, topic: str, engagement_score: float):
        """Called after a study cycle. engagement_score is 0–1 based on session richness."""
        ds = self._get_or_create(topic)
        ds.engagement_scores.append(round(engagement_score, 4))
        # Keep only last 10 sessions per topic
        ds.engagement_scores = ds.engagement_scores[-10:]
        ds.last_updated = _now()
        self._save()

    def get_avg_engagement(self, topic: str) -> float:
        ds = self._state.get(topic)
        return ds.avg_engagement if ds else 0.0

    # ── Desire score ───────────────────────────────────────────────────────────

    def get_desire_score(self, topic: str) -> float:
        if topic not in self._state:
            return 0.0
        return self._state[topic].desire_score()

    def top_desire_topics(self, top_n: int = 5) -> List[dict]:
        """Return topics sorted by desire_score -- for NightRunner priority stack."""
        scored = [
            {
                "topic": t,
                "desire_score": ds.desire_score(),
                "frustration_hits": ds.frustration_hits,
                "curiosity_pull": ds.curiosity_pull,
                "avg_engagement": ds.avg_engagement,
            }
            for t, ds in self._state.items()
            if ds.desire_score() > 0.3
        ]
        scored.sort(key=lambda x: x["desire_score"], reverse=True)
        return scored[:top_n]

    def get_desire_context(self, topic: str) -> dict:
        """Returns context dict for CognitionCore / CriticAgent injection."""
        ds = self._state.get(topic, DesireState(topic=topic))
        return {
            "topic": topic,
            "desire_score": ds.desire_score(),
            "frustration_hits": ds.frustration_hits,
            "curiosity_pull": ds.curiosity_pull,
            "avg_engagement": ds.avg_engagement,
        }

    # ── Shared environment interface ───────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to environment events broadcast by CognitionCore."""
        if event_type == "skill_certified":
            topic = data.get("topic", "")
            if topic:
                self.clear_frustration(topic)
                self.update_curiosity(topic)
                # Refresh uncertainty: fresh certification should lower the signal
                try:
                    try:
                        from uncertainty_tracker import get_uncertainty
                    except ImportError:
                        from backend.uncertainty_tracker import get_uncertainty
                    ds = self._get_or_create(topic)
                    ds.uncertainty_signal = get_uncertainty(topic)
                    self._save()
                except Exception:
                    pass

        elif event_type == "skill_failed":
            # NightRunner already calls update_frustration() directly before broadcasting.
            # Here we only update curiosity so the desire score reflects the failure signal
            # without double-counting the frustration hit.
            topic = data.get("topic", "")
            if topic:
                self.update_curiosity(topic)

        elif event_type == "goal_changed":
            # New goal activated -- decay curiosity pull for old goal's topics
            old_keywords = data.get("old_keywords", [])
            if old_keywords:
                changed = False
                for topic, ds in self._state.items():
                    if any(kw in topic.lower() for kw in old_keywords):
                        ds.curiosity_pull = round(ds.curiosity_pull * 0.3, 4)
                        changed = True
                if changed:
                    self._save()

        elif event_type == "frustration_peak":
            # Topic has hit the chronic-failure threshold (3+ hits via direct calls).
            # frustration_hits are already incremented -- don't duplicate.
            # Boost base_priority so frustration-drive selection (hits>=2, 40% chance)
            # picks it up sooner and gives SHARD another honest attempt.
            topic = data.get("topic", "")
            if topic:
                ds = self._get_or_create(topic)
                ds.base_priority = round(min(1.0, ds.base_priority + 0.15), 4)
                ds.last_updated = _now()
                self._save()

        elif event_type == "mood_shift":
            new_label = data.get("to", "")
            if new_label == "frustrated":
                # When SHARD is frustrated: push the single most-blocked topic up in priority
                # so frustration-drive selection resolves the block sooner
                top = self.top_desire_topics(top_n=5)
                blocked = [t for t in top if t.get("frustration_hits", 0) >= 2]
                if blocked:
                    ds = self._get_or_create(blocked[0]["topic"])
                    ds.base_priority = round(min(1.0, ds.base_priority + 0.10), 4)
                    ds.last_updated = _now()
                    self._save()
                    logger.debug("[DESIRE] mood_shift(frustrated) -> boosted priority for '%s'", blocked[0]["topic"])
            elif new_label in ("confident", "focused"):
                # Confident mood: spread a small curiosity boost to uncertified adjacent topics
                for ds in list(self._state.values())[:10]:
                    if ds.frustration_hits == 0 and ds.curiosity_pull < 0.5:
                        ds.curiosity_pull = round(min(1.0, ds.curiosity_pull + 0.05), 4)
                self._save()

        elif event_type == "momentum_changed":
            new_momentum = data.get("new", "")
            if new_momentum == "stagnating":
                # Boost base_priority for topics with no frustration (fresh candidates)
                changed = False
                for ds in self._state.values():
                    if ds.frustration_hits == 0 and ds.base_priority < 0.9:
                        ds.base_priority = round(min(1.0, ds.base_priority * 1.1), 4)
                        changed = True
                if changed:
                    self._save()

    def summary(self) -> str:
        top = self.top_desire_topics(3)
        if not top:
            return "DesireEngine: no significant desire state yet"
        parts = [f"'{t['topic']}' (d={t['desire_score']:.2f} f={t['frustration_hits']})" for t in top]
        return f"DesireEngine top: {', '.join(parts)}"


# ── Engagement score computation ───────────────────────────────────────────────

def compute_engagement_score(
    graphrag_relations_added: int = 0,
    cross_pollination_hits: int = 0,
    semantic_context_length: int = 0,
    certified: bool = False,
) -> float:
    """Compute a 0–1 engagement score from session metrics.

    This measures how rich the *process* was, independent of certification.
    A session that adds many causal relations and triggers cross-pollination
    was engaging even if the topic wasn't certified.
    """
    # Normalize each signal to 0–1
    relations_score   = min(1.0, graphrag_relations_added / 10.0)
    crosspoll_score   = min(1.0, cross_pollination_hits / 3.0)
    semantic_score    = min(1.0, semantic_context_length / 500.0)
    cert_bonus        = 0.2 if certified else 0.0

    raw = (
        0.35 * relations_score
        + 0.25 * crosspoll_score
        + 0.20 * semantic_score
        + 0.20 * cert_bonus
    )
    return round(min(1.0, raw), 4)


# ── Singleton ──────────────────────────────────────────────────────────────────

_DESIRE_ENGINE: Optional[DesireEngine] = None


def get_desire_engine() -> DesireEngine:
    global _DESIRE_ENGINE
    if _DESIRE_ENGINE is None:
        _DESIRE_ENGINE = DesireEngine()
    return _DESIRE_ENGINE
