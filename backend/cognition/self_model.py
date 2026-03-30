"""self_model.py -- SHARD self-awareness model.

Summarizes capabilities, computes live performance metrics, and assesses
capability gaps against the DEFAULT_LEARNING_MAP.

Metrics computed from disk data (no LLM, no external calls):
  get_certification_rate()  -- certified / total attempts (experiment_history)
  get_avg_repair_loops()    -- avg retries per topic (repeat appearances in history)
  self_assess_gaps()        -- categories with < GAP_SKILL_THRESHOLD certified skills
                              vs DEFAULT_LEARNING_MAP; returns severity + gap list
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("shard.self_model")

_ROOT = Path(__file__).resolve().parent.parent.parent

try:
    import sys as _sys
    _sys.path.insert(0, str(_ROOT / "backend"))
    from architecture_map import ArchitectureMap as _ArchMap
    _arch_map = _ArchMap()
except Exception:
    _arch_map = None

# A category is "critical" if it has fewer than this many certified skills
GAP_SKILL_THRESHOLD = 3


class SelfModel:

    def __init__(self, capability_graph, strategy_memory, research_agenda,
                 world_model=None):
        self.capability_graph = capability_graph
        self.strategy_memory  = strategy_memory
        self.research_agenda  = research_agenda
        self.world_model      = world_model

    # ── Existing summaries (unchanged) ────────────────────────────────────────

    def summarize_capabilities(self):
        certified = self.capability_graph.get_certified_skills()
        total     = len(self.capability_graph.get_all_skills())
        logger.debug("[SELF MODEL] capabilities summarized")
        return {"certified": certified, "total": total}

    def summarize_frontier(self):
        frontier = self.research_agenda.get_frontier_topics(limit=5)
        logger.debug("[SELF MODEL] frontier topics")
        return frontier

    def summarize_metrics(self):
        success_rate = getattr(
            self.strategy_memory, "get_success_rate", lambda: 0.0
        )()
        logger.debug("[SELF MODEL] metrics computed")
        return {"strategy_success_rate": success_rate}

    # ── Live performance metrics ───────────────────────────────────────────────

    def get_certification_rate(self) -> float:
        """Fraction of study cycles that resulted in a certified topic."""
        try:
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from shard_db import get_db
            conn = get_db()
            row = conn.execute(
                "SELECT COUNT(*) AS total, SUM(certified) AS cert FROM experiments"
            ).fetchone()
            if not row or not row["total"]:
                return 0.0
            return round((row["cert"] or 0) / row["total"], 3)
        except Exception as exc:
            logger.warning("[SELF MODEL] get_certification_rate failed: %s", exc)
            return 0.0

    def get_avg_repair_loops(self) -> float:
        """Average number of study attempts per unique topic.

        > 1.0 means SHARD frequently retries -- indicates learning difficulty.
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from shard_db import get_db
            conn = get_db()
            row = conn.execute(
                "SELECT COUNT(*) AS total, COUNT(DISTINCT topic) AS unique_topics FROM experiments"
            ).fetchone()
            if not row or not row["unique_topics"]:
                return 1.0
            return round(row["total"] / row["unique_topics"], 2)
        except Exception as exc:
            logger.warning("[SELF MODEL] get_avg_repair_loops failed: %s", exc)
            return 1.0

    # ── Gap self-assessment ────────────────────────────────────────────────────

    def self_assess_gaps(self) -> Dict:
        """Assess which skill categories are critically underdeveloped.

        Compares certified skills in each DEFAULT_LEARNING_MAP category against
        GAP_SKILL_THRESHOLD (default 3). Returns a structured report with
        severity and a list of specific missing skills.

        Returns:
            {
              "critical_gaps":    [str, ...],   # category names below threshold
              "missing_skills":   [str, ...],   # individual skills not in graph
              "gap_rate":         float,         # fraction of map skills missing
              "total_map":        int,
              "missing_count":    int,
              "severity":         "none"|"low"|"medium"|"critical",
            }
        """
        try:
            from research_agenda import DEFAULT_LEARNING_MAP
        except ImportError:
            logger.warning("[SELF MODEL] Cannot import DEFAULT_LEARNING_MAP -- skipping gap assessment.")
            return self._empty_gap_report()

        try:
            all_skills = set(
                s.lower() for s in self.capability_graph.get_all_skills()
            )
        except Exception as exc:
            logger.warning("[SELF MODEL] Cannot read capability graph: %s", exc)
            return self._empty_gap_report()

        # Find skills in the map that SHARD has not yet learned
        missing_skills: List[str] = []
        for skill in DEFAULT_LEARNING_MAP:
            skill_topic = DEFAULT_LEARNING_MAP.get(skill, skill).lower()
            # Match if either the key or the mapped topic is in the graph
            if skill.lower() not in all_skills and skill_topic not in all_skills:
                missing_skills.append(skill)

        # Find categories with fewer than GAP_SKILL_THRESHOLD skills
        # Group by category prefix (first word of the skill key)
        category_counts: Dict[str, int] = {}
        for skill in DEFAULT_LEARNING_MAP:
            category = skill.split("_")[0]
            if skill.lower() in all_skills or \
               DEFAULT_LEARNING_MAP[skill].lower() in all_skills:
                category_counts[category] = category_counts.get(category, 0) + 1
            else:
                category_counts.setdefault(category, 0)

        critical_gaps = [
            cat for cat, count in category_counts.items()
            if count < GAP_SKILL_THRESHOLD
        ]

        total_map    = len(DEFAULT_LEARNING_MAP)
        missing_cnt  = len(missing_skills)
        gap_rate     = round(missing_cnt / total_map, 3) if total_map else 0.0

        if gap_rate > 0.6:
            severity = "critical"
        elif gap_rate > 0.3:
            severity = "medium"
        elif gap_rate > 0.1:
            severity = "low"
        else:
            severity = "none"

        logger.info(
            "[SELF MODEL] Gap assessment: %d/%d missing (%.0f%%) -- severity=%s  critical_categories=%s",
            missing_cnt, total_map, gap_rate * 100, severity, critical_gaps,
        )

        return {
            "critical_gaps":  critical_gaps,
            "missing_skills": missing_skills,
            "gap_rate":       gap_rate,
            "total_map":      total_map,
            "missing_count":  missing_cnt,
            "severity":       severity,
        }

    # ── Architecture Map integration ──────────────────────────────────────────

    def modules_for_capability(self, capability_tag: str) -> List[str]:
        """Return backend modules that handle a given capability tag.

        Example: modules_for_capability("sandbox_execution")
                 -> ["sandbox_runner", "study_agent"]
        """
        if _arch_map is None:
            return []
        return _arch_map.modules_for_capability(capability_tag)

    def architecture_summary(self) -> str:
        """Return the architecture map summary string."""
        if _arch_map is None:
            return "Architecture map not available."
        return _arch_map.summary()

    # ── describe() -- the credible self-portrait ───────────────────────────────

    def describe(self) -> str:
        """Return a human-readable self-description with live metrics."""
        caps      = self.summarize_capabilities()
        frontier  = self.summarize_frontier()
        cert_rate = self.get_certification_rate()
        avg_loops = self.get_avg_repair_loops()
        arch      = self.architecture_summary()

        return (
            f"I am SHARD.\n\n"
            f"Certified capabilities: {caps['total']}\n"
            f"Examples: {', '.join(caps['certified'][:6])}\n\n"
            f"Currently studying: {', '.join(frontier)}\n\n"
            f"Performance metrics:\n"
            f"  Certification rate:  {cert_rate:.1%}\n"
            f"  Avg study attempts:  {avg_loops:.1f} loops per topic\n\n"
            f"System architecture:\n{arch}"
        ).strip()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _empty_gap_report() -> Dict:
        return {
            "critical_gaps":  [],
            "missing_skills": [],
            "gap_rate":       0.0,
            "total_map":      0,
            "missing_count":  0,
            "severity":       "none",
        }
