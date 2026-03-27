"""improvement_engine.py — SHARD's proactive self-improvement scheduler.

Consumes ImprovementTickets from SelfAnalyzer and converts them into a
prioritised topic queue that NightRunner drains before choosing any topic.

Decision logic per ticket type:
  retry_chronic_failure  avg < 3.5  → DECOMPOSE: split compound topic into atoms
  retry_chronic_failure  avg ≥ 3.5  → INJECT directly (close enough to work)
  certify_near_miss                 → INJECT directly (one push needed)
  retry_grown                       → INJECT directly (new prereqs available)
  fill_capability_gap               → INJECT the mapped study topic
  stagnation_probe                  → INJECT a cross-domain challenge

State is persisted to shard_memory/improvement_queue.json so the queue
survives process restarts and NightRunner can consume it across sessions.
"""
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("shard.improvement_engine")

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT        = Path(__file__).parent.parent.resolve()
_QUEUE_FILE  = _ROOT / "shard_memory" / "improvement_queue.json"

# ── Tunables ───────────────────────────────────────────────────────────────────
DECOMPOSE_THRESHOLD  = 3.5   # avg score below this → decompose compound topics
MAX_QUEUE_SIZE       = 12    # hard cap on persisted queue length
MAX_INJECT_PER_RUN   = 8     # tickets evaluated per engine run
MIN_TOPIC_WORDS      = 2     # minimum words to be a valid injected topic

# Contamination tokens — reject topics containing these
_GARBAGE_TOKENS = {
    "chiedo", "facendo", "presente", "present", "silenzio",
    "potrei", "vorrei", "penso", "forse", "dovrei",
    "riflessione", "sistema stabile", "momento per",
}


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class EngineDecision:
    """Represents the engine's decision for a single ticket."""
    ticket_id:   str
    ticket_type: str
    action:      str            # "inject" | "decompose" | "skip_garbage" | "skip_duplicate" | "skip_processed"
    topics:      List[str]      # final topics to queue (0–N)
    reason:      str


@dataclass
class EngineResult:
    """Summary of a single engine run."""
    run_at:          str
    tickets_evaluated: int
    decisions:       List[EngineDecision]
    topics_queued:   List[str]   # newly added to queue this run
    queue_size:      int         # total pending after this run

    def summary(self) -> str:
        actions = {}
        for d in self.decisions:
            actions[d.action] = actions.get(d.action, 0) + 1
        parts = ", ".join(f"{v}× {k}" for k, v in sorted(actions.items()))
        return (
            f"[ENGINE] Run @ {self.run_at} | "
            f"evaluated={self.tickets_evaluated} | "
            f"queued={len(self.topics_queued)} new topics | "
            f"queue_size={self.queue_size} | actions=({parts})"
        )


# ── ImprovementEngine ──────────────────────────────────────────────────────────

class ImprovementEngine:
    """Transforms ImprovementTickets into a durable study queue.

    Usage (inside NightRunner._run_session):
        engine = ImprovementEngine()
        report = await SelfAnalyzer(capability_graph).analyze()
        result = engine.run_from_report(report)
        logger.info(result.summary())
        # Then drain with engine.dequeue_topic() in _select_topic

    Or as a standalone queue consumer:
        topic = engine.dequeue_topic()   # returns None if empty
    """

    def __init__(self):
        self._state = self._load_state()

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_from_report(
        self,
        report,                   # AnalysisReport from SelfAnalyzer
        max_inject: int = MAX_INJECT_PER_RUN,
    ) -> EngineResult:
        """Process report → decisions → persist queue. Fully synchronous."""
        decisions: List[EngineDecision] = []
        newly_queued: List[str] = []
        processed_ids: set = set(self._state.get("processed_ticket_ids", []))

        tickets = sorted(report.tickets, key=lambda t: (t.priority, t.topic))

        for ticket in tickets[:max_inject]:
            decision = self._decide(ticket, processed_ids)
            decisions.append(decision)

            if decision.action in ("inject", "decompose"):
                for topic in decision.topics:
                    if self._enqueue(topic):
                        newly_queued.append(topic)
                        logger.info(
                            "[ENGINE] Queued [P%d/%s]: %r",
                            ticket.priority, ticket.ticket_type, topic,
                        )
                processed_ids.add(ticket.id)
            else:
                logger.debug(
                    "[ENGINE] Skipped %r → %s: %s",
                    ticket.topic, decision.action, decision.reason,
                )

        self._state["processed_ticket_ids"] = list(processed_ids)
        self._state["last_run_at"] = datetime.now().isoformat()
        self._state["total_topics_ever_queued"] = (
            self._state.get("total_topics_ever_queued", 0) + len(newly_queued)
        )
        self._save_state()

        result = EngineResult(
            run_at=self._state["last_run_at"],
            tickets_evaluated=len(decisions),
            decisions=decisions,
            topics_queued=newly_queued,
            queue_size=len(self._state["pending_queue"]),
        )
        logger.info(result.summary())
        return result

    def dequeue_topic(self) -> Optional[str]:
        """Pop the highest-priority topic from the queue. Returns None if empty."""
        queue = self._state.get("pending_queue", [])
        if not queue:
            return None
        topic = queue.pop(0)
        self._save_state()
        logger.info("[ENGINE] Dequeued topic: %r (%d remaining)", topic, len(queue))
        return topic

    def peek_queue(self) -> List[str]:
        """Non-destructive view of pending topics."""
        return list(self._state.get("pending_queue", []))

    def get_status(self) -> dict:
        """Snapshot for health endpoints."""
        return {
            "pending_queue":        self.peek_queue(),
            "queue_size":           len(self.peek_queue()),
            "last_run_at":          self._state.get("last_run_at"),
            "total_ever_queued":    self._state.get("total_topics_ever_queued", 0),
            "processed_ticket_count": len(self._state.get("processed_ticket_ids", [])),
        }

    # ── Decision logic ─────────────────────────────────────────────────────────

    def _decide(self, ticket, processed_ids: set) -> EngineDecision:
        # Already processed in a previous run
        if ticket.id in processed_ids:
            return EngineDecision(
                ticket_id=ticket.id,
                ticket_type=ticket.ticket_type,
                action="skip_processed",
                topics=[],
                reason="Already acted on in a previous engine run.",
            )

        # Contamination filter
        if self._is_garbage(ticket.topic):
            return EngineDecision(
                ticket_id=ticket.id,
                ticket_type=ticket.ticket_type,
                action="skip_garbage",
                topics=[],
                reason=f"Topic contains contamination tokens: {ticket.topic!r}",
            )

        # Chronic failure with very low score → decompose compound topic
        if (
            ticket.ticket_type == "retry_chronic_failure"
            and ticket.metadata.get("avg_score", 10) < DECOMPOSE_THRESHOLD
        ):
            parts = self._decompose(ticket.topic)
            if len(parts) > 1:
                return EngineDecision(
                    ticket_id=ticket.id,
                    ticket_type=ticket.ticket_type,
                    action="decompose",
                    topics=parts,
                    reason=(
                        f"Avg score {ticket.metadata['avg_score']}/10 < {DECOMPOSE_THRESHOLD} "
                        f"— topic too complex, split into {len(parts)} atomic sub-topics."
                    ),
                )

        # Default: inject directly
        topic = self._canonical_topic(ticket)
        if not topic or len(topic.split()) < MIN_TOPIC_WORDS:
            return EngineDecision(
                ticket_id=ticket.id,
                ticket_type=ticket.ticket_type,
                action="skip_garbage",
                topics=[],
                reason=f"Topic too short after canonicalisation: {ticket.topic!r}",
            )

        return EngineDecision(
            ticket_id=ticket.id,
            ticket_type=ticket.ticket_type,
            action="inject",
            topics=[topic],
            reason=ticket.reason,
        )

    def _canonical_topic(self, ticket) -> str:
        """Return the best study topic string for a ticket."""
        # For capability gaps, the metadata has the explicit study topic
        if ticket.ticket_type == "fill_capability_gap":
            return ticket.metadata.get("study_topic", ticket.topic)
        return ticket.topic

    def _decompose(self, topic: str) -> List[str]:
        """Split compound 'X applied to Y applied to Z' → ['X', 'Y', 'Z'].

        Filters out parts that are too short or contaminated.
        Falls back to returning the original topic in a list if splitting fails.
        """
        parts = [p.strip() for p in topic.split(" applied to ") if p.strip()]

        if len(parts) <= 1:
            # Try splitting on " and " as secondary compound separator
            parts = [p.strip() for p in topic.split(" and ") if p.strip()]

        valid = [
            p for p in parts
            if len(p.split()) >= MIN_TOPIC_WORDS and not self._is_garbage(p)
        ]

        return valid if len(valid) > 1 else [topic]

    def _is_garbage(self, topic: str) -> bool:
        if topic.strip().startswith("#"):
            return True   # markdown header — mai un topic valido
        t = topic.lower()
        return any(token in t for token in _GARBAGE_TOKENS)

    # ── Queue management ───────────────────────────────────────────────────────

    def _enqueue(self, topic: str) -> bool:
        """Add topic to queue if not duplicate and queue not full. Returns True if added."""
        queue: List[str] = self._state.setdefault("pending_queue", [])
        if topic in queue:
            return False
        if len(queue) >= MAX_QUEUE_SIZE:
            logger.warning("[ENGINE] Queue full (%d/%d) — dropping: %r", len(queue), MAX_QUEUE_SIZE, topic)
            return False
        queue.append(topic)
        return True

    def enqueue_topics(self, topics: List[str]) -> int:
        """Public API — queue study topics derived from external sources (e.g. benchmark failures).

        Returns the number of topics actually added (duplicates and full-queue are skipped).
        """
        added = 0
        for topic in topics:
            if self._enqueue(topic):
                self._state["total_topics_ever_queued"] = self._state.get("total_topics_ever_queued", 0) + 1
                logger.info("[ENGINE] Benchmark-derived topic queued: %r", topic)
                added += 1
        if added:
            self._save_state()
        return added

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            if _QUEUE_FILE.exists():
                return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[ENGINE] Could not load queue state: %s", exc)
        return {
            "pending_queue":          [],
            "processed_ticket_ids":   [],
            "total_topics_ever_queued": 0,
            "last_run_at":            None,
        }

    def _save_state(self):
        try:
            _QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=_QUEUE_FILE.parent, suffix=".tmp", delete=False,
            ) as tf:
                json.dump(self._state, tf, indent=2, ensure_ascii=False)
                tmp = tf.name
            os.replace(tmp, _QUEUE_FILE)
        except Exception as exc:
            logger.error("[ENGINE] Could not save queue state: %s", exc)

    # ── Shared environment interface ───────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to CognitionCore environment events.

        ImprovementEngine manages the study queue — it removes resolved topics
        when skills are certified and re-prioritizes on frustration peaks.
        """
        if event_type == "skill_certified":
            # Topic was certified — remove it from pending queue if present
            topic = data.get("topic", "")
            if topic:
                queue: list = self._state.get("pending_queue", [])
                before = len(queue)
                self._state["pending_queue"] = [
                    t for t in queue
                    if t.lower() != topic.lower()
                ]
                if len(self._state["pending_queue"]) < before:
                    self._save_state()
                    logger.info("[ENGINE] Removed certified topic from queue: %r", topic)

        elif event_type == "frustration_peak":
            # Topic is chronically failing — decompose and re-enqueue subtopics
            topic = data.get("topic", "")
            if topic:
                subtopics = self._decompose(topic)
                added = 0
                for sub in subtopics:
                    if sub != topic and self._enqueue(sub):
                        added += 1
                if added:
                    self._save_state()
                    logger.info(
                        "[ENGINE] Frustration peak on '%s' — enqueued %d decomposed subtopics",
                        topic, added,
                    )
