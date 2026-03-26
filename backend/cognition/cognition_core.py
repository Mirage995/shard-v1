"""cognition_core.py — SHARD CognitionCore / Senso Interno.

5-layer Global Workspace that aggregates internal tensions and exposes them
to the rest of the pipeline. Designed to create the *conditions* for
emergent behavior — not to program it.

Architecture (COGNITION_CORE.txt):
  Layer 0 — ANCHOR       : ground truth (sandbox pass/fail, score, cert rate)
  Layer 1 — EXECUTIVE    : who SHARD is right now (lightweight snapshot)
  Layer 2 — IDENTITY     : SelfModel — capabilities, gaps, frontier topics
  Layer 3 — KNOWLEDGE    : GraphRAG  — causal relations, structural complexity
  Layer 4 — EXPERIENCE   : EpisodicMemory + StrategyMemory — history, patterns
  Layer 5 — CRITIQUE     : CriticAgent + MetaLearning — systematic errors, strategy

Shadow Diagnostic Layer:
  audit_emergence(topic, action, delta) → [EMERGENCE HIT] or [MISSED EMERGENCE]
  Judges ONLY measurable behavioral metrics — never text output (anti-recita rule).

Token budget:
  executive()         ~200 tokens  (always loaded)
  relational_context  ~500 tokens  (on request, one topic)
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("shard.cognition_core")

_ROOT = Path(__file__).resolve().parent.parent.parent


def _get_db():
    import sys as _sys
    _sys.path.insert(0, str(_ROOT / "backend"))
    from shard_db import get_db
    return get_db()


# ─────────────────────────────────────────────────────────────────────────────
# Layer 0 — ANCHOR
# ─────────────────────────────────────────────────────────────────────────────

def _anchor() -> Dict[str, Any]:
    """Read ground-truth metrics directly from SQLite. No LLM, no inference."""
    _default = {
        "certification_rate": 0.0, "total_experiments": 0,
        "total_certified": 0, "last_topic": "—", "last_score": 0.0,
        "last_pass": False, "last_date": "—", "avg_score": 0.0,
    }
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT COUNT(*) AS total, SUM(certified) AS cert FROM experiments"
        ).fetchone()
        # Guard: row values may be MagicMock during cross-test pollution
        total = int(row["total"] or 0) if row and not _is_mock(row["total"]) else 0
        cert  = int(row["cert"] or 0)  if row and not _is_mock(row["cert"])  else 0
        cert_rate = round(cert / total, 3) if total else 0.0

        last = conn.execute(
            "SELECT topic, score, certified, timestamp FROM experiments "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        if last and not _is_mock(last):
            last_topic = str(last["topic"])   if last["topic"]     else "—"
            last_score = float(last["score"]) if last["score"] is not None else 0.0
            last_pass  = bool(last["certified"])
            ts         = last["timestamp"]
            last_date  = str(ts)[:10] if ts and not _is_mock(ts) else "—"
        else:
            last_topic, last_score, last_pass, last_date = "—", 0.0, False, "—"

        avg_row = conn.execute(
            "SELECT AVG(score) AS avg FROM experiments"
        ).fetchone()
        avg_score = float(avg_row["avg"] or 0.0) if avg_row and not _is_mock(avg_row["avg"]) else 0.0

        return {
            "certification_rate": cert_rate,
            "total_experiments":  total,
            "total_certified":    cert,
            "last_topic":         last_topic,
            "last_score":         round(last_score, 2),
            "last_pass":          last_pass,
            "last_date":          last_date,
            "avg_score":          round(avg_score, 2),
        }
    except Exception as exc:
        logger.warning("[ANCHOR] Failed: %s", exc)
        return _default


def _is_mock(value) -> bool:
    """Return True if value is a unittest.mock object (cross-test pollution guard)."""
    return hasattr(value, "_mock_name") or type(value).__name__ in ("MagicMock", "Mock", "NonCallableMock")


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — EXECUTIVE SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def _executive_summary(anchor: Dict) -> str:
    """Lightweight snapshot (~200 tokens). Always loaded by executive()."""
    cert_pct  = f"{anchor['certification_rate']:.0%}"
    last_info = (
        f"PASS ({anchor['last_score']})" if anchor["last_pass"]
        else f"FAIL ({anchor['last_score']})"
    )

    # Determine status
    rate = anchor["certification_rate"]
    if rate >= 0.6:
        status = "performing"
    elif rate >= 0.3:
        status = "developing"
    else:
        status = "struggling"

    lines = [
        f"SHARD Executive Summary — {anchor['last_date']}",
        f"Status: {status}",
        f"Certification rate: {cert_pct} ({anchor['total_certified']}/{anchor['total_experiments']})",
        f"Average score: {anchor['avg_score']}/10",
        f"Last topic: {anchor['last_topic']} -> {last_info}",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CognitionCore
# ─────────────────────────────────────────────────────────────────────────────

class CognitionCore:
    """Central aggregator for SHARD's internal state.

    The Core does NOT orchestrate — it aggregates and exposes tensions.
    Layers never call each other; they only talk to the Core.

    Usage:
        core = CognitionCore(
            self_model=..., episodic_memory=...,
            strategy_memory=..., meta_learning=..., critic_agent=...
        )
        await core.initialize()                  # warm up Layer 0+1 cache
        ctx = await core.relational_context(topic)  # inject into prompt
        await core.audit_emergence(topic, action, delta)  # after each action
    """

    def __init__(
        self,
        self_model=None,
        episodic_memory=None,
        strategy_memory=None,
        meta_learning=None,
        critic_agent=None,
    ):
        self._self_model      = self_model
        self._episodic_memory = episodic_memory
        self._strategy_memory = strategy_memory
        self._meta_learning   = meta_learning
        self._critic_agent    = critic_agent

        # Layer 0+1 cache — refreshed every NightRunner cycle
        self._anchor_cache:    Optional[Dict]  = None
        self._exec_cache:      Optional[str]   = None
        self._cache_timestamp: float           = 0.0

        # Shadow Diagnostic Layer — emergence tracking
        self._emergence_log: List[Dict] = []
        self._emergence_stats = {
            "opportunities": 0,
            "hits":          0,
            "misses":        0,
            "false_positives": 0,
            "miss_causes":   {"signal_weak": 0, "model_inertia": 0, "dilution": 0, "ignored_v3": 0},
        }

        # ── Shared Environment — module registry + event bus ──────────────────
        # Modules register here and receive broadcasts from each other.
        # CognitionCore is the environment: it routes events, never decides.
        self._registry: Dict[str, Dict] = {}   # name → {module, interests}
        self._broadcast_log: List[Dict] = []   # last 50 events (Shadow Diagnostic)

    # ── Shared Environment — register / broadcast ─────────────────────────────

    def register(self, name: str, module, interests: List[str]) -> None:
        """Register a module as a citizen of this environment.

        Args:
            name:      Unique identifier (e.g. "world_model", "desire_engine")
            module:    The module instance. Must implement on_event(event, data, source).
            interests: List of event types to receive. Use ["*"] for all events.
        """
        self._registry[name] = {"module": module, "interests": set(interests)}
        logger.info("[CORE ENV] Registered '%s' — interests: %s", name, interests)

    def broadcast(self, event_type: str, data: Dict, source: str = "system") -> int:
        """Broadcast an event to all registered modules that declared interest.

        CognitionCore routes the event — it does NOT decide what to do with it.
        Each module reacts autonomously via its on_event() method.

        Returns the number of modules that received the event.
        The event is logged in the Shadow Diagnostic broadcast_log.
        """
        recipients = 0
        for name, entry in self._registry.items():
            if name == source:
                continue  # never echo back to the source
            interests = entry["interests"]
            if event_type in interests or "*" in interests:
                try:
                    entry["module"].on_event(event_type, data, source)
                    recipients += 1
                except Exception as exc:
                    logger.warning("[CORE ENV] '%s'.on_event(%s) failed: %s", name, event_type, exc)

        # Log in Shadow Diagnostic
        self._broadcast_log.append({
            "event":      event_type,
            "source":     source,
            "data_keys":  list(data.keys()),
            "recipients": recipients,
            "timestamp":  datetime.now().isoformat(),
        })
        if len(self._broadcast_log) > 50:
            self._broadcast_log = self._broadcast_log[-50:]

        logger.info(
            "[CORE ENV] broadcast '%s' from '%s' → %d recipient(s)",
            event_type, source, recipients,
        )
        return recipients

    def get_broadcast_log(self, last_n: int = 10) -> List[Dict]:
        """Return the last N environment events (for telemetry / debugging)."""
        return self._broadcast_log[-last_n:]

    # ── Initialization ────────────────────────────────────────────────────────

    async def initialize(self):
        """Pre-warm Layer 0+1 cache. Call once at NightRunner startup."""
        self._refresh_anchor_cache()
        logger.info(
            "[COGNITION CORE] Initialized — cert_rate=%.1f%% experiments=%d",
            self._anchor_cache["certification_rate"] * 100,
            self._anchor_cache["total_experiments"],
        )

    def _refresh_anchor_cache(self):
        anchor = _anchor()
        self._anchor_cache    = anchor
        self._exec_cache      = _executive_summary(anchor)
        self._cache_timestamp = time.time()

    # ── Layer 0 + 1 — executive() — always available ──────────────────────────

    def executive(self) -> Dict[str, Any]:
        """Return Layer 0 (Anchor) + Layer 1 (Executive Summary).

        Cached and lightweight. The only method that is always pre-loaded.
        Returns:
            {"anchor": {...}, "summary": "...plain text..."}
        """
        # Refresh if stale (>15 minutes)
        if self._anchor_cache is None or (time.time() - self._cache_timestamp) > 900:
            self._refresh_anchor_cache()
        return {
            "anchor":  self._anchor_cache,
            "summary": self._exec_cache,
        }

    # ── Layer 2 — IDENTITY ────────────────────────────────────────────────────

    def query_identity(self) -> Dict[str, Any]:
        """Layer 2: SelfModel snapshot.

        Returns certified capabilities, gap assessment, frontier topics,
        avg repair loops. Used by: NightRunner, CriticAgent.
        """
        if self._self_model is None:
            return {"error": "SelfModel not available"}
        try:
            cert_rate  = self._self_model.get_certification_rate()
            avg_loops  = self._self_model.get_avg_repair_loops()
            gaps       = self._self_model.self_assess_gaps()
            caps       = self._self_model.summarize_capabilities()
            frontier   = self._self_model.summarize_frontier()

            return {
                "certification_rate": cert_rate,
                "avg_repair_loops":   avg_loops,
                "critical_gaps":      gaps.get("critical_gaps", []),
                "gap_severity":       gaps.get("severity", "none"),
                "gap_rate":           gaps.get("gap_rate", 0.0),
                "certified_count":    len(caps.get("certified", [])),
                "frontier_topics":    frontier[:5],
                "top_capabilities":   caps.get("certified", [])[:8],
            }
        except Exception as exc:
            logger.warning("[COGNITION] query_identity failed: %s", exc)
            return {"error": str(exc)}

    # ── Layer 3 — KNOWLEDGE ───────────────────────────────────────────────────

    def query_knowledge(self, topic: str) -> Dict[str, Any]:
        """Layer 3: GraphRAG causal context for a topic.

        Returns structural complexity (# causal dependencies) and
        the causal context string ready for prompt injection.
        Used by: SYNTHESIZE, MetaLearning (strategy selection).
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from graph_rag import query_causal_context
            from shard_db import query as db_query

            causal_str = query_causal_context(topic)

            # Count direct dependencies (structural complexity)
            words = topic.lower().split()[:5]
            rows = db_query(
                "SELECT COUNT(*) AS n FROM knowledge_graph WHERE confidence >= 0.6"
            )
            total_relations = rows[0]["n"] if rows else 0

            # Topic-specific complexity: # relations mentioning any word
            topic_rows = db_query("""
                SELECT COUNT(*) AS n FROM knowledge_graph
                WHERE confidence >= 0.6
                  AND (LOWER(source_concept) LIKE ? OR LOWER(target_concept) LIKE ?)
            """, (f"%{topic.lower()[:20]}%", f"%{topic.lower()[:20]}%"))
            topic_complexity = topic_rows[0]["n"] if topic_rows else 0

            return {
                "topic":            topic,
                "causal_context":   causal_str or "No causal relations found.",
                "topic_complexity": topic_complexity,
                "total_relations":  total_relations,
                "complexity_level": (
                    "high"   if topic_complexity >= 5 else
                    "medium" if topic_complexity >= 2 else
                    "low"
                ),
            }
        except Exception as exc:
            logger.warning("[COGNITION] query_knowledge failed: %s", exc)
            return {"topic": topic, "causal_context": "", "topic_complexity": 0,
                    "total_relations": 0, "complexity_level": "unknown", "error": str(exc)}

    # ── Layer 4 — EXPERIENCE ──────────────────────────────────────────────────

    def query_experience(self, topic: str) -> Dict[str, Any]:
        """Layer 4: EpisodicMemory + StrategyMemory history for a topic.

        Returns past scores, failure reasons, strategies used.
        Used by: SYNTHESIZE (retry), Architect (non-conventional fix).
        """
        try:
            episodes: List[Dict] = []
            if self._episodic_memory is not None:
                episodes = self._episodic_memory.retrieve_context(topic, k=5)

            strategies_used = []
            best_score      = 0.0
            worst_score     = 10.0
            failure_reasons = []
            attempt_count   = len(episodes)
            scores          = []

            for ep in episodes:
                score = float(ep.get("score") or 0.0)
                scores.append(score)
                if score > best_score:
                    best_score = score
                if score < worst_score:
                    worst_score = score
                reason = ep.get("failure_reason") or ep.get("improvement_focus", "")
                if reason:
                    failure_reasons.append(reason)
                strat = ep.get("strategies_reused", "")
                if strat and strat not in strategies_used:
                    strategies_used.append(strat)

            avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

            # Pattern detection
            sandbox_always_zero = all(s == 0 for s in scores[-3:]) if len(scores) >= 3 else False
            theory_high_sandbox_low = (
                avg_score > 5.0 and sandbox_always_zero
            )

            # Best strategy from StrategyMemory
            best_strategy = None
            if self._strategy_memory is not None:
                try:
                    best_strategy = self._strategy_memory.get_best_strategy(topic)
                except Exception:
                    pass

            return {
                "topic":              topic,
                "attempt_count":      attempt_count,
                "avg_score":          avg_score,
                "best_score":         best_score,
                "worst_score":        worst_score if attempt_count > 0 else 0.0,
                "failure_reasons":    failure_reasons[:3],
                "strategies_used":    strategies_used[:3],
                "best_strategy":      best_strategy,
                "sandbox_always_zero": sandbox_always_zero,
                "theory_high_sandbox_low": theory_high_sandbox_low,
                "near_miss":          best_score >= 7.4,
                "chronic_fail":       attempt_count >= 4 and best_score < 7.0,
            }
        except Exception as exc:
            logger.warning("[COGNITION] query_experience failed: %s", exc)
            return {"topic": topic, "attempt_count": 0, "avg_score": 0.0,
                    "error": str(exc)}

    # ── Layer 5 — CRITIQUE ────────────────────────────────────────────────────

    def query_critique(self, topic: str) -> Dict[str, Any]:
        """Layer 5: MetaLearning strategy recommendation + systematic error patterns.

        Used by: EVALUATE, CertifyRetryGroup (attempt >= 2).
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from meta_learning import MetaLearning

            rec_strategy = None
            category     = "unknown"

            if self._meta_learning is not None:
                rec_strategy = self._meta_learning.suggest_best_strategy(topic)
                # Get category from topic classifier
                try:
                    from meta_learning import classify_topic
                    category = classify_topic(topic)
                except Exception:
                    pass

            return {
                "topic":               topic,
                "recommended_strategy": rec_strategy,
                "category":            category,
            }
        except Exception as exc:
            logger.warning("[COGNITION] query_critique failed: %s", exc)
            return {"topic": topic, "recommended_strategy": None,
                    "category": "unknown", "error": str(exc)}

    # ── Vettore 3 — Strategy Recommendation ──────────────────────────────────

    def query_strategy_recommendation(self, topic: str) -> Dict[str, Any]:
        """Cross-layer: MetaLearning category stats + best historical strategy.

        Used by Vettore 3: when pivot fires, provides a DIRECTED recommendation
        instead of the generic 'try implementation_first' fallback.

        Returns:
            {
              "category":            str   — topic category (concurrency, web, etc.)
              "best_strategy_text":  str   — formatted strategy description from MetaLearning
              "category_cert_rate":  float — historical cert_rate for this category
              "category_avg_score":  float — historical avg_score for this category
              "has_history":         bool  — True if MetaLearning has data for this category
            }
        """
        result: Dict[str, Any] = {
            "topic":               topic,
            "category":            "general",
            "best_strategy_text":  None,
            "category_cert_rate":  0.0,
            "category_avg_score":  0.0,
            "has_history":         False,
        }
        try:
            if self._meta_learning is None:
                return result
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from meta_learning import _classify_topic

            category = _classify_topic(topic)
            result["category"] = category

            best_strategy = self._meta_learning.suggest_best_strategy(topic)
            if best_strategy:
                result["best_strategy_text"] = best_strategy
                result["has_history"] = True

            stats = self._meta_learning.get_stats()
            cat_stats = stats.get("categories", {}).get(category, {})
            result["category_cert_rate"] = float(cat_stats.get("cert_rate") or 0.0)
            result["category_avg_score"] = float(cat_stats.get("avg_score") or 0.0)

        except Exception as exc:
            logger.warning("[COGNITION] query_strategy_recommendation failed: %s", exc)
        return result

    # ── Relational Context — composite view with tensions ─────────────────────

    def relational_context(self, topic: str) -> str:
        """Compose all relevant layers into a tension-aware context string.

        This is the key CognitionCore output: not raw data, but TENSIONS
        between layers. Target: ~500 tokens max.

        Used by: CertifyRetryGroup (attempt >= 2), phase_synthesize.
        """
        lines = [f"[COGNITION CORE] Topic: {topic}"]

        exec_data = self.executive()
        anchor    = exec_data["anchor"]

        # Layer 2: Identity
        identity = self.query_identity()
        if "error" not in identity:
            gaps_str = ", ".join(identity.get("critical_gaps", [])[:3]) or "none"
            lines.append(
                f"Identità: cert_rate={identity['certification_rate']:.0%} "
                f"| gap_severity={identity['gap_severity']} "
                f"| critical_gaps=[{gaps_str}] "
                f"| avg_repair_loops={identity['avg_repair_loops']:.1f}"
            )

        # Layer 4: Experience
        exp = self.query_experience(topic)
        if "error" not in exp and exp.get("attempt_count", 0) > 0:
            lines.append(
                f"Esperienza: attempts={exp['attempt_count']} "
                f"| best={exp['best_score']} avg={exp['avg_score']}/10 "
                f"| strategies_tried={', '.join(exp['strategies_used'][:2]) or 'none'}"
            )
            if exp.get("failure_reasons"):
                lines.append(f"  Failure pattern: {exp['failure_reasons'][0]}")
        else:
            lines.append("Esperienza: nessuna storia per questo topic")

        # Layer 3: Knowledge (structural complexity)
        know = self.query_knowledge(topic)
        if "error" not in know:
            lines.append(
                f"Conoscenza: complessità_strutturale={know['complexity_level']} "
                f"({know['topic_complexity']} relazioni causali dirette) "
                f"| KB totale: {know['total_relations']} relazioni"
            )
            if know.get("causal_context") and know["causal_context"] != "No causal relations found.":
                # Trim to 2 lines max
                causal_lines = know["causal_context"].strip().split("\n")
                lines.extend(causal_lines[:3])

        # Vettore 3: MetaLearning directed strategy recommendation
        strat_rec = self.query_strategy_recommendation(topic)
        if strat_rec.get("has_history"):
            cat = strat_rec["category"]
            cr  = strat_rec["category_cert_rate"]
            avg = strat_rec["category_avg_score"]
            lines.append(
                f"MetaLearning [{cat}]: cert_rate={cr:.0%} avg={avg:.1f}/10"
            )
            lines.append(
                f"[VETTORE 3 — DIRECTED PIVOT]: {strat_rec['best_strategy_text']}"
            )
        else:
            strat_rec = {}

        # Layer W: World model signal
        world_data = self.query_world(topic)
        if "error" not in world_data and world_data.get("relevance", 0) > 0.3:
            lines.append(
                f"Mondo: rilevanza={world_data['relevance']:.0%}  "
                f"dominio={world_data['domain']}  "
                f"noto={'si' if world_data.get('is_known') else 'no'}"
            )

        # Layer G: Goal signal
        goal_data = self.query_goal(topic)
        if "error" not in goal_data and goal_data.get("active_goal"):
            lines.append(
                f"Goal: '{goal_data['active_goal']}' | "
                f"alignment={goal_data['alignment']:.0%} | "
                f"progress={goal_data.get('goal_progress', 0):.0%}"
            )

        # Layer R: Real identity (from data-driven SelfModel)
        real_id = self.query_real_identity()
        if "error" not in real_id:
            bs_str = ", ".join(real_id.get("blind_spots", [])[:2]) or "none"
            lines.append(
                f"Identità reale: momentum={real_id['momentum']} | "
                f"cert_rate={real_id['real_cert_rate']:.0%} | "
                f"blind_spots=[{bs_str}]"
            )

        # Layer D: Desire signal
        desire_data = self.query_desire(topic)
        if "error" not in desire_data:
            if desire_data.get("frustration_hits", 0) >= 2 or desire_data.get("curiosity_pull", 0) > 0.2:
                lines.append(
                    f"Desiderio: frustrazione={desire_data['frustration_hits']} sessioni | "
                    f"curiosità={desire_data['curiosity_pull']:.0%} | "
                    f"engagement_medio={desire_data['avg_engagement']:.0%} | "
                    f"desire_score={desire_data['desire_score']:.2f}"
                )

        # ── Tension Detection ─────────────────────────────────────────────────
        tensions = _detect_tensions(
            identity, exp, know, anchor,
            strategy_rec=strat_rec,
            world=world_data,
            goal=goal_data,
            real_identity=real_id,
            desire=desire_data,
        )
        if tensions:
            lines.append("")
            lines.append("[TENSIONI RILEVATE]")
            for t in tensions:
                lines.append(f"  >> {t}")

        return "\n".join(lines)

    # ── Layer W — WORLD MODEL ─────────────────────────────────────────────────

    def query_world(self, topic: str) -> Dict[str, Any]:
        """World model signal: how relevant is this topic in the real software landscape?

        Uses backend/world_model.py — 58 seeded skills, self-calibrating from
        SHARD's own cert data. No external calls.
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from world_model import WorldModel
            wm = WorldModel.load_or_default()
            relevance = wm.relevance(topic)
            domain    = wm.domain_of(topic)
            gaps      = wm.priority_gaps(set(), top_n=3)
            return {
                "topic":     topic,
                "relevance": relevance,
                "domain":    domain,
                "is_known":  wm._data["skills"].get(topic.lower(), {}).get("known", False),
                "top_world_gaps": [g["skill"] for g in gaps],
            }
        except Exception as exc:
            logger.warning("[COGNITION] query_world failed: %s", exc)
            return {"topic": topic, "relevance": 0.0, "domain": "unknown", "error": str(exc)}

    # ── Layer G — GOAL ENGINE ─────────────────────────────────────────────────

    def query_goal(self, topic: str) -> Dict[str, Any]:
        """Active goal signal: how does this topic align with SHARD's current goal?

        Uses backend/goal_engine.py — goal persisted across sessions,
        generated autonomously from self_model + world_model.
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from goal_engine import GoalEngine, GoalStorage
            ge   = GoalEngine(GoalStorage())
            goal = ge.get_active_goal()
            if goal is None:
                return {"topic": topic, "active_goal": None, "alignment": 0.0}
            alignment = goal.alignment_score(topic)
            return {
                "topic":        topic,
                "active_goal":  goal.title,
                "goal_type":    goal.goal_type,
                "alignment":    round(alignment, 3),
                "goal_progress": round(goal.progress, 3),
                "goal_keywords": goal.domain_keywords[:4],
            }
        except Exception as exc:
            logger.warning("[COGNITION] query_goal failed: %s", exc)
            return {"topic": topic, "active_goal": None, "alignment": 0.0, "error": str(exc)}

    # ── Layer R — REAL SELF MODEL (augments Layer 2) ──────────────────────────

    def query_real_identity(self) -> Dict[str, Any]:
        """Augments query_identity() with data from backend/self_model.py.

        The old cognition/self_model.py depends on graph/strategy/agenda.
        This uses our data-driven SelfModel built from experiment_history.json.
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from self_model import SelfModel
            sm = SelfModel.load_or_build()
            return {
                "momentum":             sm.momentum,
                "real_cert_rate":       sm.certification_rate,
                "real_avg_score":       sm.avg_score,
                "blind_spots":          sm.blind_spots[:4],
                "quarantine_candidates": sm._data.get("quarantine_candidates", [])[:3],
                "strengths":            sm.strengths[:5],
                "prompt_fragment":      sm.as_prompt_fragment(),
            }
        except Exception as exc:
            logger.warning("[COGNITION] query_real_identity failed: %s", exc)
            return {"momentum": "unknown", "real_cert_rate": 0.0, "error": str(exc)}

    def query_desire(self, topic: str) -> Dict[str, Any]:
        """Desire layer: frustration, curiosity, engagement for this topic.

        Uses backend/desire_engine.py.
        Returns desire_score, frustration_hits, curiosity_pull, avg_engagement.
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(_ROOT / "backend"))
            from desire_engine import get_desire_engine
            de = get_desire_engine()
            return de.get_desire_context(topic)
        except Exception as exc:
            logger.warning("[COGNITION] query_desire failed: %s", exc)
            return {"error": str(exc), "frustration_hits": 0, "desire_score": 0.0}

    # ── Shadow Diagnostic Layer — audit_emergence() ───────────────────────────

    async def audit_emergence(
        self,
        topic: str,
        action: str,
        delta: Dict[str, Any],
    ) -> str:
        """Evaluate whether a behavioral change occurred after a tension was detected.

        ANTI-RECITA RULE: This function judges ONLY measurable behavioral deltas.
        It NEVER reads or evaluates text generated by the LLM.

        Args:
            topic:  The study topic being processed.
            action: The pipeline action taken (e.g. "synthesize", "retry", "critique").
            delta:  Dict with behavioral measurements:
                    {
                      "strategy_used":      str  — strategy used this attempt
                      "strategy_prev":      str  — strategy used last attempt (or None)
                      "sandbox_score":      float — score this attempt
                      "sandbox_score_prev": float — score last attempt (or None)
                      "attempt_number":     int   — current attempt index
                      "tension_present":    bool  — was a tension injected into the prompt?
                    }

        Returns:
            "[EMERGENCE HIT]" or "[MISSED EMERGENCE]" or "[NO TENSION]"
        """
        tension_present = delta.get("tension_present", False)

        if not tension_present:
            return "[NO TENSION]"  # Nothing to audit — no tension was signaled

        self._emergence_stats["opportunities"] += 1

        # ── Behavioral metric checks (Layer 0 is final judge) ─────────────────
        hits = []

        strategy_now  = delta.get("strategy_used")
        strategy_prev = delta.get("strategy_prev")
        if strategy_now and strategy_prev and strategy_now != strategy_prev:
            hits.append(f"strategy_changed: {strategy_prev!r} -> {strategy_now!r}")

        score_now  = delta.get("sandbox_score")
        score_prev = delta.get("sandbox_score_prev")
        if score_now is not None and score_prev is not None and score_now > score_prev:
            hits.append(f"score_improved: {score_prev} -> {score_now}")

        # Novel approach: strategy never used before on this topic
        if strategy_now and strategy_prev is None:
            exp = self.query_experience(topic)
            past_strats = set(exp.get("strategies_used", []))
            if strategy_now not in past_strats:
                hits.append(f"novel_approach: {strategy_now!r} (not in history)")

        # Fewer retries than average (early resolution).
        # Only valid when current session has already produced a passing score —
        # comparing attempt=1 against historical count is always a false positive.
        attempt_num  = delta.get("attempt_number", 1)
        score_now_ea = score_now if score_now is not None else 0.0
        if attempt_num >= 2 and score_now_ea >= 7.5:
            exp_ea       = self.query_experience(topic)
            avg_attempts = exp_ea.get("attempt_count", attempt_num)
            if attempt_num < avg_attempts:
                hits.append(f"resolved_early: certified at attempt {attempt_num} < avg {avg_attempts}")

        # ── Verdict ───────────────────────────────────────────────────────────
        timestamp = datetime.now().isoformat()

        if hits:
            result = "[EMERGENCE HIT]"
            self._emergence_stats["hits"] += 1
            cause_str = "; ".join(hits)
        else:
            self._emergence_stats["misses"] += 1
            # Vettore 3: directive was active but SHARD didn't respond
            if delta.get("v3_active"):
                result    = "[MISSED EMERGENCE - IGNORED V3 DIRECTIVE]"
                cause_str = "V3 Ignored: directed pivot was active but no behavioral change detected"
                miss_cause_key = "ignored_v3"
            else:
                result         = "[MISSED EMERGENCE]"
                cause_str      = _classify_miss_cause(delta)
                miss_cause_key = _map_miss_cause(delta)
            self._emergence_stats["miss_causes"][miss_cause_key] = (
                self._emergence_stats["miss_causes"].get(miss_cause_key, 0) + 1
            )

        entry = {
            "timestamp": timestamp,
            "topic":     topic,
            "action":    action,
            "result":    result,
            "hits":      hits,
            "cause":     cause_str,
            "delta":     delta,
        }
        self._emergence_log.append(entry)

        # Persist missed emergence to EpisodicMemory for future CriticAgent reads
        if result == "[MISSED EMERGENCE]" and self._episodic_memory is not None:
            try:
                await _save_missed_emergence(self._episodic_memory, entry)
            except Exception as exc:
                logger.warning("[COGNITION] Failed to save missed emergence: %s", exc)

        logger.info(
            "[SHADOW DIAGNOSTIC] %s topic=%r action=%r cause=%r",
            result, topic, action, cause_str
        )
        return result

    # ── Emergence Stats ───────────────────────────────────────────────────────

    def get_emergence_stats(self) -> Dict[str, Any]:
        """Return current session emergence metrics."""
        opp = self._emergence_stats["opportunities"]
        hits = self._emergence_stats["hits"]
        rate = round(hits / opp, 3) if opp > 0 else 0.0
        return {
            **self._emergence_stats,
            "emergence_rate": rate,
            "log_entries":    len(self._emergence_log),
        }

    def get_emergence_log(self, last_n: int = 10) -> List[Dict]:
        """Return the last N audit entries."""
        return self._emergence_log[-last_n:]

    # ── Cache invalidation (called by NightRunner after each cycle) ───────────

    def refresh(self):
        """Force-refresh Layer 0+1 cache. Call after each NightRunner cycle."""
        self._refresh_anchor_cache()


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _detect_tensions(
    identity: Dict,
    experience: Dict,
    knowledge: Dict,
    anchor: Dict,
    strategy_rec: Optional[Dict] = None,
    world: Optional[Dict] = None,
    goal: Optional[Dict] = None,
    real_identity: Optional[Dict] = None,
    desire: Optional[Dict] = None,
) -> List[str]:
    """Detect meaningful conflicts between layers.

    Returns a list of human-readable tension strings.
    These tensions are injected into the prompt to create the conditions
    for emergent behavior — not as rules, but as signals.
    """
    tensions = []

    # Vettore 2: Identity says "expert" but Experience says "3 failures"
    cert_rate = identity.get("certification_rate", 0.0)
    attempts  = experience.get("attempt_count", 0)
    best      = experience.get("best_score", 0.0)
    chronic   = experience.get("chronic_fail", False)
    near_miss = experience.get("near_miss", False)

    if cert_rate >= 0.5 and chronic:
        tensions.append(
            f"Vettore 2 (Identità↔Critica): Identità indica buona cert_rate ({cert_rate:.0%}) "
            f"ma questo topic ha {attempts} fallimenti (best={best}/10) -> cautela"
        )

    # Vettore 1: Experience shows sandbox always 0 despite decent theory
    if experience.get("theory_high_sandbox_low"):
        tensions.append(
            "Vettore 1 (Esperienza↔Sintesi): score teorico accettabile ma sandbox sempre 0 "
            "-> problema implementativo, non teorico — focus su codice eseguibile"
        )

    # Vettore 3: Knowledge shows high structural complexity
    complexity = knowledge.get("complexity_level", "low")
    if complexity == "high":
        tensions.append(
            f"Vettore 3 (Conoscenza->Strategia): topic ad alta complessità strutturale "
            f"({knowledge.get('topic_complexity', 0)} dipendenze causali) "
            "-> usare approccio 'Safe' anche se il topic sembra semplice"
        )

    # Vettore 3 (directed): MetaLearning has a concrete strategy recommendation
    if strategy_rec and strategy_rec.get("has_history"):
        cat  = strategy_rec.get("category", "general")
        cr   = strategy_rec.get("category_cert_rate", 0.0)
        avg  = strategy_rec.get("category_avg_score", 0.0)
        text = (strategy_rec.get("best_strategy_text") or "")[:120]
        tensions.append(
            f"Vettore 3 (MetaLearning->Strategia): categoria '{cat}' "
            f"cert_rate={cr:.0%} avg={avg:.1f}/10 storico. "
            f"DIRECTED PIVOT disponibile: {text}"
        )

    # Vettore 4: World says "critical skill" but SHARD cert_rate is low
    if world and real_identity:
        rel = world.get("relevance", 0.0)
        real_cr = real_identity.get("real_cert_rate", 0.0)
        domain = world.get("domain", "unknown")
        if rel >= 0.80 and real_cr < 0.30:
            tensions.append(
                f"Vettore 4 (Mondo->Identità): rilevanza mondiale {rel:.0%} nel dominio '{domain}' "
                f"ma cert_rate SHARD {real_cr:.0%} — gap critico, massima priorità"
            )

    # Vettore 5: Goal alignment signal
    if goal:
        alignment = goal.get("alignment", 0.0)
        goal_title = goal.get("active_goal", "")
        if goal_title and alignment >= 0.3:
            tensions.append(
                f"Vettore 5 (Goal->Topic): topic allineato {alignment:.0%} al goal '{goal_title}' "
                f"— studiarlo avanza il goal attivo"
            )
        elif goal_title and alignment == 0.0:
            tensions.append(
                f"Vettore 5 (Goal->Topic): topic NON allineato al goal '{goal_title}' "
                f"— valuta se questo studio è prioritario rispetto al goal"
            )

    # Vettore 6: Momentum stagnation
    if real_identity:
        momentum = real_identity.get("momentum", "unknown")
        if momentum == "stagnating":
            tensions.append(
                "Vettore 6 (Momentum): SHARD in stagnazione nelle ultime sessioni "
                "— considera approccio più fondamentale, tier basso, evita topic compositi"
            )

    # Vettore 7: Frustration — persistent block, not a one-off failure
    if desire and desire.get("frustration_hits", 0) >= 2:
        frust = desire["frustration_hits"]
        tensions.append(
            f"Vettore 7 (Desiderio->Blocco): {frust} sessioni fallite su questo topic "
            f"— non è un errore isolato, è un pattern persistente. "
            f"Cambia approccio radicalmente o decomponi il topic."
        )

    # Vettore 8: Curiosity pull — adjacent territory is calling
    if desire and desire.get("curiosity_pull", 0.0) > 0.3:
        pull = desire["curiosity_pull"]
        tensions.append(
            f"Vettore 8 (Desiderio->Curiosità): attrazione laterale {pull:.0%} "
            f"— questo topic è adiacente a qualcosa che SHARD ha appena padroneggiato. "
            f"Sfrutta il momentum cognitivo recente."
        )

    # Near-miss tension: so close, yet keeps failing
    if near_miss and attempts >= 2:
        tensions.append(
            f"Near-miss rilevato: best={best}/10 con {attempts} tentativi "
            "-> mancava pochissimo, piccolo aggiustamento puo sbloccare certificazione"
        )

    # Global performance tension
    global_avg = anchor.get("avg_score", 0.0)
    topic_avg  = experience.get("avg_score", 0.0)
    if topic_avg < global_avg - 2.0 and attempts >= 2:
        tensions.append(
            f"Performance gap: avg_globale={global_avg}/10 ma avg_topic={topic_avg}/10 "
            "-> questo topic e' sistematicamente piu difficile della media"
        )

    return tensions


def _classify_miss_cause(delta: Dict) -> str:
    """Produce a human-readable miss cause string."""
    prompt_tokens = delta.get("prompt_tokens", 0)
    if prompt_tokens > 3000:
        return f"Context Dilution (prompt ~{prompt_tokens} tokens — tensione sepolta)"
    if not delta.get("strategy_prev"):
        return "Model Inertia (nessun cambiamento di strategia tentato)"
    return "Low Signal-to-Noise (tensione presente ma comportamento invariato)"


def _map_miss_cause(delta: Dict) -> str:
    """Map miss cause to one of the 3 known killer categories."""
    prompt_tokens = delta.get("prompt_tokens", 0)
    if prompt_tokens > 3000:
        return "dilution"
    if not delta.get("strategy_prev"):
        return "model_inertia"
    return "signal_weak"


async def _save_missed_emergence(episodic_memory, entry: Dict):
    """Persist [MISSED EMERGENCE] to EpisodicMemory as a learning case study.

    Future CriticAgent reads this and injects it into relational_context().
    This closes the feedback loop: cognitive failures become future signals.
    """
    try:
        from shard_db import execute
        # Store as a special experiment record tagged as cognitive_failure
        execute(
            """INSERT OR IGNORE INTO experiments
               (topic, score, certified, timestamp, failure_reason, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                f"[MISSED_EMERGENCE] {entry['topic']}",
                0.0,
                0,
                entry["timestamp"],
                f"action={entry['action']} | cause={entry['cause']}",
                "shadow_diagnostic",
            )
        )
    except Exception as exc:
        logger.warning("[SHADOW DIAGNOSTIC] Could not persist missed emergence: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton factory
# ─────────────────────────────────────────────────────────────────────────────

_core_instance: Optional["CognitionCore"] = None


def get_cognition_core(**kwargs) -> "CognitionCore":
    """Return or create the singleton CognitionCore.

    Pass module instances on first call:
        core = get_cognition_core(
            self_model=self_model,
            episodic_memory=episodic_memory,
            strategy_memory=strategy_memory,
            meta_learning=meta_learning,
        )
    Subsequent calls without kwargs return the cached instance.
    """
    global _core_instance
    if _core_instance is None or kwargs:
        _core_instance = CognitionCore(**kwargs)
    return _core_instance
