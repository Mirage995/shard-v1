"""self_analyzer.py — SHARD's introspective analysis engine.

Reads experiment history, failed cache, night reports, and capability graph
to identify patterns of failure, near-misses, and capability gaps.
Produces ImprovementTickets consumed by improvement_engine.py.

No LLM calls. No external dependencies. Fast enough to run at NightRunner startup.

Ticket types and their meaning:
  retry_chronic_failure  — topic failed 2+ times, avg score < 6.0, never certified
  certify_near_miss      — topic stuck at 6.0–7.4, never crossed the certification bar
  retry_grown            — topic is in failed_cache but SHARD has grown 15+ skills since
  fill_capability_gap    — skill in DEFAULT_LEARNING_MAP not yet in capability_graph
"""
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("shard.self_analyzer")

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT             = Path(__file__).parent.parent.resolve()
_EXPERIMENT_FILE  = _ROOT / "shard_memory" / "experiment_history.json"
_FAILED_CACHE     = _ROOT / "shard_memory" / "failed_cache.json"
_NIGHT_REPORTS    = _ROOT / "night_reports"
_CAPABILITY_FILE  = _ROOT / "shard_memory" / "capability_graph.json"

# ── Thresholds ─────────────────────────────────────────────────────────────────
CHRONIC_FAILURE_MIN_EXPERIMENTS = 2      # need at least N attempts before flagging
CHRONIC_FAILURE_MAX_AVG_SCORE   = 6.0   # avg below this = chronic failure
NEAR_MISS_MIN_SCORE             = 6.0   # bottom of near-miss band
NEAR_MISS_MAX_SCORE             = 7.4   # top of near-miss band (cert threshold = 7.5)
GROWN_SKILLS_DELTA              = 15    # skills gained since failure → ready to retry
STAGNATION_SESSIONS             = 3     # look at last N sessions for stagnation
STAGNATION_MAX_SKILLS_PER_SESSION = 2   # avg skills/session below this = stagnant

# ── Ticket priorities ──────────────────────────────────────────────────────────
P1, P2, P3 = 1, 2, 3


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ImprovementTicket:
    """A single actionable improvement item for improvement_engine.py."""
    id: str
    priority: int          # 1 = urgent, 2 = normal, 3 = low
    ticket_type: str       # see module docstring
    topic: str
    reason: str            # human-readable explanation
    suggested_action: str  # what improvement_engine should do
    metadata: dict         # supporting evidence (score history, counts, etc.)
    created_at: str        = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalysisReport:
    """Full introspection snapshot produced by SelfAnalyzer.analyze()."""
    generated_at: str
    total_experiments: int
    total_capabilities: int
    failure_patterns: List[dict]      # per-topic failure stats
    near_miss_topics: List[dict]      # per-topic near-miss stats
    capability_gaps: List[str]        # skill names missing from graph
    stagnation_detected: bool
    stagnation_evidence: dict
    tickets: List[ImprovementTicket]  # sorted by priority asc

    def summary(self) -> str:
        lines = [
            f"[ANALYZER] Report @ {self.generated_at}",
            f"  Experiments: {self.total_experiments} | Capabilities: {self.total_capabilities}",
            f"  Chronic failures: {len(self.failure_patterns)}",
            f"  Near-misses:      {len(self.near_miss_topics)}",
            f"  Capability gaps:  {len(self.capability_gaps)}",
            f"  Stagnation:       {'YES' if self.stagnation_detected else 'no'}",
            f"  Tickets generated: {len(self.tickets)}",
        ]
        if self.tickets:
            lines.append("  Top tickets:")
            for t in self.tickets[:5]:
                lines.append(f"    [P{t.priority}] {t.ticket_type} — {t.topic!r}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ── SelfAnalyzer ───────────────────────────────────────────────────────────────

class SelfAnalyzer:
    """Reads SHARD's memory and produces ImprovementTickets.

    Args:
        capability_graph: Live CapabilityGraph instance (optional; falls back to
                          reading capability_graph.json directly).
        strategy_memory:  Live StrategyMemory instance (optional; used for richer
                          strategy correlation in future phases).
    """

    def __init__(self, capability_graph=None, strategy_memory=None):
        self.capability_graph = capability_graph
        self.strategy_memory  = strategy_memory

    # ── Public API ─────────────────────────────────────────────────────────────

    async def analyze(self) -> AnalysisReport:
        """Run full analysis and return a report with ranked ImprovementTickets."""
        logger.info("[ANALYZER] Starting self-analysis…")

        experiments   = self._load_experiments()
        failed_cache  = self._load_failed_cache()
        night_reports = self._load_night_reports()
        capabilities  = self._load_capabilities()

        topic_stats = self._compute_topic_stats(experiments)

        failure_patterns = self._find_chronic_failures(topic_stats)
        near_misses      = self._find_near_misses(topic_stats)
        capability_gaps  = self._find_capability_gaps(capabilities)
        stagnation, stag_evidence = self._detect_stagnation(night_reports)
        grown_retries    = self._find_grown_retries(failed_cache, capabilities)

        tickets = self._generate_tickets(
            failure_patterns, near_misses, capability_gaps,
            grown_retries, stagnation,
        )

        report = AnalysisReport(
            generated_at      = datetime.now().isoformat(),
            total_experiments = len(experiments),
            total_capabilities= len(capabilities),
            failure_patterns  = failure_patterns,
            near_miss_topics  = near_misses,
            capability_gaps   = capability_gaps,
            stagnation_detected = stagnation,
            stagnation_evidence = stag_evidence,
            tickets           = tickets,
        )

        logger.info(report.summary())
        return report

    # ── Loaders ────────────────────────────────────────────────────────────────

    def _load_experiments(self) -> List[dict]:
        """Load from SQLite, fallback to JSON."""
        try:
            from shard_db import get_db
            conn = get_db()
            rows = conn.execute(
                "SELECT topic, score, certified as success, timestamp, "
                "failure_reason, source, previous_score "
                "FROM experiments ORDER BY timestamp"
            ).fetchall()
            logger.info("[DB] SelfAnalyzer loaded %d experiments from SQLite", len(rows))
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("[DB] SelfAnalyzer SQLite load failed (%s), falling back to JSON", exc)
        try:
            if not _EXPERIMENT_FILE.exists():
                return []
            data = json.loads(_EXPERIMENT_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else list(data.values())
        except Exception as exc:
            logger.warning("[ANALYZER] Could not load experiment_history: %s", exc)
            return []

    def _load_failed_cache(self) -> Dict[str, int]:
        """Load from SQLite, fallback to JSON."""
        try:
            from shard_db import get_db
            conn = get_db()
            rows = conn.execute("SELECT topic, skill_count_at_fail FROM failed_cache").fetchall()
            logger.info("[DB] SelfAnalyzer loaded %d failed_cache entries from SQLite", len(rows))
            return {r["topic"]: r["skill_count_at_fail"] for r in rows}
        except Exception as exc:
            logger.warning("[DB] SelfAnalyzer failed_cache SQLite load failed (%s), falling back to JSON", exc)
        try:
            if not _FAILED_CACHE.exists():
                return {}
            return json.loads(_FAILED_CACHE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[ANALYZER] Could not load failed_cache: %s", exc)
            return {}

    def _load_night_reports(self) -> List[dict]:
        reports = []
        try:
            if not _NIGHT_REPORTS.exists():
                return []
            for p in sorted(_NIGHT_REPORTS.glob("session_*.json")):
                try:
                    reports.append(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("[ANALYZER] Could not load night reports: %s", exc)
        return reports

    def _load_capabilities(self) -> Dict[str, dict]:
        """Use live graph if available, then SQLite, then JSON fallback."""
        if self.capability_graph and hasattr(self.capability_graph, "capabilities"):
            return dict(self.capability_graph.capabilities)
        # SQLite fallback
        try:
            from shard_db import get_db
            conn = get_db()
            rows = conn.execute(
                "SELECT name, source_topic, acquired_at FROM capabilities"
            ).fetchall()
            logger.info("[DB] SelfAnalyzer loaded %d capabilities from SQLite", len(rows))
            return {
                r["name"]: {"source_topic": r["source_topic"], "acquired": r["acquired_at"], "requires": []}
                for r in rows
            }
        except Exception:
            pass
        # JSON fallback
        try:
            if not _CAPABILITY_FILE.exists():
                return {}
            return json.loads(_CAPABILITY_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[ANALYZER] Could not load capability_graph: %s", exc)
            return {}

    # ── Analysis passes ────────────────────────────────────────────────────────

    def _compute_topic_stats(self, experiments: List[dict]) -> Dict[str, dict]:
        """Aggregate per-topic: scores, attempts, certified flag."""
        stats: Dict[str, dict] = {}
        for exp in experiments:
            topic = str(exp.get("topic", "")).strip().lower()
            if not topic:
                continue
            if topic not in stats:
                stats[topic] = {"scores": [], "certified": False, "timestamps": []}
            score = exp.get("score")
            if score is not None:
                stats[topic]["scores"].append(float(score))
            if exp.get("success"):
                stats[topic]["certified"] = True
            ts = exp.get("timestamp")
            if ts:
                stats[topic]["timestamps"].append(ts)
        # Compute derived fields
        for topic, s in stats.items():
            scores = s["scores"]
            s["attempts"]  = len(scores)
            s["avg_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0
            s["max_score"] = max(scores) if scores else 0.0
            s["min_score"] = min(scores) if scores else 0.0
            s["last_ts"]   = max(s["timestamps"]) if s["timestamps"] else ""
        return stats

    def _find_chronic_failures(self, topic_stats: Dict[str, dict]) -> List[dict]:
        """Topics with 2+ attempts, avg score < threshold, never certified."""
        patterns = []
        for topic, s in topic_stats.items():
            if (
                s["attempts"] >= CHRONIC_FAILURE_MIN_EXPERIMENTS
                and s["avg_score"] < CHRONIC_FAILURE_MAX_AVG_SCORE
                and not s["certified"]
            ):
                patterns.append({
                    "topic":    topic,
                    "attempts": s["attempts"],
                    "avg_score":s["avg_score"],
                    "max_score":s["max_score"],
                    "last_ts":  s["last_ts"],
                })
        patterns.sort(key=lambda x: (x["avg_score"], -x["attempts"]))
        logger.debug("[ANALYZER] Chronic failures found: %d", len(patterns))
        return patterns

    def _find_near_misses(self, topic_stats: Dict[str, dict]) -> List[dict]:
        """Topics where every score landed in 6.0–7.4 and never certified."""
        near = []
        for topic, s in topic_stats.items():
            if not s["scores"] or s["certified"]:
                continue
            all_near = all(NEAR_MISS_MIN_SCORE <= sc <= NEAR_MISS_MAX_SCORE for sc in s["scores"])
            if all_near:
                near.append({
                    "topic":    topic,
                    "attempts": s["attempts"],
                    "avg_score":s["avg_score"],
                    "max_score":s["max_score"],
                    "last_ts":  s["last_ts"],
                })
        near.sort(key=lambda x: -x["max_score"])  # highest near-miss first
        logger.debug("[ANALYZER] Near-misses found: %d", len(near))
        return near

    def _find_capability_gaps(self, capabilities: Dict[str, dict]) -> List[str]:
        """Skills in DEFAULT_LEARNING_MAP not yet in the capability graph."""
        # Import here to avoid circular at module level
        try:
            from research_agenda import DEFAULT_LEARNING_MAP
        except ImportError:
            logger.warning("[ANALYZER] Could not import DEFAULT_LEARNING_MAP")
            return []

        cap_keys = set(capabilities.keys())
        gaps = [
            skill for skill in DEFAULT_LEARNING_MAP
            if skill.lower() not in cap_keys
        ]
        gaps.sort()
        logger.debug("[ANALYZER] Capability gaps: %d / %d", len(gaps), len(DEFAULT_LEARNING_MAP))
        return gaps

    def _detect_stagnation(self, night_reports: List[dict]):
        """Check if recent sessions are yielding very few new skills."""
        if len(night_reports) < STAGNATION_SESSIONS:
            return False, {}

        recent = night_reports[-STAGNATION_SESSIONS:]
        skills_per_session = []
        for report in recent:
            before = after = None
            for cycle in report.get("cycles", []):
                if before is None:
                    before = cycle.get("skills_before", 0)
                after = cycle.get("skills_after", before)
            if before is not None and after is not None:
                skills_per_session.append(after - before)

        if not skills_per_session:
            return False, {}

        avg_growth = sum(skills_per_session) / len(skills_per_session)
        stagnating = avg_growth < STAGNATION_MAX_SKILLS_PER_SESSION

        evidence = {
            "sessions_checked": len(recent),
            "skills_per_session": skills_per_session,
            "avg_growth": round(avg_growth, 2),
            "threshold": STAGNATION_MAX_SKILLS_PER_SESSION,
        }

        if stagnating:
            logger.warning(
                "[ANALYZER] Stagnation detected — avg %.1f skills/session over last %d sessions",
                avg_growth, STAGNATION_SESSIONS,
            )
        return stagnating, evidence

    def _find_grown_retries(
        self,
        failed_cache: Dict[str, int],
        capabilities: Dict[str, dict],
    ) -> List[dict]:
        """Topics in failed_cache where SHARD has grown enough to retry.

        failed_cache value = skills_count at time of failure.
        If current skills - skills_at_failure >= GROWN_SKILLS_DELTA, SHARD is
        meaningfully stronger and should try again.
        """
        current_skills = len(capabilities)
        ready = []
        for topic, skills_at_failure in failed_cache.items():
            if not isinstance(skills_at_failure, int):
                continue
            delta = current_skills - skills_at_failure
            if delta >= GROWN_SKILLS_DELTA:
                ready.append({
                    "topic":            topic,
                    "skills_at_failure":skills_at_failure,
                    "current_skills":   current_skills,
                    "skills_gained":    delta,
                })
        ready.sort(key=lambda x: -x["skills_gained"])
        logger.debug("[ANALYZER] Grown-retry candidates: %d", len(ready))
        return ready

    # ── Ticket generation ──────────────────────────────────────────────────────

    def _generate_tickets(
        self,
        failure_patterns: List[dict],
        near_misses: List[dict],
        capability_gaps: List[str],
        grown_retries: List[dict],
        stagnation: bool,
    ) -> List[ImprovementTicket]:
        tickets: List[ImprovementTicket] = []
        seen_topics: set[str] = set()  # one ticket per topic

        # ── P1: chronic failures ───────────────────────────────────────────────
        for fp in failure_patterns:
            topic = fp["topic"]
            if topic in seen_topics:
                continue
            seen_topics.add(topic)
            tickets.append(ImprovementTicket(
                id=f"cf_{topic[:40].replace(' ', '_')}",
                priority=P1,
                ticket_type="retry_chronic_failure",
                topic=topic,
                reason=(
                    f"Failed {fp['attempts']}x with avg score {fp['avg_score']}/10 "
                    f"(max {fp['max_score']}/10), never certified."
                ),
                suggested_action=(
                    "Re-study with a revised approach. Consider alternative sources "
                    "or breaking the topic into smaller sub-topics."
                ),
                metadata=fp,
            ))

        # ── P1: near-misses ────────────────────────────────────────────────────
        for nm in near_misses:
            topic = nm["topic"]
            if topic in seen_topics:
                continue
            seen_topics.add(topic)
            tickets.append(ImprovementTicket(
                id=f"nm_{topic[:40].replace(' ', '_')}",
                priority=P1,
                ticket_type="certify_near_miss",
                topic=topic,
                reason=(
                    f"Stuck at {nm['avg_score']}/10 avg (max {nm['max_score']}/10) "
                    f"after {nm['attempts']} attempt(s). Just below certification threshold."
                ),
                suggested_action=(
                    "One more focused attempt. Prioritise depth over breadth: "
                    "target the specific gaps identified in the last evaluation."
                ),
                metadata=nm,
            ))

        # ── P2: grown retries ──────────────────────────────────────────────────
        for gr in grown_retries:
            topic = gr["topic"]
            if topic in seen_topics:
                continue
            seen_topics.add(topic)
            tickets.append(ImprovementTicket(
                id=f"gr_{topic[:40].replace(' ', '_')}",
                priority=P2,
                ticket_type="retry_grown",
                topic=topic,
                reason=(
                    f"Previously failed when SHARD had {gr['skills_at_failure']} skills. "
                    f"Now has {gr['current_skills']} (+{gr['skills_gained']}). "
                    "New prerequisite knowledge available."
                ),
                suggested_action=(
                    "Retry — SHARD's expanded skill set may unlock a better approach."
                ),
                metadata=gr,
            ))

        # ── P2: capability gaps ────────────────────────────────────────────────
        try:
            from research_agenda import DEFAULT_LEARNING_MAP
        except ImportError:
            DEFAULT_LEARNING_MAP = {}

        for skill in capability_gaps:
            study_topic = DEFAULT_LEARNING_MAP.get(skill, skill.replace("_", " "))
            if study_topic in seen_topics:
                continue
            seen_topics.add(study_topic)
            tickets.append(ImprovementTicket(
                id=f"gap_{skill[:40]}",
                priority=P2,
                ticket_type="fill_capability_gap",
                topic=study_topic,
                reason=f"Skill '{skill}' is in the learning map but not yet acquired.",
                suggested_action=f"Study '{study_topic}' to fill this capability gap.",
                metadata={"skill": skill, "study_topic": study_topic},
            ))

        # ── P3: stagnation probe ───────────────────────────────────────────────
        if stagnation and "advanced python concurrency" not in seen_topics:
            tickets.append(ImprovementTicket(
                id="stagnation_probe",
                priority=P3,
                ticket_type="stagnation_probe",
                topic="advanced python concurrency",
                reason="Recent sessions show low skill growth. Injecting a challenge topic.",
                suggested_action=(
                    "Study a harder, cross-domain topic to break the stagnation plateau."
                ),
                metadata={},
            ))

        # Sort: P1 first, then by type stability
        tickets.sort(key=lambda t: (t.priority, t.ticket_type, t.topic))

        logger.info("[ANALYZER] Generated %d tickets (%d P1, %d P2, %d P3)",
            len(tickets),
            sum(1 for t in tickets if t.priority == P1),
            sum(1 for t in tickets if t.priority == P2),
            sum(1 for t in tickets if t.priority == P3),
        )
        return tickets
