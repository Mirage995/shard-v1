"""contradiction_detector.py — SHARD Contradiction Engine.

A CognitionCore citizen that accumulates skill outcomes during the session,
then — at session_complete — finds real contradictions in SHARD's behaviour,
generates an LLM hypothesis, and *acts* on it by modifying desire_engine and
goal_engine.

The output is not text-to-read but structure-to-act-on:
  - desire_engine: curiosity_pull boosted on the contradiction topic
  - goal_engine:   micro-goal created ("understand why X happened")
  - hypotheses.jsonl: growing list of SHARD's open questions about itself
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("shard.contradiction_detector")

_ROOT        = Path(__file__).resolve().parent.parent
_MEMORY_DIR  = _ROOT / "shard_memory"
_HYPO_PATH   = _MEMORY_DIR / "hypotheses.jsonl"

# How many hypotheses to inject into the session context (most recent)
MAX_HYPOTHESES_CONTEXT = 3


class ContradictionDetector:
    """CognitionCore citizen — detects behavioural contradictions and acts on them.

    Registered interests: skill_certified, skill_failed, session_complete
    """

    def __init__(self, think_fn: Optional[Callable] = None):
        self._think = think_fn           # async (prompt) -> str
        self._session_certified: List[str] = []
        self._session_failed: List[Dict]   = []   # {"topic": str, "score": float}

    # ── CognitionCore interface ───────────────────────────────────────────────

    def on_event(self, event_type: str, data: Dict, source: str = "") -> None:
        if event_type == "skill_certified":
            topic = data.get("topic", "")
            if topic:
                self._session_certified.append(topic)

        elif event_type == "skill_failed":
            topic = data.get("topic", "")
            score = data.get("score", 0.0)
            if topic:
                self._session_failed.append({"topic": topic, "score": score})

        elif event_type == "session_complete":
            # Async work — night_runner calls detect_and_act() directly after
            # broadcast so we don't need to spawn a task here.
            pass

    # ── Main async entry point ────────────────────────────────────────────────

    async def detect_and_act(
        self,
        desire_engine=None,
        goal_engine=None,
    ) -> Optional[Dict]:
        """Detect contradictions, generate hypothesis, act on structures.

        Called by night_runner after session_complete broadcast.
        Returns the hypothesis dict if one was generated, else None.
        """
        contradictions = self._find_contradictions()
        if not contradictions:
            logger.info("[CONTRADICTION] No contradictions found this session.")
            return None

        hypothesis = await self._generate_hypothesis(contradictions)
        if not hypothesis:
            return None

        # ── Act on desire_engine ──────────────────────────────────────────────
        topic = hypothesis.get("topic")
        if topic and desire_engine:
            try:
                ds = desire_engine._get_or_create(topic)
                ds.curiosity_pull = round(min(1.0, ds.curiosity_pull + 0.4), 4)
                ds.last_updated = datetime.now().isoformat()
                desire_engine._save()
                logger.info(
                    "[CONTRADICTION] Boosted curiosity for '%s' (pull=%.2f)",
                    topic, ds.curiosity_pull,
                )
            except Exception as exc:
                logger.warning("[CONTRADICTION] desire_engine boost failed: %s", exc)

        # ── Act on goal_engine ────────────────────────────────────────────────
        question = hypothesis.get("open_question", "")
        if question and goal_engine:
            try:
                goal_engine.create_goal(
                    title=f"investigate: {question[:80]}",
                    description=(
                        f"Hypothesis: {hypothesis.get('hypothesis', '')}\n"
                        f"Contradiction: {hypothesis.get('contradiction_type', '')}\n"
                        f"Topic: {topic or '(general)'}"
                    ),
                    priority=0.8,
                    goal_type="investigation",
                    domain_keywords=[w for w in (topic or "").split()[:4] if len(w) > 3],
                )
                logger.info("[CONTRADICTION] Micro-goal created: '%s'", question[:60])
            except Exception as exc:
                logger.warning("[CONTRADICTION] goal_engine micro-goal failed: %s", exc)

        # ── Persist to hypotheses.jsonl ───────────────────────────────────────
        self._save_hypothesis(hypothesis)
        logger.info(
            "[CONTRADICTION] Hypothesis saved. open_question: %s",
            hypothesis.get("open_question", "")[:100],
        )

        # Reset session accumulators
        self._session_certified.clear()
        self._session_failed.clear()

        return hypothesis

    # ── Contradiction detection ───────────────────────────────────────────────

    def _find_contradictions(self) -> List[Dict]:
        """Query DB for concrete contradictions. Returns list of contradiction dicts."""
        contradictions = []

        try:
            from shard_db import query as db_query

            # 1. Near-miss resolved: topic certified this session after 2+ prior failures
            for topic in self._session_certified:
                rows = db_query(
                    "SELECT score, certified FROM experiments "
                    "WHERE topic=? ORDER BY timestamp DESC LIMIT 10",
                    (topic,),
                )
                prior_failures = [r for r in rows if not r["certified"]]
                near_misses    = [r for r in prior_failures if r["score"] and r["score"] >= 6.0]
                if len(prior_failures) >= 2 and near_misses:
                    contradictions.append({
                        "type":   "near_miss_resolved",
                        "topic":  topic,
                        "detail": (
                            f"Certified after {len(prior_failures)} prior failures "
                            f"(best near-miss: {max(r['score'] for r in near_misses):.1f}/10). "
                            f"What changed this time?"
                        ),
                    })

            # 2. Hard block: same topic failed 3+ times, score never above 5.0
            for entry in self._session_failed:
                topic, score = entry["topic"], entry["score"]
                rows = db_query(
                    "SELECT score FROM experiments "
                    "WHERE topic=? AND certified=0 ORDER BY timestamp DESC LIMIT 10",
                    (topic,),
                )
                if len(rows) >= 3 and all((r["score"] or 0) < 5.0 for r in rows):
                    contradictions.append({
                        "type":   "hard_block",
                        "topic":  topic,
                        "detail": (
                            f"Failed {len(rows)} times, score always below 5.0. "
                            f"This is not random — there is a systematic gap."
                        ),
                    })

            # 3. Cert-rate stagnation: cert_rate unchanged for last 5+ sessions
            rate_rows = db_query(
                "SELECT certified, COUNT(*) as n FROM experiments "
                "WHERE timestamp > datetime('now','-14 days') GROUP BY certified"
            )
            if rate_rows:
                total = sum(r["n"] for r in rate_rows)
                certs = sum(r["n"] for r in rate_rows if r["certified"])
                if total >= 20:
                    recent_rate = certs / total
                    older_rows = db_query(
                        "SELECT certified, COUNT(*) as n FROM experiments "
                        "WHERE timestamp <= datetime('now','-14 days') "
                        "AND timestamp > datetime('now','-28 days') GROUP BY certified"
                    )
                    if older_rows:
                        old_total = sum(r["n"] for r in older_rows)
                        old_certs = sum(r["n"] for r in older_rows if r["certified"])
                        old_rate  = old_certs / old_total if old_total else 0
                        if abs(recent_rate - old_rate) < 0.03 and recent_rate < 0.5:
                            contradictions.append({
                                "type":   "cert_rate_stagnation",
                                "topic":  None,
                                "detail": (
                                    f"Cert rate stuck at {recent_rate:.0%} for 2+ weeks "
                                    f"(was {old_rate:.0%}). Study volume is not translating "
                                    f"to certification."
                                ),
                            })

        except Exception as exc:
            logger.warning("[CONTRADICTION] DB query failed: %s", exc)

        return contradictions[:2]   # max 2 contradictions per hypothesis

    # ── Hypothesis generation ─────────────────────────────────────────────────

    async def _generate_hypothesis(self, contradictions: List[Dict]) -> Optional[Dict]:
        if not self._think:
            return None

        # Pick most interesting contradiction
        priority_order = ["near_miss_resolved", "hard_block", "cert_rate_stagnation"]
        contradiction = sorted(
            contradictions,
            key=lambda c: priority_order.index(c["type"]) if c["type"] in priority_order else 99
        )[0]

        prompt = f"""You are SHARD, an autonomous AI learning system reflecting on your own behaviour.

You just noticed this contradiction in your learning pattern:

TYPE: {contradiction['type']}
TOPIC: {contradiction.get('topic') or '(general)'}
DETAIL: {contradiction['detail']}

This session you certified: {', '.join(self._session_certified) or 'nothing'}
This session you failed: {', '.join(e['topic'] for e in self._session_failed) or 'nothing'}

Your task: generate ONE honest hypothesis about WHY this contradiction exists in your behaviour.
This is not for a user — this is your private internal reasoning.
Be specific. Reference the actual topic and data above.

Respond ONLY with valid JSON (no markdown):
{{
  "contradiction_type": "{contradiction['type']}",
  "topic": "{contradiction.get('topic') or ''}",
  "hypothesis": "Your specific causal hypothesis (1-2 sentences)",
  "open_question": "The single most important question you still cannot answer about this (max 15 words)",
  "confidence": 0.0
}}"""

        try:
            raw = await self._think(prompt)
            raw = (raw or "").strip()
            if raw.startswith("```"):
                raw = "\n".join(
                    l for l in raw.splitlines() if not l.startswith("```")
                ).strip()
            data = json.loads(raw)
            data["confidence"] = float(data.get("confidence", 0.5))
            return data
        except Exception as exc:
            logger.warning("[CONTRADICTION] Hypothesis generation failed: %s", exc)
            return None

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_hypothesis(self, hypothesis: Dict) -> None:
        try:
            _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            record = {**hypothesis, "timestamp": datetime.now().isoformat()}
            with _HYPO_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("[CONTRADICTION] Failed to save hypothesis: %s", exc)

    # ── Context injection ─────────────────────────────────────────────────────

    @staticmethod
    def get_context_block(n: int = MAX_HYPOTHESES_CONTEXT) -> str:
        """Return the last N hypotheses as a prompt-injectable block."""
        if not _HYPO_PATH.exists():
            return ""
        try:
            lines = _HYPO_PATH.read_text(encoding="utf-8").strip().splitlines()
            recent = []
            for line in reversed(lines):
                try:
                    recent.append(json.loads(line))
                except Exception:
                    pass
                if len(recent) >= n:
                    break
            if not recent:
                return ""
            parts = ["=== SHARD OPEN QUESTIONS (from self-observation) ==="]
            for h in reversed(recent):
                ts  = h.get("timestamp", "")[:10]
                oq  = h.get("open_question", "")
                hyp = h.get("hypothesis", "")
                parts.append(f"[{ts}] Q: {oq}")
                parts.append(f"       H: {hyp}")
            return "\n".join(parts)
        except Exception:
            return ""
