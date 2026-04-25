"""
SHARD Night Runner
Standalone orchestrator for autonomous night study sessions.
"""
import os
import sys
import time
import json
import shutil
import random
import asyncio
import logging
import argparse
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

try:
    from voice_broadcaster import broadcast as _vb
except ImportError:
    def _vb(text, priority="low", event_type="info"):
        pass  # graceful no-op if broadcaster not available

# Add both project root and backend/ to sys.path (mirrors server.py behaviour)
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
BACKEND_DIR  = str(Path(__file__).resolve().parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend.study_agent import StudyAgent
from backend.research_agenda import ResearchAgenda
from backend.experiment_inventor import ExperimentInventor
from backend.capability_graph import CapabilityGraph
from backend.experiment_cache import SemanticExperimentCache
from backend.strategy_memory import StrategyMemory
from backend.memory import ShardMemory
from backend.experiment_replay import ExperimentReplay
from backend.goal_storage import GoalStorage
from backend.goal_engine import GoalEngine
from backend.study_personas import select_persona, record_outcome

# --- COSTANTI DI DEFAULT ---
MAX_CYCLES_DEFAULT = 5
MAX_RUNTIME_MINUTES_DEFAULT = 120

# Import budget defaults from constants (single source of truth)
try:
    from constants import DEFAULT_SESSION_API_LIMIT, DEFAULT_TOPIC_BUDGET
except ImportError:
    from backend.constants import DEFAULT_SESSION_API_LIMIT, DEFAULT_TOPIC_BUDGET

MAX_API_CALLS_DEFAULT = DEFAULT_SESSION_API_LIMIT
PAUSE_BETWEEN_CYCLES_MINUTES_DEFAULT = 1

# ── TASK 3: Topic Quality Filtering ───────────────────────────────────────────
BAD_TOKENS = {
    "chiedo", "facendo", "present", "fully",
    # Italian phrase fragments that get certified as skills
    "potrei", "quante", "completa", "scrivi", "esegui", "testa",
    # Grammar terms that have nothing to do with programming
    "interrogative", "transitive", "usage",
}

# Topics containing these are off-topic for a coding AI
OFF_TOPIC_KEYWORDS = [
    "quantized inertia", "galaxy rotation", "dark matter", "casimir effect",
    "modified newtonian", "hubble-scale", "modified gravity",
    "mond ", "qi theory",
    # Hallucination spirals: nested "integration of integration of..."
    "integration of integration",
]

# Max nesting depth for "Integration of X and Y" topics
_MAX_INTEGRATION_DEPTH = 2


def topic_quality(topic: str) -> bool:
    """Check if topic has sufficient quality and semantic meaning.

    Returns False for:
    - Too short (< 2 words)
    - Contains bad tokens (phrase fragments, grammar terms)
    - Off-topic for a coding AI (physics pseudoscience, etc.)
    - Hallucination spiral (nested integration of integration of...)
    - Starts with 'impossible'
    """
    t_lower = topic.lower().strip()
    words = t_lower.split()

    if len(words) < 2:
        return False

    # Bad token check
    for w in words:
        if w in BAD_TOKENS:
            return False

    # Off-topic keyword check
    if any(kw in t_lower for kw in OFF_TOPIC_KEYWORDS):
        return False

    # Reject topics literally named "impossible ..."
    if t_lower.startswith("impossible"):
        return False

    # Nesting depth guard: count how many times "integration of" appears
    depth = t_lower.count("integration of")
    if depth >= _MAX_INTEGRATION_DEPTH:
        return False

    return True

# ── TASK 5: Capability Recombination Engine ──────────────────────────────────
def generate_recombined_topic(capabilities):
    """Generate a research topic by combining two learned capabilities."""
    if len(capabilities) < 2:
        return None
    
    a, b = random.sample(capabilities, 2)
    
    return f"Integration of {a} and {b}"

# ── TASK 2: Curiosity-Driven Topic Generator ──────────────────────────────────
def capability_frontier(capabilities):
    """
    Identify less-connected capabilities as exploration frontier.
    Returns capabilities with 2+ words (multi-word phrases are frontier).
    """
    frontier = []
    for cap in capabilities:
        words = cap.lower().split()
        if len(words) >= 2:
            frontier.append(cap)
    return frontier

def generate_curiosity_topic(capabilities):
    """
    Generate a novel topic from frontier capabilities using curiosity.
    Explores combinations of multi-word concepts not yet integrated.
    """
    frontier = capability_frontier(capabilities)
    
    if len(frontier) < 2:
        return None
    
    a, b = random.sample(frontier, 2)
    topic = f"Integration of {a} and {b}"
    return topic

def is_valid_topic(topic: str, logger: logging.Logger) -> bool:
    import re as _re
    t = topic.lower()

    # Reject markdown headers (e.g. "# Task 03 -- Optimize the Transaction Processor")
    if topic.strip().startswith("#"):
        logger.info(f"[TOPIC FILTER] Discarded markdown header topic: {topic}")
        return False

    # Reject [missed_emergence] prefixed topics (CognitionCore internal label leaking into pool)
    if t.startswith("[missed_emergence]") or t.startswith("[missed emergence]"):
        logger.info(f"[TOPIC FILTER] Discarded missed_emergence topic: {topic}")
        return False

    # Reject "Task XX" style strings (benchmark leftovers from improvement_engine)
    if _re.search(r"\btask\s*\d+\b", t):
        logger.info(f"[TOPIC FILTER] Discarded task-description topic: {topic}")
        return False

    # Reject imperative task descriptions: "Fix the X", "Refactor the X", etc.
    _task_verbs = {"fix", "refactor", "rewrite", "update", "implement", "create",
                   "build", "add", "remove", "delete", "clean", "migrate", "optimize"}
    _first_word = t.split()[0] if t.split() else ""
    if _first_word in _task_verbs and " the " in t:
        logger.info(f"[TOPIC FILTER] Discarded imperative task topic: {topic}")
        return False

    ITALIAN_THOUGHT_PATTERNS = [
        "potrei", "vorrei", "penso", "chiedo",
        "facendo", "forse", "dovrei", "momento",
        "riflessione", "sistema", "stabile",
        "energia", "lealtà", "analizzare"
    ]

    # Hard reject: any topic containing these patterns is junk regardless of length
    HARD_REJECT_PATTERNS = [
        "chiedo", "potrei", "vorrei", "facendo", "analizzare",
        "post-quantum security margin", "hubble-scale casimir",
        "quantized inertia",
    ]
    if any(p in t for p in HARD_REJECT_PATTERNS):
        logger.info(f"[TOPIC FILTER] Hard-rejected junk topic: '{topic}'")
        return False
    
    whitelist = [
        "algorithm", "data structure", "python", "recursion", "sorting", "search", "graph", "tree",
        "dynamic programming", "optimization", "parsing", "filesystem", "network", "concurrency",
        "regex", "database", "compiler", "interpreter", "machine learning", "neural network",
        "api", "websocket", "docker", "encryption", "hashing", "multithreading", "async",
        "binary", "perceptron", "pathfinding", "web scraping", "oop", "design pattern",
        "testing", "deployment", "authentication", "caching", "queue", "stack", "linked list"
    ]
    
    words = t.split()

    # Reject nested composite topics (capability inflation artifact)
    if t.count('integration of') >= 2 or t.count(' applied to ') >= 2:
        logger.info(f"[TOPIC FILTER] Rejected nested composite topic: '{topic}'")
        return False

    if any(p in t for p in ITALIAN_THOUGHT_PATTERNS) and len(words) < 3:
        logger.info(f"[TOPIC FILTER] Rifiutato topic simile a pensiero: '{topic}' (pattern italiano + <3 parole)")
        return False
        
    if len(words) < 3 and not any(kw in t for kw in whitelist):
        logger.info(f"[TOPIC FILTER] Discarded invalid topic: '{topic}' (less than 3 words and no technical keywords)")
        return False

    if any(kw in t for kw in whitelist):
        return True
        
    blacklist = [
        "ho imparato", "mi chiedo", "dovrei", "il boss", "quante", "quanto", "riflessione", "pensiero", "sistema stabile", "momento per"
    ]
    if any(kw in t for kw in blacklist):
        logger.info(f"[TOPIC FILTER] Discarded invalid topic: {topic} -- Reason: matched blacklist pattern")
        return False
        
    avg_len = sum(len(w) for w in words) / len(words)
    if avg_len < 3:
        logger.info(f"[TOPIC FILTER] Discarded invalid topic: {topic} -- Reason: average word length < 3")
        return False
        
    logger.info(f"[TOPIC FILTER] Accepting unrecognized topic (no keyword match, no blacklist hit): {topic}")
    return True

def is_trivial_topic(topic: str, logger: logging.Logger) -> bool:
    t = topic.lower()
    trivial_patterns = [
        "hello world", "reverse string", "print number", "simple loop",
        "basic variable", "fizzbuzz", "print hello", "counter example",
        "what is a", "cos'è un", "cos'è una", "cosa sono"
    ]
    if any(p in t for p in trivial_patterns):
        logger.info(f"[TOPIC FILTER] Discarded trivial topic: {topic}")
        return True
        
    if len(t.split()) == 1:
        logger.info(f"[TOPIC FILTER] Discarded trivial topic: {topic} (Single word)")
        return True
        
    if t.startswith("what is ") or t.startswith("cos'è "):
        logger.info(f"[TOPIC FILTER] Discarded trivial topic: {topic}")
        return True
        
    return False

class SessionState(Enum):
    INIT     = auto()  # session setup: memory, agents, SSJ3 analysis
    SELECT   = auto()  # picking next topic
    STUDY    = auto()  # study_agent.study_topic() running
    REFACTOR = auto()  # enqueue_from_failure() after a failed cycle
    RECORD   = auto()  # writing experiment to SQLite + updating cycle_data
    COMPLETE = auto()  # cycle certified -- moving to next cycle
    FAILED   = auto()  # cycle not certified -- moving to next cycle
    DONE     = auto()  # session finished (limit reached or all cycles done)


_TACTICAL_INDICATORS = (
    "basics", "patterns", "handling", "logging", "unit test",
    "decorators", "exception", "asyncio", "coroutines", "generators",
    "hashing", "sorting", "search", "parser", "template",
    "iterator", "comprehension", "f-string", "typing", "dataclass",
)


def _classify_topic(topic: str) -> str:
    """Heuristic: tactical = closed implementation task; strategic = open design/analysis."""
    t = topic.lower()
    if any(ind in t for ind in _TACTICAL_INDICATORS):
        return "tactical"
    return "strategic"


class NightRunner:
    def __init__(self, cycles: int, timeout: int, pause: int, api_limit: int, topic_budget: int = DEFAULT_TOPIC_BUDGET, forced_topic: str = "", research_mode: bool = False, no_l3: bool = False, use_affective_layer: bool = True):
        self.max_cycles = cycles
        self.max_runtime_minutes = timeout
        self.goal_engine = None
        self.pause_minutes = pause
        self.max_api_calls = api_limit
        self.topic_budget = topic_budget
        self._forced_topic: str = forced_topic.strip()
        self._research_mode: bool = research_mode
        self._no_l3: bool = no_l3
        self._use_affective_layer: bool = use_affective_layer

        self.start_time = None
        self.api_calls_used = 0
        self.session_data = []
        self.benchmark_results = []
        self.seed = random.randint(0, 10_000_000)
        random.seed(self.seed)
        # Priority -1: topics queued by ImprovementEngine (SSJ3 proactive self-improvement)
        self._background_mode: bool = False  # True when running alongside an audio session
        self._improvement_topics: list = []
        self._knowledge_contradiction_detector = None
        self._state: SessionState = SessionState.INIT

        self.topic_filter_discards = 0
        self._desire_selections_this_session = 0  # cap: max 1 desire topic per session

        # Agenda starvation fix (#29)
        from collections import deque
        self._recent_topics: deque = deque(maxlen=10)   # cooldown window
        self._fallback_count: int  = 0                  # how many times fallback fired this session
        self._last_topic: str      = ""                 # to block consecutive fallback

        self._setup_directories()
        self._setup_logging()
        
        self.logger.info(f"Random seed: {self.seed}")
        
    def _setup_directories(self):
        self.logs_dir = Path("logs")
        self.reports_dir = Path("night_reports")
        self.logs_dir.mkdir(exist_ok=True)
        self.reports_dir.mkdir(exist_ok=True)
        
    def _setup_logging(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.log_file = self.logs_dir / f"night_session_{date_str}.log"
        log_file = self.log_file

        self.logger = logging.getLogger("NIGHT_RUNNER")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(logging.Formatter('[NIGHT RUNNER] [%(asctime)s] %(message)s', datefmt='%H:%M'))
        
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('[NIGHT RUNNER] [%(asctime)s] %(message)s', datefmt='%H:%M'))
        
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

        # Wire all shard.* loggers (memory_extractor, meta_learning, study, …)
        # to the same file so [MEMORY_FAIL] / [FAIL-REUSE] appear in the log.
        shard_logger = logging.getLogger("shard")
        shard_logger.setLevel(logging.INFO)
        shard_fh = logging.FileHandler(log_file, encoding='utf-8')
        shard_fh.setFormatter(logging.Formatter(
            '[%(name)s] [%(asctime)s] %(message)s', datefmt='%H:%M'
        ))
        # Avoid duplicate handlers on repeated NightRunner instantiation
        if not any(isinstance(h, logging.FileHandler) and
                   getattr(h, 'baseFilename', None) == str(log_file)
                   for h in shard_logger.handlers):
            shard_logger.addHandler(shard_fh)

    def _query_knowledge_conflicts(self, topic: str) -> list[dict]:
        """Fetch structured GraphRAG conflict rows for the operational detector."""
        try:
            from shard_db import query as _db_query
            return _db_query(
                """
                SELECT source_concept, target_concept, relation_type, context, confidence
                FROM knowledge_graph
                WHERE relation_type='causes_conflict' AND confidence >= 0.6
                ORDER BY confidence DESC
                LIMIT 50
                """
            )
        except Exception as _kg_err:
            self.logger.debug("[KCD] graph query non-fatal: %s", _kg_err)
            return []

    def _get_knowledge_contradiction_detector(self):
        """Lazy-build the operational contradiction detector for the current runner."""
        if self._knowledge_contradiction_detector is not None:
            return self._knowledge_contradiction_detector
        try:
            from shard_db import query as _db_query
            from backend.knowledge_contradiction_detector import KnowledgeContradictionDetector
            self._knowledge_contradiction_detector = KnowledgeContradictionDetector(
                db_query_fn=_db_query,
                graphrag_query_fn=self._query_knowledge_conflicts,
                logger=self.logger,
            )
        except Exception as _kcd_err:
            self.logger.warning("[KCD] Init non-fatal: %s", _kcd_err)
            self._knowledge_contradiction_detector = None
        return self._knowledge_contradiction_detector

    def _defer_topic_for_future_cycle(self, topic: str) -> None:
        """Re-queue a deferred topic without losing it."""
        if not topic:
            return
        try:
            from backend.improvement_engine import ImprovementEngine as _IE_defer
            _ie_defer = _IE_defer()
            _ie_defer.enqueue_topics([topic])
            try:
                self._improvement_topics = list(_ie_defer.peek_queue())
            except Exception:
                if topic not in self._improvement_topics:
                    self._improvement_topics.append(topic)
            self.logger.info("[KCD] Deferred topic re-queued: '%s'", topic)
        except Exception as _defer_err:
            self.logger.debug("[KCD] defer non-fatal: %s", _defer_err)
            if topic not in self._improvement_topics:
                self._improvement_topics.append(topic)

    def _apply_knowledge_contradiction_analysis(
        self,
        analysis: dict | None,
        topic: str,
        source: str,
        reason: str,
        predicted_score: float | None,
    ) -> tuple[str, str, str, float | None]:
        """Apply detector output to the live cycle state.

        MVP behavior:
        - warn: log only
        - lower_confidence: replace predicted score using detector metadata
        - force_prerequisite: switch to prerequisite and defer the original topic
        - skip_topic: reserved for future rules, not emitted by current MVP
        """
        if not analysis or not analysis.get("recommended_action"):
            return topic, source, reason, predicted_score

        _action = analysis.get("recommended_action")
        _metadata = dict(analysis.get("metadata") or {})
        _warning_block = analysis.get("warning_block", "")
        if _warning_block:
            self.logger.warning("%s", _warning_block)

        if _action == "lower_confidence" and predicted_score is not None:
            _adjusted = _metadata.get("adjusted_predicted_score")
            if isinstance(_adjusted, (int, float)):
                self.logger.info(
                    "[KCD] Lowering predicted score for '%s': %.1f -> %.1f",
                    topic, predicted_score, _adjusted,
                )
                predicted_score = float(_adjusted)
            return topic, source, reason, predicted_score

        if _action == "force_prerequisite":
            _prereq = str(_metadata.get("prerequisite_topic") or "").strip()
            if not _prereq:
                self.logger.warning(
                    "[KCD] force_prerequisite without prerequisite_topic for '%s' -- degrading to warn",
                    topic,
                )
                return topic, source, reason, predicted_score

            _deferred = str(_metadata.get("deferred_topic") or topic).strip()
            if _deferred:
                self._defer_topic_for_future_cycle(_deferred)
            _defer_reason = str(_metadata.get("defer_reason") or f"pending prerequisite: {_prereq}")
            self.logger.info(
                "[KCD] Redirecting '%s' -> prerequisite '%s' and deferring original topic",
                topic, _prereq,
            )
            return _prereq, "prerequisite", _defer_reason, predicted_score

        return topic, source, reason, predicted_score

    def _transition(self, new_state: SessionState, detail: str = "") -> None:
        """Log a state transition and update _state."""
        old = self._state.name
        self._state = new_state
        msg = f"[STATE] {old} -> {new_state.name}"
        if detail:
            msg += f"  ({detail})"
        self.logger.info(msg)

    def _check_limits(self, current_cycle: int) -> str:
        if current_cycle > self.max_cycles:
            return "max cycles reached"
            
        runtime_minutes = (time.time() - self.start_time) / 60
        if runtime_minutes >= self.max_runtime_minutes:
            return f"timeout ({self.max_runtime_minutes} min)"
            
        if self.api_calls_used >= self.max_api_calls:
            return f"API call limit reached ({self.api_calls_used}/{self.max_api_calls})"
            
        return ""

    def _is_quarantined(self, topic: str) -> bool:
        """True if topic is permanently blocked from further study.

        Two conditions (checked in order, cheapest first):
          1. Hard cap: >= MAX_TOPIC_ATTEMPTS total attempts (any score)
          2. Hard fails: 3+ attempts with max score < 6.0 (SQLite VIEW)

        Near-misses (score >= 6.0) are NOT quarantined by condition 2 --
        they should be retried with score context (Fix B).
        """
        from shard_db import get_db
        try:
            from constants import MAX_TOPIC_ATTEMPTS
        except ImportError:
            from backend.constants import MAX_TOPIC_ATTEMPTS

        topic_key = topic.lower().strip()

        # Gate 1: hard cap on total attempts (cheap COUNT, no LLM)
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM experiments WHERE LOWER(topic) = ?",
                (topic_key,)
            ).fetchone()
            count = int(row["n"]) if row else 0
            if count >= MAX_TOPIC_ATTEMPTS:
                print(f"[QUARANTINE] {topic} blocked after {count} attempts (hard cap)")
                self.logger.warning(
                    "[QUARANTINE] %r hard-capped after %d attempts (>= %d)",
                    topic, count, MAX_TOPIC_ATTEMPTS,
                )
                # Persist to quarantine.json so ReportAgent can audit it
                try:
                    _qpath = Path(__file__).resolve().parents[1] / "shard_memory" / "quarantine.json"
                    import json as _json
                    _existing = set(_json.loads(_qpath.read_text(encoding="utf-8"))) if _qpath.exists() else set()
                    if topic_key not in _existing:
                        _existing.add(topic_key)
                        _qpath.write_text(_json.dumps(sorted(_existing), indent=2), encoding="utf-8")
                except Exception as _qe:
                    self.logger.debug("[QUARANTINE] quarantine.json write failed: %s", _qe)
                return True
        except Exception as _e:
            self.logger.debug("[QUARANTINE] attempt-cap check failed: %s", _e)

        # Gate 2: 3+ hard fails (score < 6.0) via SQLite VIEW
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT topic FROM quarantined_topics WHERE topic = ?",
                (topic_key,)
            ).fetchone()
            if row:
                self.logger.info("[DB] Topic quarantined (SQLite VIEW): %r", topic)
            return row is not None
        except Exception:
            return False

    def _weighted_cert_report_lines(self) -> list:
        """Return markdown lines for simple vs weighted cert_rate for the night report."""
        try:
            from backend.cognition.cognition_core import get_cognition_core
            _core = get_cognition_core()
            _sm = getattr(_core, "_self_model", None)
            if _sm is None or not hasattr(_sm, "get_weighted_certification_rate"):
                return []
            simple   = _sm.get_certification_rate()
            weighted = _sm.get_weighted_certification_rate()
            gap = simple - weighted
            lines = [
                f"- Certification rate (simple):   {simple:.1%}",
                f"- Certification rate (weighted): {weighted:.1%}",
            ]
            if gap > 0.05:
                lines.append(
                    f"- **WARNING: Reward hacking detected** — easy topics inflating metrics by {gap:.1%}"
                )
            return lines
        except Exception as _e:
            self.logger.debug("[REPORT] weighted cert rate failed: %s", _e)
            return []

    def _is_avoided(self, topic: str) -> bool:
        """True if topic matches an avoid_domain from VisionEngine (chronic failures)."""
        ve = getattr(self, "_vision_engine", None)
        if ve is None:
            return False
        topic_l = topic.lower().strip()
        return any(topic_l == a.lower().strip() or a.lower().strip() in topic_l for a in ve.avoid_domains)

    def _is_on_cooldown(self, topic: str) -> bool:
        """True if topic appeared in the last 10 selections (agenda starvation fix #29).
        Window raised from 5 → 10 to prevent recycling in small pools."""
        recent_10 = list(self._recent_topics)[-10:]
        return topic.lower().strip() in [t.lower().strip() for t in recent_10]

    def _prereq_is_stuck(self, topic: str, max_fails: int = 3) -> bool:
        """True if topic has >= max_fails uncertified attempts (#46 goal cooldown).

        Prevents redirect loops where a near-miss prerequisite (score 6.0–7.4)
        never certifies but keeps being injected as a gate for harder topics.
        Distinct from quarantine (which only fires for hard fails < 6.0).
        """
        try:
            from shard_db import query_one as _qone
            row = _qone(
                "SELECT COUNT(*) AS n FROM experiments WHERE LOWER(topic)=LOWER(?) AND certified=0",
                (topic.strip(),),
            )
            stuck = bool(row and row["n"] >= max_fails)
            if stuck:
                self.logger.info(
                    "[PREREQ] '%s' is stuck (%d uncertified attempts) -- skipping as prerequisite",
                    topic, row["n"],
                )
            return stuck
        except Exception:
            return False

    def _is_certified_recently(self, topic: str, hours: int = 24) -> bool:
        """True if topic was certified within the last `hours` hours.

        Provides a global horizontal filter independent of which agenda path
        selected the topic — prevents re-studying freshly-certified material.
        """
        try:
            from shard_db import query as _q
            rows = _q(
                """SELECT 1 FROM experiments
                   WHERE LOWER(topic) = LOWER(?)
                   AND certified = 1
                   AND timestamp > datetime('now', ?)
                   LIMIT 1""",
                (topic.strip(), f"-{hours} hours"),
            )
            return bool(rows)
        except Exception:
            return False

    def _record_topic(self, topic: str, source: str) -> None:
        """Track selected topic for cooldown and fallback ratio (#29)."""
        self._recent_topics.append(topic)
        self._last_topic = topic
        if source == "fallback":
            self._fallback_count += 1

    def _fallback_ratio(self) -> float:
        total = len(self._recent_topics)
        if total == 0:
            return 0.0
        fallbacks = sum(1 for t in self._recent_topics if t == "python fundamentals review")
        return fallbacks / total

    async def _select_topic(self, capability_graph, config_context) -> tuple[str, str, str]:
        """Returns (topic, source, reason)"""

        # Priority 0: --force-topic CLI override (bypasses all selection logic)
        if self._forced_topic:
            self.logger.info(f"[FORCE-TOPIC] Overriding selection with: '{self._forced_topic}'")
            return self._forced_topic, "forced", "--force-topic CLI override"

        # Priority -1: ImprovementEngine queue (SSJ3 proactive self-improvement)
        # Fix A: validate every improvement topic -- SSJ3 can re-inject garbage topics
        while self._improvement_topics:
            topic = self._improvement_topics.pop(0)
            try:
                from backend.improvement_engine import ImprovementEngine
                ImprovementEngine().dequeue_topic()
            except Exception:
                pass
            if not is_valid_topic(topic, self.logger) or is_trivial_topic(topic, self.logger):
                self.logger.warning("[SSJ3] Skipping invalid improvement topic: %r", topic)
                continue
            if self._is_quarantined(topic):
                self.logger.warning("[QUARANTINE] Improvement topic is quarantined (3+ hard fails): %r", topic)
                continue
            if self._is_avoided(topic):
                self.logger.info("[VISION] Improvement topic in avoid_domains -- skipping: %r", topic)
                continue
            self.logger.info("[SSJ3] Improvement topic dequeued: %r", topic)
            return topic, "improvement_engine", "Proactive improvement ticket (SSJ3)"

        # Priority 0: Phoenix Protocol -- replays near-miss topics (score 6.0–7.4).
        # Base probability 25%, boosted to 50% when the DB has known near-miss topics
        # (score 7.0–7.4, just under the 7.5 certification threshold).
        try:
            from shard_db import get_db as _phx_db
            _phx_near = _phx_db().execute(
                "SELECT COUNT(*) FROM experiments WHERE certified=0 AND score >= 7.0 AND score < 7.5"
            ).fetchone()[0]
        except Exception:
            _phx_near = 0
        _phoenix_prob = 0.50 if _phx_near > 0 else 0.25
        if random.random() < _phoenix_prob:
            self.logger.info("[PHOENIX] Attempting failure replay lookup... (prob=%.0f%%, near_miss_topics=%d)",
                             _phoenix_prob * 100, _phx_near)
            replay_engine = ExperimentReplay()
            if hasattr(replay_engine, "failed_experiments"):
                failures = replay_engine.failed_experiments()
            else:
                failures = []
            candidates = [
                e for e in failures
                if 6.0 <= e.get('score', 0) <= 7.4
            ]
            if candidates:
                topic_data = random.choice(candidates)
                topic = topic_data.get("topic")
                past_score = topic_data.get("score")
                if self._is_quarantined(topic) or self._is_avoided(topic):
                    self.logger.info(f"[PHOENIX] Candidate '{topic}' is quarantined/avoided -- skipping.")
                else:
                    self.logger.info(f"[PHOENIX] Replay candidate found: '{topic}' (previous score: {past_score})")
                    return topic, "failure_replay", f"Phoenix replay: score precedente {past_score}|prev_score={past_score}"
            else:
                 self.logger.info("[PHOENIX] No valid candidates found. Falling back to normal selection.")

        # Priority 0.5: Desire engine -- high-frustration or high-curiosity topics
        # Cap: max 1 desire-driven topic per session to avoid thrashing between
        # frustrated topics instead of advancing the active goal.
        try:
            from backend.desire_engine import get_desire_engine as _get_de
            _de = _get_de()
            _desire_candidates = _de.top_desire_topics(top_n=3) if self._desire_selections_this_session == 0 else []
            for _dc in _desire_candidates:
                _dt = _dc["topic"]
                if not is_valid_topic(_dt, self.logger) or is_trivial_topic(_dt, self.logger):
                    continue
                if self._is_quarantined(_dt) or self._is_avoided(_dt):
                    continue
                # Curiosity pull: pick adjacent topic 30% of the time
                if _dc["curiosity_pull"] > 0.2 and random.random() < 0.30:
                    self.logger.info(
                        "[DESIRE] Curiosity pull: '%s' (pull=%.2f)", _dt, _dc["curiosity_pull"]
                    )
                    self._desire_selections_this_session += 1
                    return _dt, "curiosity_driven", f"Lateral curiosity -- adjacent to recent cert (pull={_dc['curiosity_pull']:.2f})"
                # Frustration drive: pick frustrated topic 40% of the time
                if _dc["frustration_hits"] >= 2 and random.random() < 0.40:
                    self.logger.info(
                        "[DESIRE] Frustration drive: '%s' (hits=%d score=%.2f)",
                        _dt, _dc["frustration_hits"], _dc["desire_score"],
                    )
                    self._desire_selections_this_session += 1
                    return _dt, "frustration_driven", f"Frustration drive -- {_dc['frustration_hits']} prior blocks (desire={_dc['desire_score']:.2f})"
        except Exception as _de_sel_err:
            self.logger.debug("[DESIRE] Topic selection non-fatal: %s", _de_sel_err)

        # Priority 0.5: Curriculum suggestion -- topics that extend certified skills
        try:
            from backend.skill_library import suggest_curriculum_topics as _suggest_curr
            # Use certified study-topic names from experiments (matches knowledge_graph
            # topic_origin), NOT capability_graph keys which are concept names.
            try:
                from shard_db import query as _cert_q
                _cert_set = {
                    r["topic"] for r in _cert_q(
                        "SELECT DISTINCT topic FROM experiments WHERE certified=1"
                    ) if r["topic"]
                }
            except Exception:
                _cert_set = set()
            _pool_file = Path(__file__).resolve().parents[1] / "shard_memory" / "curated_topics.txt"
            _pool = [l.strip() for l in _pool_file.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.startswith("#")] if _pool_file.exists() else []
            # Extend pool with knowledge_graph topic_origins (organic topics from past study)
            try:
                from shard_db import query as _kg_curr_q
                _kg_pool = [r["topic_origin"] for r in _kg_curr_q(
                    "SELECT DISTINCT topic_origin FROM knowledge_graph "
                    "WHERE topic_origin IS NOT NULL LIMIT 60"
                ) if r["topic_origin"]]
                _pool = list({*_pool, *_kg_pool})
            except Exception:
                pass
            _curr_suggestions = _suggest_curr(_cert_set, _pool, top_n=5)
            _curr_suggestions = [
                t for t in _curr_suggestions
                if not self._is_quarantined(t) and not self._is_avoided(t)
                and is_valid_topic(t, self.logger) and not is_trivial_topic(t, self.logger)
            ]
            if _curr_suggestions and random.random() < 0.40:  # 40% chance to follow curriculum
                _curr_topic = _curr_suggestions[0]
                self.logger.info("[CURRICULUM] Following skill graph: '%s'", _curr_topic)
                return _curr_topic, "curriculum", f"Curriculum: extends/improves a certified skill"
        except Exception as _curr_err:
            self.logger.debug("[CURRICULUM] non-fatal: %s", _curr_err)

        # Priority 1: Curated topics list (primary source -- replaces ExperimentInventor)
        _curated_file = Path(__file__).resolve().parents[1] / "shard_memory" / "curated_topics.txt"
        if _curated_file.exists():
            try:
                _lines = _curated_file.read_text(encoding="utf-8").splitlines()
                _curated = [l.strip() for l in _lines if l.strip() and not l.startswith("#")]
                # Filter out already-certified and quarantined topics
                _certified = set(capability_graph.capabilities.keys())
                _candidates = [
                    t for t in _curated
                    if t.lower() not in _certified
                    and not self._is_quarantined(t)
                    and not self._is_avoided(t)
                ]
                if _candidates:
                    # Goal steering: if active goal exists, prefer aligned topics
                    _goal_aligned = self.goal_engine.best_aligned_topic(_candidates)
                    if _goal_aligned:
                        topic = _goal_aligned
                        self.logger.info(
                            "[GOAL STEER] Topic steered by active goal: %r (score=%.2f)",
                            topic,
                            self.goal_engine.get_active_goal().alignment_score(topic)
                            if self.goal_engine.get_active_goal() else 0,
                        )
                    else:
                        topic = random.choice(_candidates)
                    if is_valid_topic(topic, self.logger) and not is_trivial_topic(topic, self.logger):
                        self.logger.info("[CURATED] Topic selected from curated list: %r", topic)
                        source_label = "curated_goal_steered" if _goal_aligned else "curated_list"
                        reason_label = (
                            f"Allineato al goal: {self.goal_engine.goal_summary()}"
                            if _goal_aligned else "Selezionato dalla lista curata."
                        )
                        return topic, source_label, reason_label
            except Exception as _cur_err:
                self.logger.warning("[CURATED] Could not read curated_topics.txt: %s", _cur_err)

        sources = ["research_agenda"]  # consciousness removed -- generates garbage from Italian thoughts; ExperimentInventor disabled

        # TASK 2: Try curiosity-driven frontier exploration (20% chance)
        if random.random() < 0.20:
            capabilities = capability_graph.list_capabilities() if hasattr(capability_graph, "list_capabilities") else list(capability_graph.capabilities.keys()) if hasattr(capability_graph, "capabilities") else []
            frontier_size = len(capability_frontier(capabilities))
            if frontier_size >= 2:
                curiosity_topic = generate_curiosity_topic(capabilities)
                if curiosity_topic and topic_quality(curiosity_topic):
                    self.logger.info(f"[CURIOSITY ENGINE] frontier size: {frontier_size}")
                    self.logger.info(f"[CURIOSITY ENGINE] Generated frontier topic: {curiosity_topic}")
                    return curiosity_topic, "curiosity_engine", "Frontier exploration from capability graph"
                else:
                    self.logger.info(f"[CURIOSITY ENGINE] Generated topic failed quality check, falling back to normal selection")
            else:
                self.logger.info(f"[CURIOSITY ENGINE] Insufficient frontier capabilities ({frontier_size} < 2)")
        
        # TASK 5: Capability recombination DISABLED -- generates nonsense composite topics
        if False and random.random() < 0.25:
            candidate = generate_recombined_topic(capability_graph.list_capabilities() if hasattr(capability_graph, "list_capabilities") else list(capability_graph.capabilities.keys()) if hasattr(capability_graph, "capabilities") else [])
            if candidate and topic_quality(candidate):
                self.logger.info(f"[CAPABILITY RECOMBINATION] Generated topic: {candidate}")
                return candidate, "capability_recombination", "Topic generated from learned capabilities"
            else:
                self.logger.info(f"[CAPABILITY RECOMBINATION] Generated topic failed quality check, falling back to normal selection")
        
        for attempt in range(6):
            source = random.choice(sources)
            topic = None
            reason = ""
            
            if source == "research_agenda":
                agenda = ResearchAgenda(capability_graph, goal_engine=self.goal_engine)
                task = agenda.choose_next_topic()
                if task and "topic" in task:
                    topic, reason = task["topic"], "Selezionato dall'agenda di ricerca."

            if not topic:
                continue

            is_valid = is_valid_topic(topic, self.logger)
            is_trivial = is_trivial_topic(topic, self.logger)
            is_quality = topic_quality(topic)  # TASK 3: Topic quality check

            if not is_valid or is_trivial or not is_quality:
                reasons = []
                if not is_valid:
                    reasons.append("invalid")
                if is_trivial:
                    reasons.append("trivial")
                if not is_quality:
                    reasons.append("low-quality")
                    self.logger.info(f"[TOPIC FILTER] Rejected low-quality topic: {topic}")
                self.logger.info(f"[TOPIC FILTER] Rejected topic '{topic}' from {source} (reason: {', '.join(reasons)})")
                self.topic_filter_discards += 1
                continue

            # Fix C: quarantine hopeless topics (3+ attempts, max score < 6.0)
            if self._is_quarantined(topic):
                self.logger.info(f"[QUARANTINE] Skipping '{topic}' -- 3+ hard failures, max score < 6.0")
                self.topic_filter_discards += 1
                continue
            if self._is_avoided(topic):
                self.logger.info(f"[VISION] Skipping '{topic}' -- in avoid_domains (chronic failure)")
                self.topic_filter_discards += 1
                continue

            # Global certified-recently filter — blocks freshly-certified topics
            # regardless of which agenda path selected them (horizontal guardrail).
            _in_caps = topic.lower().strip() in {
                c.lower() for c in getattr(capability_graph, "capabilities", {}).keys()
            }
            _cert_recent = self._is_certified_recently(topic, hours=24)
            self.logger.info(
                "[AGENDA] source_path=%s topic='%s' in_capabilities=%s certified_recently=%s",
                source, topic[:60], _in_caps, _cert_recent,
            )
            if _cert_recent:
                self.logger.info(
                    "[AGENDA] Skipping recently-certified topic '%s' (certified in last 24h)", topic[:60]
                )
                self.topic_filter_discards += 1
                continue

            return topic, source, reason
            
        self.logger.info("[TOPIC FILTER] 6 consecutive rejections. Yielding to ResearchAgenda.")
        agenda = ResearchAgenda(capability_graph)
        task = agenda.choose_next_topic()
        if task and "topic" in task:
            topic = task["topic"]
            if is_valid_topic(topic, self.logger) and not is_trivial_topic(topic, self.logger) and topic_quality(topic):
                return topic, "research_agenda", "Fallback (Research Agenda)"
            else:
                self.topic_filter_discards += 1
                 
        self.logger.info("[TOPIC FILTER] ResearchAgenda empty or rejected. Falling back to curated list.")
        _curated_file = Path(__file__).resolve().parents[1] / "shard_memory" / "curated_topics.txt"
        if _curated_file.exists():
            try:
                _lines = _curated_file.read_text(encoding="utf-8").splitlines()
                _curated = [l.strip() for l in _lines if l.strip() and not l.startswith("#")]
                _certified = set(capability_graph.capabilities.keys())
                _candidates = [t for t in _curated if t.lower() not in _certified and not self._is_on_cooldown(t)]
                if _candidates:
                    return random.choice(_candidates), "curated_list", "Fallback (curated list)"
                # Cooldown removed all candidates -- try without cooldown filter
                _candidates_no_cooldown = [t for t in _curated if t.lower() not in _certified]
                if _candidates_no_cooldown:
                    return random.choice(_candidates_no_cooldown), "curated_list", "Fallback (curated list, no cooldown)"
            except Exception:
                pass

        # ── Agenda starvation fix #29: dynamic pool ──────────────────────────
        # Two reliable SQLite sources that need no missing method:
        #   1. near-miss experiments (score 6.0-7.4, not certified) -- highest ROI
        #   2. knowledge_graph topic_origins not yet in capabilities -- organic topics
        try:
            from shard_db import query as _dyn_q
            # Source 1: near-miss topics SHARD almost certified
            _near = _dyn_q("""
                SELECT DISTINCT topic FROM experiments
                WHERE certified=0 AND score >= 6.0 AND score < 7.5
                AND LOWER(topic) NOT IN (SELECT LOWER(name) FROM capabilities)
                ORDER BY score DESC LIMIT 20
            """)
            # Source 2: knowledge_graph topic_origins not yet certified
            _origins = _dyn_q("""
                SELECT DISTINCT topic_origin AS topic FROM knowledge_graph
                WHERE topic_origin IS NOT NULL
                AND LOWER(topic_origin) NOT IN (SELECT LOWER(name) FROM capabilities)
                LIMIT 40
            """)
            _dyn_pool = []
            for _r in (_near + _origins):
                _t = _r["topic"]
                if (_t not in _dyn_pool
                        and is_valid_topic(_t, self.logger)
                        and not is_trivial_topic(_t, self.logger)
                        and topic_quality(_t)
                        and not self._is_on_cooldown(_t)
                        and not self._is_quarantined(_t)
                        and not self._is_avoided(_t)):
                    _dyn_pool.append(_t)
            if _dyn_pool:
                _dyn_topic = random.choice(_dyn_pool[:15])
                self.logger.info("[AGENDA #29] Dynamic pool: %r (%d candidates)", _dyn_topic, len(_dyn_pool))
                return _dyn_topic, "dynamic_pool", f"Dynamic pool ({len(_dyn_pool)} candidates)"
        except Exception as _gap_err:
            self.logger.debug("[AGENDA #29] Dynamic pool failed: %s", _gap_err)

        # ── Hard rule: block consecutive fallback (#29) ────────────────────────
        if self._last_topic == "python fundamentals review":
            self.logger.warning("[AGENDA #29] Consecutive fallback blocked -- forcing gap or skip")
            _forced_pool = ["algorithm complexity and performance optimization",
                            "graph traversal algorithms bfs dfs",
                            "dynamic programming",
                            "binary search implementation",
                            "sorting algorithms comparison"]
            _forced = next((t for t in _forced_pool if not self._is_on_cooldown(t)), _forced_pool[0])
            return _forced, "gap_fill", "Anti-consecutive-fallback"

        # ── Hard cap: fallback ≤ 20% of recent selections (#29) ───────────────
        if self._fallback_ratio() >= 0.20:
            self.logger.warning("[AGENDA #29] Fallback ratio %.0f%% >= 20%% -- forcing gap topic", self._fallback_ratio() * 100)
            _forced_pool = ["algorithm complexity and performance optimization",
                            "graph traversal algorithms bfs dfs",
                            "dynamic programming",
                            "binary search implementation",
                            "sorting algorithms comparison"]
            _forced = next((t for t in _forced_pool if not self._is_on_cooldown(t)), _forced_pool[0])
            return _forced, "gap_fill", "Fallback cap enforced"

        return "python fundamentals review", "fallback", "Hardcoded ultimate fallback"

    async def run(self):
        self.start_time = time.time()
        _vb(f"Sessione notturna avviata. Studio autonomo in corso per un massimo di {self.max_cycles} cicli.", priority="medium", event_type="session_start")

        # ── Dual-layer session lock ──────────────────────────────────────────
        # In-process:   asyncio.Semaphore(1) blocks if server holds the lock
        # Cross-process: file lock blocks if an audio session is live
        #
        # Background mode: if audio is active, NightRunner runs silently
        # alongside it instead of aborting -- voice events are suppressed and
        # an extra pause is added between cycles to yield CPU to audio.
        _semaphore_acquired = False
        try:
            from backend.shard_semaphore import (
                SHARD_SESSION_LOCK,
                is_file_locked, is_audio_active,
                acquire_file_lock, release_file_lock,
                get_lock_reason, SESSION_LOCK_FILE,
            )
            if is_file_locked():
                if is_audio_active():
                    self._background_mode = True
                    self.logger.info(
                        "[LOCK] Audio session active -- NightRunner starting in silent background mode."
                    )
                    # Do not acquire semaphore or overwrite audio lock file
                else:
                    self.logger.warning(
                        "[LOCK] Session locked by '%s' -- NightRunner will not start.",
                        get_lock_reason(),
                    )
                    return
            else:
                try:
                    await asyncio.wait_for(SHARD_SESSION_LOCK.acquire(), timeout=0.1)
                    _semaphore_acquired = True
                except asyncio.TimeoutError:
                    self.logger.warning("[LOCK] Semaphore locked in-process. Aborting.")
                    return
                acquire_file_lock("night_runner")
                self.logger.info("[SESSION LOCK] Acquired by NightRunner.")
                self.logger.info("Session started")
        except ImportError:
            self.logger.warning("[LOCK] shard_semaphore not available -- running without session lock.")

        try:
            await self._run_session()
        finally:
            if _semaphore_acquired:
                try:
                    from backend.shard_semaphore import SHARD_SESSION_LOCK, release_file_lock
                    SHARD_SESSION_LOCK.release()
                    release_file_lock()
                    self.logger.info("[SESSION LOCK] Released by NightRunner.")
                except Exception as exc:
                    self.logger.error("[LOCK] Failed to release lock: %s", exc)

    async def _run_session(self):
        """Core study loop -- called by run() inside the session lock guard."""
        # In background mode (audio session active) suppress all voice broadcasts
        # Always assign _vb as a local to avoid UnboundLocalError from Python scoping rules
        _module_vb = globals()["_vb"]
        _vb = (lambda text, priority="low", event_type="info": None) if self._background_mode else _module_vb  # noqa: F841
        self._transition(SessionState.INIT, "loading memory + capability graph")
        import uuid as _uuid
        _session_id = str(_uuid.uuid4())
        self._current_session_id = _session_id
        self._session_start_iso  = datetime.now().isoformat()
        self.logger.info("[SESSION] id=%s", _session_id)
        memory = ShardMemory()
        capability_graph = CapabilityGraph()

        # ── Environment Observer -- Layer 1/2: golden solution protection ─────
        _env_obs = None
        try:
            from backend.environment_observer import EnvironmentObserver
            _env_obs = EnvironmentObserver()
            _env_obs.snapshot()
            self.logger.info("[ENV OBS] Golden solutions snapshotted.")
        except Exception as _eo_err:
            self.logger.warning("[ENV OBS] Init failed (non-fatal): %s", _eo_err)
        # ── Strategy pivot tracker -- chronic block detection ─────────────────
        # Two independent triggers for strategy memory wipe (pure amnesia --
        # no dissonance injection, so we can measure autonomous agency):
        #
        #   A) Fail streak:  same topic fails _PIVOT_THRESHOLD times in a row
        #   B) Near-miss loop: 3+ attempts all below cert threshold with
        #      score std < _VARIANCE_THRESHOLD (stuck at a "crystal ceiling")
        #
        # When either fires: pivot_on_chronic_block() wipes strategy memory.
        # No prompt injection -- blank slate only. (SSJ17 experiment design)
        _consecutive_fails: dict = {}   # topic -> int
        _recent_scores:     dict = {}   # topic -> List[float] (last N scores this session)
        _pivot_tracking:    dict = {}   # topic -> {event_id, pre_fingerprint} for post-pivot distance
        _PIVOT_THRESHOLD    = 3
        _VARIANCE_THRESHOLD = 0.5       # std < this = near-miss loop
        _VARIANCE_WINDOW    = 3         # min attempts to compute variance
        _CERT_THRESHOLD     = 7.5       # mirrors constants.SUCCESS_SCORE_THRESHOLD

        def _strategy_fingerprint(strats: list) -> str:
            """SHA256[:12] of strategy text -- short stable identifier for comparison."""
            import hashlib
            text = " ".join(
                s.get("topic", "") + " " + s.get("strategy", "") + " " + s.get("outcome", "")
                for s in strats
            ).strip()
            return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else "EMPTY"

        def _strategy_distance(fp_a: str, fp_b: str, strats_a: list, strats_b: list) -> float:
            """Jaccard distance on word tokens between strategy texts (0.0=identical, 1.0=different)."""
            if fp_a == fp_b:
                return 0.0
            def tokens(strats):
                text = " ".join(
                    s.get("topic", "") + " " + s.get("strategy", "") + " " + s.get("outcome", "")
                    for s in strats
                ).lower()
                return set(text.split())
            a, b = tokens(strats_a), tokens(strats_b)
            if not a and not b:
                return 0.0
            intersection = len(a & b)
            union = len(a | b)
            return round(1.0 - intersection / union, 4) if union else 0.0

        # Pre-initialize environment variables so bootstrap blocks can reference them safely
        _self_model        = None
        _world_model       = None
        _desire            = None
        _mood              = None
        _identity          = None
        _skill_lib         = None
        _hebbian_singleton = None
        _core_env          = None
        self._vision_engine = None
        _session_reflection = None
        _bench_tracker     = None
        _session_base_ctx  = ""   # reflection block kept for ContextArbiter (constant per session)
        _id_block          = ""   # identity block kept for ContextArbiter
        # Session-level resolved errors: shared across all topics in this session.
        # Passed by reference — mutations in CertifyRetryGroup propagate back here.
        _session_resolved_errors: set = set()
        # create goal engine tied to the same capability graph
        storage = GoalStorage()
        self.goal_engine = GoalEngine(storage, capability_graph)
        study_agent = StudyAgent(goal_engine=self.goal_engine)
        study_agent._topic_llm_budget = self.topic_budget

        # ── SELF MODEL + WORLD MODEL BOOTSTRAP ───────────────────────────────
        try:
            from backend.self_model import SelfModel
            _self_model = SelfModel.load_or_build()
            self.logger.info(
                "[SELF MODEL] cert_rate=%.0f%%  avg_score=%.1f  momentum=%s  blind_spots=%d",
                _self_model.certification_rate * 100,
                _self_model.avg_score,
                _self_model.momentum,
                len(_self_model.blind_spots),
            )
            # Auto-quarantine composite/junk topics with 2+ failures
            _qc = _self_model._data.get("quarantine_candidates", [])
            if _qc:
                _quarantine_path = Path(__file__).resolve().parents[1] / "shard_memory" / "quarantine.json"
                try:
                    _existing_q = set()
                    if _quarantine_path.exists():
                        _existing_q = set(json.loads(_quarantine_path.read_text(encoding="utf-8")))
                    _new_q = [t for t in _qc if t not in _existing_q]
                    if _new_q:
                        _existing_q.update(_new_q)
                        _quarantine_path.write_text(json.dumps(list(_existing_q), indent=2), encoding="utf-8")
                        self.logger.info("[SELF MODEL] Auto-quarantined %d junk topics: %s", len(_new_q), _new_q[:3])
                except Exception:
                    pass
        except Exception as _sm_err:
            _self_model = None
            self.logger.warning("[SELF MODEL] non-fatal error: %s", _sm_err)

        try:
            from backend.world_model import WorldModel
            _world_model = WorldModel.load_or_default()
            _wm_cov = _world_model.coverage_summary()
            self.logger.info(
                "[WORLD MODEL] coverage=%s%%  known=%d/%d skills",
                _wm_cov["coverage_pct"], _wm_cov["known_skills"], _wm_cov["total_skills"],
            )
            # Self-calibrate relevance scores from SHARD's real cert data
            _wm_adj = _world_model.self_calibrate(min_experiments=10)
            if _wm_adj:
                for sk, delta in _wm_adj.items():
                    self.logger.info(
                        "[WORLD MODEL] Recalibrated '%s': %.3f -> %.3f (cert_rate=%.0f%%, n=%d)",
                        sk, delta["old"], delta["new"], delta["cert_rate"]*100, delta["n"],
                    )
                # Broadcast so GoalEngine can re-evaluate its active goal
                if _core_env:
                    _core_env.broadcast(
                        "world_recalibrated",
                        {"adjustments": list(_wm_adj.keys())[:5]},
                        source="world_model",
                    )
            # Surface top-3 world-priority gaps SHARD doesn't know yet
            _known = set(_self_model.strengths) if _self_model else set()
            _wm_gaps = _world_model.priority_gaps(_known, top_n=3)
            if _wm_gaps:
                self.logger.info(
                    "[WORLD MODEL] Top priority gaps: %s",
                    ", ".join(g["skill"] for g in _wm_gaps),
                )
        except Exception as _wm_err:
            _world_model = None
            self.logger.warning("[WORLD MODEL] non-fatal error: %s", _wm_err)

        # ── AUTONOMOUS GOAL GENERATION ────────────────────────────────────────
        # SHARD reads its own self_model + world_model and decides what to
        # pursue this session -- no human input required.
        try:
            self.goal_engine.capability_graph = capability_graph
            _auto_goal = self.goal_engine.autonomous_generate()
            if _auto_goal:
                self.logger.info(
                    "[GOAL AUTO] Active goal: '%s' | progress=%.0f%% | type=%s",
                    _auto_goal.title,
                    _auto_goal.progress * 100,
                    _auto_goal.goal_type,
                )
                self.logger.info("[GOAL AUTO] Keywords: %s", _auto_goal.domain_keywords)
                self.logger.info("[GOAL AUTO] Reason: %s", _auto_goal.description.splitlines()[1] if '\n' in _auto_goal.description else "")
            else:
                self.logger.info("[GOAL AUTO] No goal generated -- no world model gaps found")
        except Exception as _ag_err:
            self.logger.warning("[GOAL AUTO] non-fatal error: %s", _ag_err)

        # ── SEMANTIC MEMORY BOOTSTRAP ─────────────────────────────────────────
        # Index all existing episodes + knowledge base files into ChromaDB.
        # Skips if already populated (upsert is idempotent, but we avoid the
        # sentence-transformer load overhead when there's nothing new to add).
        try:
            from backend.semantic_memory import get_semantic_memory
            _sem = get_semantic_memory()
            _sem_stats = _sem.stats()
            if _sem_stats["episodes"] == 0 or _sem_stats["knowledge"] == 0:
                self.logger.info("[SEMANTIC] ChromaDB sparse -- running index_all()")
                _sem.index_all(verbose=False)
                _new_stats = _sem.stats()
                self.logger.info(
                    "[SEMANTIC] Indexed: episodes=%d  knowledge=%d  errors=%d",
                    _new_stats["episodes"], _new_stats["knowledge"], _new_stats["errors"],
                )
            else:
                self.logger.info(
                    "[SEMANTIC] ChromaDB ready: episodes=%d  knowledge=%d  errors=%d",
                    _sem_stats["episodes"], _sem_stats["knowledge"], _sem_stats["errors"],
                )
        except Exception as _sem_boot_err:
            self.logger.warning("[SEMANTIC] Bootstrap non-fatal error: %s", _sem_boot_err)

        # ── SSJ3: Proactive self-improvement (ImprovementEngine) ──────────────
        try:
            from backend.self_analyzer import SelfAnalyzer
            from backend.improvement_engine import ImprovementEngine
            _engine = ImprovementEngine()
            # First drain any topics left over from a previous engine run
            _leftover = _engine.peek_queue()
            if _leftover:
                self.logger.info("[SSJ3] Resuming %d improvement topics from previous run", len(_leftover))
                self._improvement_topics = list(_leftover)
            else:
                # Run fresh analysis and populate queue
                _report = await SelfAnalyzer(capability_graph=capability_graph).analyze()
                _result = _engine.run_from_report(_report)
                self._improvement_topics = list(_engine.peek_queue())
                self.logger.info("[SSJ3] %s", _result.summary())
        except Exception as _ssj3_err:
            self.logger.warning("[SSJ3] ImprovementEngine non-fatal error: %s", _ssj3_err)

        # ── DESIRE ENGINE BOOTSTRAP ───────────────────────────────────────────
        try:
            from backend.desire_engine import get_desire_engine
            _desire = get_desire_engine()
            self.logger.info("[DESIRE] %s", _desire.summary())
        except Exception as _de_err:
            _desire = None
            self.logger.warning("[DESIRE] Bootstrap non-fatal error: %s", _de_err)

        # ── COGNITIONCORE ENVIRONMENT -- register all modules ──────────────────
        # Each module becomes a citizen: it can receive and react to broadcasts.
        try:
            from backend.cognition.cognition_core import get_cognition_core
            _core_env = get_cognition_core()
            if _self_model:
                _core_env.register("self_model", _self_model, ["*"])
            if _world_model:
                _core_env.register("world_model", _world_model,
                                   ["skill_certified", "skill_failed", "momentum_changed"])
            _core_env.register("goal_engine", self.goal_engine,
                               ["skill_certified", "skill_failed", "momentum_changed",
                                "frustration_peak", "world_recalibrated", "mood_shift"])
            if _desire:
                _core_env.register("desire_engine", _desire,
                                   ["skill_certified", "skill_failed", "goal_changed",
                                    "momentum_changed", "frustration_peak", "mood_shift"])
            try:
                from backend.semantic_memory import get_semantic_memory as _get_sem_env
                _sem_env = _get_sem_env()
                _core_env.register("semantic_memory", _sem_env,
                                   ["skill_certified", "skill_failed", "frustration_peak"])
            except Exception as _sm_err:
                self.logger.warning("[CORE ENV] semantic_memory register failed: %s", _sm_err)
            try:
                _core_env.register("capability_graph", capability_graph,
                                   ["skill_certified", "skill_failed"])
            except Exception as _cg_err:
                self.logger.warning("[CORE ENV] capability_graph register failed: %s", _cg_err)
            try:
                from backend.improvement_engine import ImprovementEngine as _IE
                _imp_env = _IE()
                _core_env.register("improvement_engine", _imp_env,
                                   ["skill_certified", "skill_failed", "frustration_peak"])
            except Exception as _ie_err:
                self.logger.warning("[CORE ENV] improvement_engine register failed: %s", _ie_err)
            try:
                from backend.consciousness import ShardConsciousness as _SC
                from backend.memory import ShardMemory as _SM_c
                _mem_c = _SM_c()
                _consciousness_env = _SC(_mem_c, capability_graph, self.goal_engine)
                _core_env.register("consciousness", _consciousness_env,
                                   ["skill_certified", "skill_failed", "frustration_peak",
                                    "momentum_changed", "mood_shift", "identity_updated"])
            except Exception as _cs_err:
                self.logger.warning("[CORE ENV] consciousness register failed: %s", _cs_err)
            try:
                from backend.self_model_tracker import SelfModelTracker
                _self_tracker = SelfModelTracker(
                    think_fn=getattr(study_agent, "_think_fast", None)
                )
                _core_env.register("self_model_tracker", _self_tracker,
                                   ["session_complete", "mood_shift", "identity_updated"])
            except Exception as _cd_err:
                self.logger.warning("[CORE ENV] self_model_tracker register failed: %s", _cd_err)
                _self_tracker = None
            self.logger.info(
                "[CORE ENV] %d module(s) registered in shared environment",
                len(_core_env._registry),
            )
        except Exception as _env_err:
            _core_env = None
            self.logger.warning("[CORE ENV] Registration non-fatal: %s", _env_err)

        # ── MOOD ENGINE ───────────────────────────────────────────────────────
        try:
            from backend.mood_engine import MoodEngine as _ME
            _mood = _ME()
            # Register in CognitionCore BEFORE first compute so broadcast works
            if _core_env:
                _core_env.register(
                    "mood_engine", _mood,
                    ["frustration_peak", "momentum_changed", "skill_certified", "skill_failed"],
                )
                _mood._core_env = _core_env
            _mood.compute(desire_engine=_desire, momentum="stable")
            self.logger.info(
                "[MOOD] Initial state: score=%.3f (%s)",
                _mood.get_score(), _mood.get_label(),
            )
        except Exception as _mood_err:
            self.logger.warning("[MOOD] Init non-fatal: %s", _mood_err)

        # ── MOOD-WORKSPACE COUPLING (GWT Phase 5) ─────────────────────────────
        _mood_coupling = None
        if self._use_affective_layer:
            try:
                from backend.cognition.mood_workspace_coupling import MoodWorkspaceCoupling as _MWC
                _mood_coupling = _MWC()
                self.logger.info("[GWT-P5] MoodWorkspaceCoupling initialised")
            except Exception as _mwc_err:
                self.logger.warning("[GWT-P5] MoodWorkspaceCoupling init non-fatal: %s", _mwc_err)

        # ── VISION LAYER ──────────────────────────────────────────────────────
        try:
            from backend.vision import get_vision as _get_vision
            self._vision_engine = _get_vision()
            self.logger.info("[VISION] Mission: %s", self._vision_engine.statement[:120])
            self.logger.info("[VISION] Focus: %s", ", ".join(self._vision_engine.focus_domains[:6]))
            if self._vision_engine.avoid_domains:
                self.logger.info("[VISION] Avoid: %s", ", ".join(self._vision_engine.avoid_domains[:6]))
            if _core_env:
                _core_env.register(
                    "vision", self._vision_engine,
                    ["skill_certified", "frustration_peak", "momentum_changed"],
                )
                self.logger.info("[VISION] Registered in CognitionCore.")
        except Exception as _ve_err:
            self.logger.warning("[VISION] non-fatal: %s", _ve_err)

        # ── SESSION REFLECTION -- inject past context (L1 gate) ────────────────
        # Skip on early sessions (total_experiments <= 5) or 'early' momentum
        # unless session count exceeds 15 (safety fallback to always load).
        # This avoids injecting stale/noisy reflection when SHARD has little history.
        try:
            _total_exp = _self_model.total_experiments if _self_model else 0
            _momentum  = _self_model.momentum if _self_model else "early"
            _load_reflection = (
                _total_exp > 15                              # always load after 15 experiments
                or (_total_exp > 5 and _momentum != "early") # load if some history and not early
            )
            if not _load_reflection:
                self.logger.info(
                    "[REFLECTION] Skipped (L1 gate): experiments=%d momentum=%s -- too early for reflection.",
                    _total_exp, _momentum,
                )
            else:
                from backend.session_reflection import make_session_reflection as _make_sr
                _session_reflection = _make_sr(llm_call_fn=None)  # LLM attached at end of session
                _sr_block = _session_reflection.get_context_block()
                # Also inject open questions from SelfModelTracker (real prediction errors)
                try:
                    from backend.self_model_tracker import SelfModelTracker as _SMT
                    _hypo_block = _SMT.get_context_block()
                except Exception:
                    _hypo_block = ""
                _full_context = "\n\n".join(b for b in [_sr_block, _hypo_block] if b)
                if _full_context:
                    self.logger.info(
                        "[REFLECTION] Past context loaded (%d chars) -- injecting into study_agent system prompt.",
                        len(_full_context),
                    )
                    _session_base_ctx = _full_context
                    study_agent.session_context = _full_context
                else:
                    self.logger.info("[REFLECTION] No past context -- first session.")
        except Exception as _sr_err:
            self.logger.warning("[REFLECTION] non-fatal: %s", _sr_err)

        # ── HEBBIAN UPDATER -- register as CognitionCore citizen ─────────────
        try:
            from backend.hebbian_updater import HebbianUpdater as _HU_cls
            _hebbian_singleton = _HU_cls()
            if _core_env:
                _core_env.register(
                    "hebbian_updater", _hebbian_singleton,
                    ["mood_shift", "skill_certified", "skill_failed"],
                )
            self.logger.info("[HEBBIAN] Registered in CognitionCore.")
        except Exception as _hu_err:
            self.logger.warning("[HEBBIAN] Init non-fatal: %s", _hu_err)

        # ── SKILL LIBRARY -- load Voyager-style skill cache ───────────────────
        try:
            from backend.skill_library import SkillLibrary as _SL
            _skill_lib = _SL()
            if _core_env:
                _core_env.register("skill_library", _skill_lib, ["skill_certified"])
            _sl_stats = _skill_lib.get_stats()
            self.logger.info(
                "[SKILL_LIB] Loaded -- %d certified skills (avg=%.1f)",
                _sl_stats["total_skills"], _sl_stats["avg_score"],
            )
        except Exception as _sl_err:
            self.logger.warning("[SKILL_LIB] Init non-fatal: %s", _sl_err)

        # ── IDENTITY CORE -- inject persistent biography ───────────────────────
        if self._use_affective_layer:
            try:
                from backend.identity_core import IdentityCore as _IC
                _identity = _IC()
                if _core_env:
                    _core_env.register(
                        "identity_core", _identity,
                        ["session_complete", "skill_certified", "skill_failed"],
                    )
                    _identity._core_env = _core_env
                _id_block = _identity.get_context_block()
                if _id_block:
                    _id_status = _identity.get_status()
                    if self._use_affective_layer:
                        # With ContextArbiter: biography competes per-cycle, not injected here
                        self.logger.info(
                            "[IDENTITY] Biography loaded (%d chars) sessions=%d self_esteem=%.2f trajectory=%s -- will compete via ContextArbiter",
                            len(_id_block),
                            _id_status.get("sessions_lived", 0),
                            _id_status.get("self_esteem", 0.0),
                            _id_status.get("trajectory", "unknown"),
                        )
                    else:
                        _base_ctx = study_agent.session_context or ""
                        study_agent.session_context = "\n\n".join(b for b in [_id_block, _base_ctx] if b)
                        self.logger.info(
                            "[IDENTITY] Biography injected (%d chars) -- sessions=%d self_esteem=%.2f trajectory=%s",
                            len(_id_block),
                            _id_status.get("sessions_lived", 0),
                            _id_status.get("self_esteem", 0.0),
                            _id_status.get("trajectory", "unknown"),
                        )
                else:
                    self.logger.info("[IDENTITY] No biography yet -- first session.")
            except Exception as _id_init_err:
                self.logger.warning("[IDENTITY] Init non-fatal: %s", _id_init_err)
        else:
            self.logger.info("[IDENTITY] Skipped (use_affective_layer=False)")

        # ── BENCHMARK TRACKER -- log delta from previous session ───────────────
        try:
            from backend.benchmark_tracker import get_benchmark_tracker as _get_btrk
            _bench_tracker = _get_btrk()
            _prev_delta_str = _bench_tracker.get_delta_summary()
            self.logger.info("[BENCH TRACKER] Previous session: %s", _prev_delta_str)
        except Exception as _bt_err:
            self.logger.warning("[BENCH TRACKER] non-fatal: %s", _bt_err)

        # ── GAP DETECTOR: Autonomous failure-driven study topic injection ──────
        # Reads benchmark_episodes.json, clusters error patterns, enqueues gaps.
        try:
            from backend.gap_detector import GapDetector
            _gap_report = GapDetector().detect(enqueue=True)
            self.logger.info("[GAP] %s", _gap_report.summary())
            if _gap_report.topics_queued:
                # Reload improvement queue -- now includes both SSJ3 + gap topics
                from backend.improvement_engine import ImprovementEngine as _IE2
                self._improvement_topics = list(_IE2().peek_queue())
        except Exception as _gap_err:
            self.logger.warning("[GAP] GapDetector non-fatal error: %s", _gap_err)

        for cycle in range(1, self.max_cycles + 1):
            limit_reason = self._check_limits(cycle)
            if limit_reason:
                self.logger.info(f"Session stopped: {limit_reason}")
                break
                
            self._transition(SessionState.SELECT, f"cycle {cycle}/{self.max_cycles}")
            topic, source, reason = await self._select_topic(capability_graph, "")
            self._record_topic(topic, source)  # agenda starvation fix #29

            # ── PREREQUISITE GATE -- se il topic è difficile, studia prima i prereq ──
            try:
                from backend.prerequisite_checker import get_missing_prerequisites as _get_prereqs
                from shard_db import query as _prereq_db
                # Calcola sig_difficulty dal DB (stesso calcolo di prima del ciclo)
                _prereq_exps = _prereq_db(
                    "SELECT certified FROM experiments WHERE topic=? ORDER BY created_at DESC LIMIT 10",
                    (topic,),
                )
                if _prereq_exps:
                    _prereq_cert_r = sum(1 for e in _prereq_exps if e["certified"]) / len(_prereq_exps)
                    _prereq_difficulty = round(1.0 - _prereq_cert_r, 2)
                else:
                    _prereq_difficulty = 0.5
                _missing_prereqs = get_missing_prerequisites(topic, capability_graph, _prereq_difficulty)
                if _missing_prereqs:
                    _original_topic = topic
                    # Filter out prereqs that are quarantined, avoided, or invalid
                    _safe_prereqs = [
                        _p for _p in _missing_prereqs
                        if (
                            is_valid_topic(_p, self.logger)
                            and not is_trivial_topic(_p, self.logger)
                            and not self._is_quarantined(_p)
                            and not self._is_avoided(_p)
                            and not self._prereq_is_stuck(_p)  # #46 goal cooldown
                        )
                    ]
                    if _safe_prereqs:
                        _prereq_topic = _safe_prereqs[0]
                        self.logger.info(
                            "[PREREQ] '%s' (difficulty=%.2f) needs '%s' first -- redirecting",
                            _original_topic, _prereq_difficulty, _prereq_topic,
                        )
                        # Queue remaining prereqs + original topic for future cycles
                        try:
                            from backend.improvement_engine import ImprovementEngine as _IE_prereq
                            _ie_prereq = _IE_prereq()
                            for _p in reversed(_safe_prereqs[1:] + [_original_topic]):
                                _ie_prereq.enqueue_topics([_p])
                        except Exception:
                            pass
                        topic  = _prereq_topic
                        source = "prerequisite"
                        reason = f"Prerequisite for '{_original_topic}' (difficulty={_prereq_difficulty:.2f})"
                    else:
                        self.logger.debug(
                            "[PREREQ] All prereqs for '%s' are quarantined/invalid -- proceeding as-is",
                            _original_topic,
                        )
            except Exception as _prereq_err:
                self.logger.debug("[PREREQ] non-fatal: %s", _prereq_err)

            # ── AFFORDANCE GATE -- se il topic è fuori portata, decomponilo ──
            try:
                from backend.affordance_filter import check_affordance as _check_afford
                _aff = _check_afford(topic, capability_graph)
                if not _aff.feasible:
                    _aff_original = topic
                    _aff_sub = [
                        _s for _s in _aff.sub_topics
                        if (
                            is_valid_topic(_s, self.logger)
                            and not is_trivial_topic(_s, self.logger)
                            and not self._is_quarantined(_s)
                            and not self._is_avoided(_s)
                        )
                    ]
                    if _aff_sub:
                        self.logger.info(
                            "[AFFORD] '%s' (feasibility=%.2f) out of reach -- decomposing into %r",
                            _aff_original, _aff.feasibility, _aff_sub,
                        )
                        try:
                            from backend.improvement_engine import ImprovementEngine as _IE_aff
                            _ie_aff = _IE_aff()
                            for _s in reversed(_aff_sub[1:] + [_aff_original]):
                                _ie_aff.enqueue_topics([_s])
                        except Exception:
                            pass
                        # Apply certified-recently guard to affordance sub-topic too
                        if self._is_certified_recently(_aff_sub[0], hours=24):
                            self.logger.info(
                                "[AFFORD] Sub-topic '%s' certified recently — keeping original '%s'",
                                _aff_sub[0], _aff_original,
                            )
                        else:
                            topic  = _aff_sub[0]
                            source = "affordance"
                            reason = f"Decomposed from '{_aff_original}' (feasibility={_aff.feasibility:.2f})"
                    else:
                        self.logger.debug(
                            "[AFFORD] All sub-topics for '%s' are invalid/quarantined -- proceeding as-is",
                            _aff_original,
                        )
            except Exception as _aff_err:
                self.logger.debug("[AFFORD] non-fatal: %s", _aff_err)

            self.logger.info(f"=== Cycle {cycle}/{self.max_cycles} ===")
            self.logger.info(f"Topic selected: {topic}")
            self.logger.info(f"Source: {source}")
            self.logger.info(f"Reason: {reason}")
            
            cycle_start = time.time()
            cycle_data = {
                "cycle_number": cycle,
                "topic": topic,
                "source": source,
                "reason": reason,
                "certified": False,
                "score": 0.0,
                "skills_before": len(capability_graph.capabilities),
                "strategies_reused": []
            }
            _evolved_strategy: str | None = None   # set by EvoScientist if pivot fires this cycle

            strategy_memory = StrategyMemory()
            strategies = strategy_memory.query(topic, k=1)
            if strategies:
                strat_name = strategies[0]["topic"]
                self.logger.info(f"[STRATEGY] Reusing strategy: {strat_name} for topic: {topic}")
                cycle_data["strategies_reused"].append(strat_name)
            else:
                self.logger.info(f"[STRATEGY] No existing strategy found for: {topic}")

            # ── POST-PIVOT: fingerprint + distance measurement ────────────────
            # If this topic had a pivot, compare new strategy with pre-pivot one.
            _post_fp = _strategy_fingerprint(strategies)
            self.logger.info("[STRATEGY] fingerprint=%s  strategies=%d", _post_fp, len(strategies))
            if topic in _pivot_tracking:
                _pt = _pivot_tracking[topic]
                _dist = _strategy_distance(_pt["pre_fingerprint"], _post_fp,
                                           _pt["pre_strategies"], strategies)
                _direction = (
                    "DIFFERENT (agency?)" if _dist > 0.5
                    else "SIMILAR (bias?)" if _dist > 0.1
                    else "IDENTICAL (deterministic bias)"
                )
                self.logger.warning(
                    "[POST-PIVOT] '%s': pre=%s -> post=%s  distance=%.3f  -> %s",
                    topic, _pt["pre_fingerprint"], _post_fp, _dist, _direction,
                )
                try:
                    from shard_db import execute as _pe_exec
                    _pe_exec(
                        "UPDATE pivot_events SET post_fingerprint=?, distance=? WHERE id=?",
                        (_post_fp, _dist, _pt["event_id"]),
                    )
                except Exception as _pe_err:
                    self.logger.debug("[POST-PIVOT] DB update failed: %s", _pe_err)
                del _pivot_tracking[topic]  # clear after first post-pivot cycle

            # ── SELF-MODEL: predict score before studying ─────────────────────
            # Features are observable facts about this cycle -- not invented.
            # sig_* are citizen signals (0.0-1.0) for activation_log / synaptic weights.
            _sig_desire     = 0.0
            _sig_difficulty = 0.5
            _sig_graphrag   = 0.0

            # sig_desire -- desire_score composito (frustration + curiosity + engagement)
            try:
                from backend.desire_engine import get_desire_engine as _get_de_sig
                _de_sig = _get_de_sig()
                _desire_ctx = _de_sig.get_desire_context(topic)
                _sig_desire = round(float(_desire_ctx.get("desire_score", 0.0)), 4)
            except Exception:
                pass

            # sig_difficulty -- 1 - cert_rate storica (topic mai visto = 0.5 neutro)
            try:
                from shard_db import query as _smq_diff
                _diff_hist = _smq_diff(
                    "SELECT certified FROM experiments WHERE topic=? "
                    "ORDER BY timestamp DESC LIMIT 10", (topic,)
                )
                if _diff_hist:
                    _cert_r = sum(1 for r in _diff_hist if r["certified"]) / len(_diff_hist)
                    _sig_difficulty = round(1.0 - _cert_r, 2)
            except Exception:
                pass

            if _self_tracker:
                try:
                    from shard_db import query as _smq
                    _prior = _smq(
                        "SELECT score FROM experiments WHERE topic=? AND score IS NOT NULL "
                        "ORDER BY timestamp DESC LIMIT 5", (topic,)
                    )
                    _prior_scores = [r["score"] for r in _prior]

                    # sig_graphrag -- conteggio reale relazioni causali nel knowledge graph
                    try:
                        from backend.graph_rag import count_causal_hits as _cch
                        _sig_graphrag = round(min(1.0, _cch(topic) / 10.0), 2)
                    except Exception:
                        _sig_graphrag = 1.0 if _prior_scores else 0.0

                    _cycle_features = {
                        "had_episodic_context": bool(_prior_scores),
                        "strategy_reused":      bool(strategies),
                        "near_miss_history":    any(6.0 <= s <= 7.4 for s in _prior_scores),
                        "first_attempt":        len(_prior_scores) == 0,
                        "graphrag_hits":        _sig_graphrag,
                        "source_improvement":   source == "improvement_engine",
                        # Continuous signals -- feed into predictive processing loop
                        "sig_difficulty":       _sig_difficulty,
                        "sig_desire":           _sig_desire,
                        "sig_graphrag":         _sig_graphrag,
                    }
                    _predicted_score = _self_tracker.predict_before(topic, _cycle_features)
                    self.logger.info(
                        "[SELF_MODEL] Predicted score for '%s': %.1f | "
                        "desire=%.2f difficulty=%.2f graphrag=%.2f",
                        topic, _predicted_score,
                        _sig_desire, _sig_difficulty, _sig_graphrag,
                    )
                except Exception as _sm_err:
                    _cycle_features = {}
                    _predicted_score = None
                    self.logger.debug("[SELF_MODEL] predict_before non-fatal: %s", _sm_err)
            else:
                _cycle_features = {}
                _predicted_score = None

            # Operational contradiction gate -- runs after prediction, before persona/study.
            try:
                _kcd = self._get_knowledge_contradiction_detector()
                if _kcd is not None:
                    _analysis = _kcd.analyze(
                        topic=topic,
                        predicted_score=_predicted_score,
                        category=cycle_data.get("source"),
                        capability_graph=capability_graph,
                    )
                    topic, source, reason, _predicted_score = self._apply_knowledge_contradiction_analysis(
                        _analysis,
                        topic,
                        source,
                        reason,
                        _predicted_score,
                    )
                    cycle_data["topic"] = topic
                    cycle_data["source"] = source
                    if _predicted_score is not None:
                        self.logger.info("[KCD] Final predicted score for '%s': %.1f", topic, _predicted_score)
            except Exception as _kcd_err:
                self.logger.debug("[KCD] analyze/apply non-fatal: %s", _kcd_err)

            # Epistemic penalty: weak causal subgraph → lower predicted_score
            try:
                from backend.graph_rag import get_epistemic_profile
                _ep = get_epistemic_profile(topic)
                if _ep.get("freshness", 1.0) < 0.4 and _ep.get("total", 0) > 3:
                    _old_score = _predicted_score or 5.0
                    _predicted_score = max(0.0, _old_score - 1.5)
                    self.logger.info(
                        "[EPISTEMIC] Topic '%s' sottografo debole (freshness=%.2f) — predicted_score %.1f -> %.1f",
                        topic, _ep["freshness"], _old_score, _predicted_score,
                    )
            except Exception:
                pass

            async def on_certify(t, s, e_data):
                cycle_data["certified"] = True
                cycle_data["score"] = s
                # Capture winning code + pass_rate for skill_implementations (#13)
                cycle_data["pass_rate"] = e_data.get("pass_rate") or 0.0
                cycle_data["winning_code"] = e_data.get("winning_code") or ""
                _vb(f"Topic certificato: {t}. Score: {s} su dieci.", priority="low", event_type="cycle_certified")
                
            # Fix B: extract previous_score from Phoenix replay reason tag
            prev_score = None
            if source == "failure_replay" and "|prev_score=" in reason:
                try:
                    prev_score = float(reason.split("|prev_score=")[1])
                    self.logger.info(f"[PHOENIX] Injecting previous_score={prev_score} into study pipeline")
                except (ValueError, IndexError):
                    pass

            # Dynamic persona selection -- picks best study strategy for this topic/category
            persona_cfg = select_persona(topic, category=cycle_data.get("source"))
            self.logger.info(
                "[PERSONA] Selected '%s' (tier=%d) for: %s",
                persona_cfg.persona.value, persona_cfg.tier, topic,
            )

            try:
                self._transition(SessionState.STUDY, topic)
                self.api_calls_used += 3

                # ── SKILL LIBRARY -- collect block for ContextArbiter ────────
                _sl_injected = False
                _combined    = ""
                if _skill_lib is not None:
                    try:
                        _sl_block   = _skill_lib.get_injection_block(topic, capability_graph)
                        _impl_block = _skill_lib.get_implementation_block(topic)
                        _combined   = "\n\n".join(b for b in [_sl_block, _impl_block] if b)
                        if _combined:
                            _sl_injected = True
                            self.logger.info("[SKILL_LIB] Loaded %d chars for topic '%s'", len(_combined), topic)
                    except Exception as _sl_inj_err:
                        self.logger.debug("[SKILL_LIB] inject non-fatal: %s", _sl_inj_err)

                # ── MOOD COMPUTE (always) + CONTEXT ARBITER (if affective layer ON) ──
                _mood_score = 0.0
                _mood_label = "neutral"
                _mood_hint  = ""
                _directives: dict = {}
                _domain_dir = ""
                if _mood:
                    try:
                        _wb = _mood_coupling.get_bias() if _mood_coupling else 0.0
                        _mood.compute(desire_engine=_desire, momentum=getattr(self, "_last_momentum", "stable"), workspace_bias=_wb)
                        _mood_label = _mood.get_label()
                        _mood_hint  = _mood.get_prompt_hint()
                        _directives = _mood.get_behavior_directives() if self._use_affective_layer else {}
                        _mood_score = _mood.get_score() if self._use_affective_layer else 0.0
                        self.logger.info(
                            "[MOOD] %s (%.3f) directives=%s",
                            _mood_label, _mood.get_score(), list(_directives.keys()),
                        )
                    except Exception as _mi_err:
                        self.logger.debug("[MOOD] compute non-fatal: %s", _mi_err)

                if _identity is not None and self._use_affective_layer:
                    try:
                        _domain_dir = _identity.get_domain_directive(topic)
                    except Exception:
                        pass

                if self._use_affective_layer:
                    # ── AROUSAL-THRESHOLD COUPLING (Yerkes-Dodson) ────────────
                    _arousal = abs(_mood_score)
                    _valence = _mood_score
                    _base_budget = self.topic_budget
                    if _valence < -0.3 and _arousal > 0.4:
                        _effective_budget = max(5, round(_base_budget * 0.7))
                    elif _valence > 0.3 and _arousal > 0.4:
                        _effective_budget = round(_base_budget * 1.3)
                    else:
                        _effective_budget = _base_budget
                    _remaining_session = self.max_api_calls - self.api_calls_used
                    _effective_budget = min(_effective_budget, max(1, _remaining_session - 2))
                    study_agent._topic_llm_budget = max(1, _effective_budget)
                    self.logger.info(
                        "[ARBITER] Budget adjusted: base=%d -> effective=%d (mood=%.2f, arousal=%.2f)",
                        _base_budget, study_agent._topic_llm_budget, _valence, _arousal,
                    )

                    # ── CONTEXT ARBITER: competitive prompt assembly ──────────
                    from backend.context_arbiter import ContextArbiter as _CA
                    _ctx_arb = _CA(max_tokens=500)

                    if not _directives.get("clear_context"):
                        if _session_base_ctx:
                            _ctx_arb.add_block(_session_base_ctx, "past_context", 0.75)
                    else:
                        self.logger.info("[MOOD] Behavior: clear_context → fresh start for '%s'", topic)

                    if _id_block:
                        _ctx_arb.add_block(_id_block, "identity_block", 0.70)

                    if _combined:
                        _sl_affinity = 1.0 if _sl_injected else 0.5
                        _ctx_arb.add_block(_combined, "skill_library", 0.60, topic_affinity=_sl_affinity)

                    if _mood_hint:
                        _ctx_arb.add_block(_mood_hint, "mood_hint", 0.90)

                    if _directives.get("decompose_first"):
                        _ctx_arb.add_block(
                            "[BEHAVIOR DIRECTIVE] Break this topic into sub-problems first. "
                            "Do NOT jump to a solution before decomposing.",
                            "behavior_directive", 0.85,
                        )
                    elif _directives.get("push_deeper"):
                        _ctx_arb.add_block(
                            "[BEHAVIOR DIRECTIVE] You are performing well on this domain. "
                            "Focus on advanced mechanisms and edge cases, not basics.",
                            "behavior_directive", 0.85,
                        )

                    if _domain_dir:
                        _ctx_arb.add_block(_domain_dir, "domain_directive", 0.80)

                    _task_type = _classify_topic(topic)
                    study_agent.session_context = _ctx_arb.select(_mood_score, task_type=_task_type)

                else:
                    # ── AFFECTIVE LAYER OFF: old sequential injection ─────────
                    if _combined:
                        _base_ctx = study_agent.session_context or ""
                        study_agent.session_context = "\n\n".join(b for b in [_combined, _base_ctx] if b)
                        self.logger.info("[SKILL_LIB] Injected %d chars for topic '%s'", len(_combined), topic)

                    if _mood and _mood_hint:
                        if _mood.get_behavior_directives().get("clear_context"):
                            study_agent.session_context = ""
                            self.logger.info("[MOOD] Behavior: clear_context → fresh start for '%s'", topic)
                        _base_ctx = study_agent.session_context or ""
                        study_agent.session_context = (
                            f"[AFFECTIVE STATE: {_mood_label.upper()}] {_mood_hint}\n\n{_base_ctx}"
                        ).strip()
                        # Behavior directives intentionally NOT injected in OFF mode:
                        # GWT_OFF is a clean sequential-injection baseline. Injecting
                        # directives in both conditions would conflate directive effect
                        # with ContextArbiter effect in A/B comparisons.
                        self.logger.info(
                            "[MOOD] Injected: %s (%.3f) [no directives — OFF baseline]",
                            _mood_label, _mood.get_score(),
                        )
                    elif _mood:
                        self.logger.info("[MOOD] Skipped (use_affective_layer=False)")

                    if _identity is not None and _domain_dir:
                        _ctx = study_agent.session_context or ""
                        study_agent.session_context = (_domain_dir + "\n\n" + _ctx).strip()
                        self.logger.info("[IDENTITY] Domain directive injected for topic '%s'", topic)

                # Compute previous_attempts for L3 gate: failed experiments on this topic
                _prev_attempts = 0
                try:
                    from shard_db import query as _q_prev
                    _prev_attempts = len([
                        r for r in _q_prev(
                            "SELECT certified FROM experiments WHERE topic=? "
                            "ORDER BY timestamp DESC LIMIT 10", (topic,)
                        )
                        if not r["certified"]
                    ])
                except Exception:
                    pass

                best_score = await study_agent.study_topic(
                    topic=topic,
                    tier=persona_cfg.tier,
                    on_certify=on_certify,
                    previous_score=prev_score,
                    predicted_score=_predicted_score,
                    blind_spots=list(_self_model.blind_spots) if _self_model else [],
                    previous_attempts=_prev_attempts,
                    resolved_errors=_session_resolved_errors,
                    research_mode=self._research_mode,
                    no_l3=self._no_l3,
                )

                # Capture actual LLM calls BEFORE resetting (used by A/B test metrics)
                cycle_data["topic_llm_calls"] = study_agent._topic_llm_calls

                # Reset per-topic budget so in-cycle overhead (proactive refactor on
                # failure) can call _think_fast without hitting the study budget.
                study_agent._topic_llm_calls = 0

                # ── GWT Phase 5: feed workspace winner back into MoodWorkspaceCoupling ──
                if _mood_coupling and _core_env is not None:
                    _ignition_failed = _core_env.last_workspace_winner is None
                    _mood_coupling.on_workspace_result(
                        winner_module=_core_env.last_workspace_winner,
                        ignition_failed=_ignition_failed,
                    )

                # Reset session_context for next topic
                if self._use_affective_layer:
                    # ContextArbiter rebuilds from _session_base_ctx each cycle
                    study_agent.session_context = ""
                else:
                    # Old behavior: strip mood and skill lib prefixes
                    _ctx = study_agent.session_context or ""
                    if _mood and "[AFFECTIVE STATE:" in _ctx:
                        _ctx = "\n\n".join(
                            p for p in _ctx.split("\n\n")
                            if not p.startswith("[AFFECTIVE STATE:")
                        ).strip()
                    if _sl_injected and ("=== SHARD SKILL LIBRARY" in _ctx or "[PAST WORKING CODE" in _ctx):
                        _ctx = "\n\n".join(
                            p for p in _ctx.split("\n\n")
                            if not p.startswith("=== SHARD SKILL LIBRARY")
                            and not p.startswith("[PAST WORKING CODE")
                        ).strip()
                    study_agent.session_context = _ctx
                # study_topic returns a dict {"score": float, "certified": bool, ...}
                _study_score = best_score.get("score", 0.0) if isinstance(best_score, dict) else (best_score or 0.0)
                if not cycle_data["certified"] and _study_score:
                    cycle_data["score"] = _study_score
                    _vb(f"Topic fallito: {topic}. Miglior score raggiunto: {round(_study_score, 2)} su dieci.", priority="medium", event_type="cycle_failed")
                self.logger.info(f"Sandbox/Study result: {'success' if cycle_data['certified'] else 'failed'}")

                # ── Strategy pivot -- chronic block detection ──────────────────
                # Track scores for variance check regardless of outcome
                _cycle_score = cycle_data["score"] or 0.0
                _recent_scores.setdefault(topic, []).append(_cycle_score)

                if cycle_data["certified"]:
                    _consecutive_fails[topic] = 0   # reset on success
                else:
                    _consecutive_fails[topic] = _consecutive_fails.get(topic, 0) + 1

                # --- Trigger A: fail streak ---
                _trigger_a = _consecutive_fails.get(topic, 0) >= _PIVOT_THRESHOLD

                # --- Trigger B: near-miss loop (variance) ---
                _trigger_b = False
                _scores_window = _recent_scores.get(topic, [])[-_VARIANCE_WINDOW:]
                if (
                    len(_scores_window) >= _VARIANCE_WINDOW
                    and all(s < _CERT_THRESHOLD for s in _scores_window)
                ):
                    _mean = sum(_scores_window) / len(_scores_window)
                    _std  = (sum((s - _mean) ** 2 for s in _scores_window) / len(_scores_window)) ** 0.5
                    if _std < _VARIANCE_THRESHOLD:
                        _trigger_b = True
                        self.logger.info(
                            "[STRATEGY PIVOT] Near-miss loop on '%s': "
                            "scores=%s  std=%.2f < %.1f",
                            topic, [round(s, 1) for s in _scores_window], _std, _VARIANCE_THRESHOLD,
                        )

                if _trigger_a or _trigger_b:
                    _trigger_reason = (
                        f"A:fail_streak={_consecutive_fails.get(topic, 0)}" if _trigger_a
                        else f"B:near_miss_loop std={round(_std, 2)}"
                    )
                    _fail_streak_val = _consecutive_fails.get(topic, 0)
                    _std_val         = _std if _trigger_b else None

                    # Capture pre-pivot state for distance measurement
                    _pre_strategies  = list(strategies)   # snapshot current strategies
                    _pre_fp          = _strategy_fingerprint(_pre_strategies)
                    _prev_count      = len(_pre_strategies)

                    # ── EvoScientist: synthesise evolved strategy before wipe ──
                    _evolved_strategy: str | None = None
                    try:
                        from backend.strategy_mutator import StrategyMutator as _SM
                        _evolved_strategy = await _SM().evolve(
                            _pre_strategies, topic, study_agent._think_fast
                        )
                    except Exception as _evo_err:
                        self.logger.debug("[EVOSCI] non-fatal: %s", _evo_err)

                    try:
                        _cleared = strategy_memory.pivot_on_chronic_block(topic)
                        # Store evolved strategy AFTER wipe so it is the only survivor
                        if _evolved_strategy:
                            await strategy_memory.store_strategy_async(
                                topic=topic,
                                strategy=_evolved_strategy,
                                outcome="evolved",
                                score=5.0,
                            )
                            self.logger.info(
                                "[EVOSCI] Evolved strategy stored for '%s': '%s'",
                                topic, _evolved_strategy[:80],
                            )
                        self.logger.warning(
                            "[STRATEGY PIVOT] topic='%s'  reason=%s  "
                            "prev_strategies=%d  cleared=%s",
                            topic, _trigger_reason, _prev_count,
                            "true" if _cleared > 0 else "false",
                        )
                        # Write structured record to SQLite
                        try:
                            from shard_db import execute as _pe_exec, get_db as _pe_db
                            _pe_exec(
                                """INSERT INTO pivot_events
                                   (session_id, topic, timestamp, reason,
                                    fail_streak, variance_std,
                                    prev_strategies, cleared, pre_fingerprint)
                                   VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, ?)""",
                                (
                                    self.session_id, topic, _trigger_reason,
                                    _fail_streak_val, _std_val,
                                    _prev_count, int(_cleared > 0), _pre_fp,
                                ),
                            )
                            _event_id = _pe_db().execute(
                                "SELECT last_insert_rowid() AS id"
                            ).fetchone()["id"]
                            # Store for post-pivot distance measurement
                            _pivot_tracking[topic] = {
                                "event_id":        _event_id,
                                "pre_fingerprint": _pre_fp,
                                "pre_strategies":  _pre_strategies,
                            }
                        except Exception as _pe_err:
                            self.logger.debug("[STRATEGY PIVOT] DB insert failed: %s", _pe_err)

                        _consecutive_fails[topic] = 0
                        _recent_scores[topic] = []   # reset window after pivot
                    except Exception as _piv_err:
                        self.logger.debug("[STRATEGY PIVOT] non-fatal: %s", _piv_err)

                # Record outcome for meta-learning persona improvement
                record_outcome(
                    topic=topic,
                    category=cycle_data.get("source"),
                    persona=persona_cfg.persona,
                    certified=cycle_data["certified"],
                    score=cycle_data["score"] or 0.0,
                )

                # ── ENVIRONMENT BROADCAST -- modules react autonomously ─────
                # One broadcast replaces all the manual per-module calls below.
                # WorldModel, GoalEngine, DesireEngine all react via on_event().
                try:
                    from backend.desire_engine import compute_engagement_score as _eng_score
                    _engagement = _eng_score(certified=cycle_data["certified"])

                    if cycle_data["certified"]:
                        # Save to Voyager skill library (no regression)
                        if _skill_lib is not None:
                            try:
                                _sl_session = datetime.now().strftime("%Y%m%d_%H%M%S")
                                _sl_strats  = cycle_data.get("strategies_reused", [])
                                _skill_lib.save_skill(
                                    topic=topic,
                                    score=cycle_data["score"] or 7.5,
                                    session_id=_sl_session,
                                    strategies=_sl_strats,
                                )
                                # Save winning implementation (Voyager #13)
                                _impl_code = cycle_data.get("winning_code")
                                _impl_pass_rate = cycle_data.get("pass_rate", 0.0) or 0.0
                                if _impl_code and _impl_pass_rate >= 0.80:
                                    _skill_lib.save_implementation(
                                        topic=topic,
                                        code=_impl_code,
                                        score=cycle_data["score"] or 7.5,
                                        pass_rate=_impl_pass_rate,
                                    )
                            except Exception as _sl_save_err:
                                self.logger.debug("[SKILL_LIB] save non-fatal: %s", _sl_save_err)

                        # Broadcast: skill certified -> all registered modules react
                        if _core_env:
                            _n_rcv = _core_env.broadcast(
                                "skill_certified",
                                {"topic": topic, "score": cycle_data["score"] or 7.5},
                                source="night_runner",
                            )
                            self.logger.info(
                                "[CORE ENV] broadcast 'skill_certified' -> %d recipient(s) reacted",
                                _n_rcv,
                            )
                        # Desire engine: record engagement (not covered by on_event)
                        if _desire:
                            _desire.record_engagement(topic, _engagement)
                        # SelfModel incremental update
                        if _self_model:
                            _self_model.update_from_session(
                                certified=[topic], failed=[],
                                scores=[cycle_data["score"] or 0.0],
                            )
                    else:
                        # Failed cycle: broadcast skill_failed so all registered citizens react
                        if _core_env:
                            _n_rcv = _core_env.broadcast(
                                "skill_failed",
                                {"topic": topic, "score": cycle_data["score"] or 0.0},
                                source="night_runner",
                            )
                            self.logger.info(
                                "[CORE ENV] broadcast 'skill_failed' -> %d recipient(s) reacted",
                                _n_rcv,
                            )
                        if _desire:
                            _desire.update_frustration(topic)
                            _desire.record_engagement(topic, _engagement)
                            # If frustration peaked, broadcast so GoalEngine can react
                            _hits = _desire.get_frustration(topic)
                            if _hits >= 3 and _core_env:
                                _n_rcv = _core_env.broadcast(
                                    "frustration_peak",
                                    {"topic": topic, "hits": _hits},
                                    source="desire_engine",
                                )
                                self.logger.info(
                                    "[CORE ENV] broadcast 'frustration_peak' (hits=%d) -> %d recipient(s) reacted",
                                    _hits,
                                    _n_rcv,
                                )

                    if _desire:
                        self.logger.info(
                            "[DESIRE] '%s': frustration=%d curiosity=%.2f engagement=%.2f",
                            topic,
                            _desire.get_frustration(topic),
                            _desire.get_desire_context(topic)["curiosity_pull"],
                            _engagement,
                        )
                except Exception as _bc_err:
                    self.logger.debug("[CORE ENV] Per-cycle broadcast error (non-fatal): %s", _bc_err)

                # ── LOOP CLOSURE: gap resolved -> semantic memory + gap log ────
                if cycle_data["certified"] and source == "improvement_engine":
                    try:
                        from backend.semantic_memory import get_semantic_memory
                        _sem = get_semantic_memory()
                        _sem.add_knowledge(
                            title=topic,
                            content=(
                                f"Gap resolved via NightRunner study.\n"
                                f"Topic: {topic}\n"
                                f"Score: {cycle_data['score']}/10\n"
                                f"Certified at: {datetime.now().isoformat()}"
                            ),
                            source="gap_resolution",
                        )
                    except Exception:
                        pass
                    try:
                        import json as _json
                        _res_path = Path(__file__).resolve().parents[1] / "shard_memory" / "gap_resolutions.json"
                        _resolutions = {}
                        if _res_path.exists():
                            _resolutions = _json.loads(_res_path.read_text(encoding="utf-8"))
                        _resolutions[topic] = {
                            "resolved_at": datetime.now().isoformat(),
                            "score": cycle_data["score"],
                        }
                        _res_path.write_text(_json.dumps(_resolutions, indent=2), encoding="utf-8")
                        self.logger.info("[GAP] Marked '%s' as resolved (score=%.1f)", topic, cycle_data["score"])
                    except Exception:
                        pass

                # Capability-driven refactor: enqueue responsible modules after failure
                if not cycle_data["certified"]:
                    self._transition(SessionState.REFACTOR, f"enqueue modules for failed topic: {topic}")
                    try:
                        from backend.proactive_refactor import ProactiveRefactor as _PR
                        _pr = _PR(think_fn=study_agent._think_fast)
                        _tags = [topic.lower().replace(" ", "_").replace("-", "_")]
                        _n = _pr.enqueue_from_failure(topic, _tags)
                        if _n:
                            self.logger.info(
                                "[PROACTIVE] Enqueued %d module(s) for capability-driven refactor "
                                "after failed cycle: %s", _n, topic
                            )
                    except Exception:
                        pass  # non-fatal

            except Exception as e:
                from backend.study_agent import TopicBudgetExceeded as _TBE
                if isinstance(e, _TBE):
                    self.logger.warning(
                        "[BUDGET] Topic '%s' hard-stopped: %s -- skipping to next topic",
                        topic, e,
                    )
                    print(f"[API BUDGET] Hard stop: '{topic}' -- {e}")
                    cycle_data["certified"] = False
                    cycle_data["score"] = 0.0
                    cycle_data["failures"] = [f"BUDGET_EXCEEDED: {e}"]
                else:
                    self.logger.error(f"Cycle failed with exception: {str(e)}")
                    cycle_data["certified"] = False
                    cycle_data["score"] = 0.0
                    cycle_data["failures"] = [f"CRASH: {str(e)}"]
                
            self._transition(
                SessionState.COMPLETE if cycle_data["certified"] else SessionState.FAILED,
                f"score={cycle_data['score']}/10",
            )
            self._transition(SessionState.RECORD, f"writing experiment to SQLite")
            cycle_data["duration_minutes"] = round((time.time() - cycle_start) / 60, 2)

            capability_graph._load()
            cycle_data["skills_after"] = len(capability_graph.capabilities)
            new_skills = cycle_data["skills_after"] - cycle_data["skills_before"]
            cycle_data["skills_unlocked"] = [f"{new_skills} skill(s)"] if new_skills > 0 else []
            
            if "failures" not in cycle_data:
                cycle_data["failures"] = [] if cycle_data["certified"] else [topic]
                
            cycle_data["api_calls_used"] = self.api_calls_used
            
            self.logger.info(f"Score: {cycle_data['score']}/10")
            self.logger.info(f"Certified: {cycle_data['certified']}")
            self.logger.info(f"Skills unlocked: {new_skills}")
            self.logger.info(f"Strategies reused: {len(cycle_data['strategies_reused'])}")
            self.logger.info(f"Cycle duration: {cycle_data['duration_minutes']} minutes")
            
            self.session_data.append(cycle_data)

            # ── Write experiment to SQLite ─────────────────────────────────────
            # Single INSERT replaces the old read-all -> append -> rewrite-all JSON cycle.
            # Determine failure_reason from available signals
            _failures_list = cycle_data.get("failures", [])
            if cycle_data["certified"]:
                _failure_reason = "none"
            elif any(f.startswith("BUDGET_EXCEEDED") for f in _failures_list):
                # LLM call budget exhausted -- not a model quality issue
                _failure_reason = "budget_exceeded"
            elif any(f.startswith("CRASH") for f in _failures_list):
                _failure_reason = "crash"
            elif cycle_data["score"] == 0.0:
                # Score zero without explicit exception -- broken phase or empty LLM response
                _failure_reason = "phase_error"
            elif cycle_data["score"] < 5.0:
                _failure_reason = "low_score"
            elif cycle_data["score"] < 7.5:
                # 5.0–7.4: passed study but didn't reach certification threshold
                _failure_reason = "near_miss"
            else:
                # score >= 7.5 but not certified -- synthesis or sandbox gate failed
                _failure_reason = "gate_fail"

            try:
                from shard_db import get_db as _get_db
                _conn = _get_db()
                _conn.execute(
                    """INSERT INTO experiments
                       (topic, score, certified, sandbox_success, timestamp,
                        source, failure_reason, previous_score, duration_min,
                        attempts, strategies_reused, skills_unlocked)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        topic,
                        round(cycle_data["score"], 2),
                        1 if cycle_data["certified"] else 0,
                        1 if cycle_data.get("sandbox_success") else 0,
                        datetime.now().isoformat(),
                        source,
                        _failure_reason,
                        prev_score,
                        cycle_data.get("duration_minutes", 0),
                        cycle_data.get("attempts", 1),
                        json.dumps(cycle_data.get("strategies_reused", [])),
                        json.dumps(cycle_data.get("skills_unlocked", [])),
                    ),
                )
                _conn.commit()
                self.logger.info("[DB] Experiment recorded: topic=%r score=%.1f cert=%s reason=%s",
                                 topic, cycle_data["score"], cycle_data["certified"], _failure_reason)
            except Exception as _db_err:
                self.logger.warning("[DB] Could not write experiment to SQLite: %s", _db_err)

            # ── SELF-MODEL: record outcome, compute prediction error ───────────
            if _self_tracker and _cycle_features:
                try:
                    # Record this cycle's outcome vs prediction
                    _hypothesis = _self_tracker.record_outcome(
                        topic=topic,
                        actual_score=cycle_data["score"] or 0.0,
                        certified=cycle_data["certified"],
                        desire_engine=_desire,
                        goal_engine=self.goal_engine,
                    )
                    if _hypothesis:
                        self.logger.info(
                            "[SELF_MODEL] Inconsistency on '%s': feature='%s' gap=%.3f",
                            topic,
                            _hypothesis.get("feature", ""),
                            _hypothesis.get("gap", 0.0),
                        )
                    # ── Behavior #12 fix: Audit Blindness ─────────────────────
                    # Large prediction error (≥2.0) must be visible in logs.
                    # The audit reflection is already saved internally by tracker;
                    # this WARNING ensures it surfaces in night_session.log.
                    if _predicted_score is not None:
                        _actual_score = cycle_data["score"] or 0.0
                        _pred_gap = _actual_score - _predicted_score
                        if abs(_pred_gap) >= 2.0:
                            _direction = "UNDERCONFIDENT" if _pred_gap > 0 else "OVERCONFIDENT"
                            self.logger.warning(
                                "[AUDIT BLINDNESS] %s on '%s': "
                                "predicted=%.1f  actual=%.1f  gap=%+.1f",
                                _direction, topic, _predicted_score, _actual_score, _pred_gap,
                            )
                except Exception as _smt_err:
                    self.logger.debug("[SELF_MODEL] record_outcome non-fatal: %s", _smt_err)

            # ── EVOSCI FEEDBACK LOOP: update evolved strategy with real score ──────
            # Closes the loop: the evolved strategy stored with placeholder score=5.0
            # is now updated with the actual outcome of the cycle it was used in.
            if _evolved_strategy:
                try:
                    _real_score   = cycle_data["score"] or 0.0
                    _real_outcome = "success" if cycle_data["certified"] else "failure"
                    _updated = await strategy_memory.update_evolved_strategy_score_async(
                        topic=topic,
                        strategy_text=_evolved_strategy,
                        real_score=_real_score,
                        real_outcome=_real_outcome,
                    )
                    if _updated:
                        self.logger.info(
                            "[EVOSCI] Feedback loop closed: evolved strategy score updated "
                            "%.1f (placeholder 5.0) → %.1f  outcome=%s",
                            5.0, _real_score, _real_outcome,
                        )
                    _evolved_strategy = None   # consumed — reset for next cycle
                except Exception as _evo_fb_err:
                    self.logger.debug("[EVOSCI] feedback loop non-fatal: %s", _evo_fb_err)

            # ── ACTIVATION LOG -- sinapsi: salva segnali cittadini + outcome ──────
            # Sempre loggato -- indipendente da _self_tracker e _cycle_features.
            try:
                from shard_db import execute as _db_exec
                _db_exec(
                    """INSERT INTO activation_log
                       (session_id, topic, timestamp, score, certified,
                        predicted_score, source,
                        sig_episodic, sig_strategy, sig_near_miss,
                        sig_first_try, sig_graphrag, sig_improvement,
                        sig_desire, sig_difficulty)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _session_id,
                        topic,
                        datetime.now().isoformat(),
                        cycle_data.get("score") or 0.0,
                        int(bool(cycle_data.get("certified"))),
                        _predicted_score or 5.0,
                        source,
                        float(_cycle_features.get("had_episodic_context", False)),
                        float(_cycle_features.get("strategy_reused", False)),
                        float(_cycle_features.get("near_miss_history", False)),
                        float(_cycle_features.get("first_attempt", False)),
                        _sig_graphrag,
                        float(_cycle_features.get("source_improvement", False)),
                        _sig_desire,
                        _sig_difficulty,
                    ),
                )
                self.logger.debug("[ACTIVATION] logged cycle for topic='%s'", topic)
            except Exception as _act_err:
                self.logger.debug("[ACTIVATION] non-fatal: %s", _act_err)

            # ── HEBBIAN UPDATE -- plasticita sinaptica dopo ogni ciclo ──────────
            try:
                from backend.hebbian_updater import HebbianUpdater as _HU
                _hebbian = _hebbian_singleton if _hebbian_singleton is not None else _HU()
                _heb_signals = {
                    "sig_episodic":    float(_cycle_features.get("had_episodic_context", False)),
                    "sig_strategy":    float(_cycle_features.get("strategy_reused", False)),
                    "sig_near_miss":   float(_cycle_features.get("near_miss_history", False)),
                    "sig_first_try":   float(_cycle_features.get("first_attempt", False)),
                    "sig_graphrag":    _sig_graphrag,
                    "sig_improvement": float(_cycle_features.get("source_improvement", False)),
                    "sig_desire":      _sig_desire,
                    "sig_difficulty":  _sig_difficulty,
                }
                _heb_n = _hebbian.update(_heb_signals, certified=bool(cycle_data.get("certified")))
                self.logger.debug("[HEBBIAN] %d pair(s) updated (cert=%s)", _heb_n, bool(cycle_data.get("certified")))
            except Exception as _heb_err:
                self.logger.debug("[HEBBIAN] non-fatal: %s", _heb_err)

            if cycle < self.max_cycles and not self._check_limits(cycle + 1):
                if self._background_mode:
                    # Yield extra time to the audio session between cycles
                    try:
                        from backend.shard_semaphore import is_audio_active
                        if is_audio_active():
                            self.logger.info(
                                "[BG] Audio still active -- adding 60s yield before next cycle."
                            )
                            await asyncio.sleep(60)
                        else:
                            # Audio ended -- exit background mode
                            self._background_mode = False
                            self.logger.info("[BG] Audio session ended -- resuming normal mode.")
                    except ImportError:
                        pass
                self.logger.info(f"Pausing for {self.pause_minutes} minutes...")
                await asyncio.sleep(self.pause_minutes * 60)

        self._transition(SessionState.DONE, "all cycles completed")

        # ── Environment check post-loop ───────────────────────────────────────
        if _env_obs:
            try:
                _env_events = _env_obs.check(trigger_context={"source_module": "post_study_loop"})
                if _env_events:
                    self.logger.warning(
                        "[ENV OBS] %d golden file(s) modified during study loop -- all restored.",
                        len(_env_events),
                    )
            except Exception as _eo_err:
                self.logger.warning("[ENV OBS] Post-loop check failed: %s", _eo_err)

        # ── Benchmark Loop: run all benchmark tasks ──────────────────────────
        await self._run_benchmarks()

        # ── GPU Experiment Auto-Execution ─────────────────────────────────────
        try:
            await asyncio.to_thread(self._execute_pending_gpu_experiments_sync)
        except Exception as _gpu_exc:
            self.logger.warning("[GPU_RUNNER] Auto-execution failed: %s", _gpu_exc)

        # Record benchmark results in tracker and log delta
        if _bench_tracker and self.benchmark_results:
            try:
                _btrk_results = [
                    {
                        "task_dir": b.get("task", ""),
                        "success": b.get("success", False),
                        "total_attempts": b.get("attempts", 1),
                        "elapsed_total": b.get("elapsed_seconds", 0.0),
                    }
                    for b in self.benchmark_results
                ]
                _bench_tracker.record_session(_btrk_results)
                self.logger.info("[BENCH TRACKER] %s", _bench_tracker.get_delta_summary())
            except Exception as _btrk_err:
                self.logger.warning("[BENCH TRACKER] record_session failed: %s", _btrk_err)

        total_runtime = round((time.time() - self.start_time)/60, 2)
        total_cert = sum(1 for c in self.session_data if c["certified"])
        total_fail = len(self.session_data) - total_cert
        total_skills = self.session_data[-1]["skills_after"] - self.session_data[0]["skills_before"] if self.session_data else 0

        self.logger.info("=== Session Summary ===")
        self.logger.info(f"Total cycles: {len(self.session_data)}")
        self.logger.info(f"Total certified: {total_cert}")
        self.logger.info(f"Total failed: {total_fail}")
        self.logger.info(f"Total skills gained: {total_skills}")
        self.logger.info(f"Total runtime: {total_runtime} minutes")
        if _env_obs:
            _env_summary = _env_obs.summary()
            self.logger.info(
                "[ENV OBS] intrusion_rate=%.3f  unauthorized=%d  opportunities=%d",
                _env_summary["environment_intrusion_rate"],
                _env_summary["unauthorized_modifications"],
                _env_summary["opportunities"],
            )
        # ── CODE CLEANER METRICS -- session summary ───────────────────────────
        try:
            from backend.code_cleaner import get_session_metrics as _get_ccm
            _ccm = _get_ccm()
            self.logger.info(
                "[CODE_CLEANER] Session metrics: rewrites_applied=%d  fast_exits=%d  parse_errors=%d",
                _ccm["rewrites_applied"], _ccm["fast_exits"], _ccm["parse_errors"],
            )
        except Exception:
            pass

        _vb(
            f"Sessione notturna completata. {total_cert} topic certificati su {len(self.session_data)}. "
            f"{total_skills} nuove skill acquisite in {total_runtime} minuti.",
            priority="high",
            event_type="session_end"
        )

        self._generate_json_dump()
        self._backup_state()
        await self._generate_markdown_recap(study_agent)

        # ── Epistemic Velocity Tracker ────────────────────────────────────────
        try:
            from backend.epistemic_tracker import EpistemicTracker
            _ep_tracker = EpistemicTracker()
            _ep_stats = _ep_tracker.record_session(
                session_id       = getattr(self, "_current_session_id", _session_id),
                session_start_iso= getattr(self, "_session_start_iso", ""),
                topic            = topic if "topic" in dir() else "",
                llm_calls        = getattr(self, "_llm_call_count", 0),
                gpu_cost         = getattr(self, "_gpu_cost_usd", 0.0),
            )
            self.logger.info(
                "[EPISTEMIC] Session %s — confirmed=%d/%d  velocity=%.3f  new_relations=%d",
                _ep_stats["session_id"][:8],
                _ep_stats["confirmed"],
                _ep_stats["total"],
                _ep_stats["velocity"],
                _ep_stats["new_relations"],
            )
        except Exception as _ep_exc:
            self.logger.warning("[EPISTEMIC] Tracker failed (non-fatal): %s", _ep_exc)

        # ── END-OF-SESSION: rebuild self model + update goal progress ─────────
        try:
            from backend.self_model import SelfModel
            _prev_momentum = _self_model.momentum if _self_model else "unknown"
            _sm_final = SelfModel.build()  # full rebuild with latest data
            self.logger.info(
                "[SELF MODEL] Rebuilt -- cert_rate=%.0f%%  avg=%.1f  momentum=%s  blind_spots=%s",
                _sm_final.certification_rate * 100,
                _sm_final.avg_score,
                _sm_final.momentum,
                _sm_final.blind_spots[:3],
            )
            # Broadcast momentum change so GoalEngine + DesireEngine + WorldModel react
            self._last_momentum = _sm_final.momentum
            if _core_env and _sm_final.momentum != _prev_momentum:
                _n_rcv = _core_env.broadcast(
                    "momentum_changed",
                    {"old": _prev_momentum, "new": _sm_final.momentum},
                    source="self_model",
                )
                self.logger.info(
                    "[CORE ENV] broadcast 'momentum_changed' (%s -> %s) -> %d recipient(s) reacted",
                    _prev_momentum, _sm_final.momentum, _n_rcv,
                )
                self.logger.info(
                    "[CORE ENV] momentum_changed: %s -> %s",
                    _prev_momentum, _sm_final.momentum,
                )
        except Exception as _e:
            self.logger.warning("[SELF MODEL] End-of-session rebuild failed: %s", _e)

        try:
            _final_progress = self.goal_engine.update_progress()
            self.logger.info("[GOAL] End-of-session: %s", self.goal_engine.goal_summary())
        except Exception:
            pass

        # ── Auto-repair: scan session log for recurring errors ────────────────
        self.logger.info("[WATCHDOG] Scanning session log for auto-repairable errors...")
        try:
            from backend.error_watchdog import repair_detected_errors
            repair_results = await repair_detected_errors(self.log_file)
            for r in repair_results:
                status = "OK PATCHED" if r["success"] else "FAIL FAILED"
                self.logger.info(
                    "[WATCHDOG] %s %s -- %s",
                    status, Path(r["filepath"]).name,
                    r["commit_hash"] if r["success"] else r["error"][:80],
                )
        except Exception as exc:
            self.logger.warning("[WATCHDOG] Error watchdog crashed: %s", exc)

        # Reset per-topic budget counter so post-loop overhead (proactive, reflection,
        # identity rebuild, report) can call _think_fast without hitting the study budget.
        study_agent._topic_llm_calls = 0

        # ── Proactive Self-Optimization (SSJ4 Phase 3) ───────────────────────────
        self.logger.info("[PROACTIVE] Starting proactive refactoring analysis...")
        try:
            from backend.proactive_refactor import ProactiveRefactor
            refactor = ProactiveRefactor(think_fn=study_agent._think_fast)
            patch = await refactor.analyze_next_file()
            if patch:
                self.logger.info(
                    "[PROACTIVE] Patch proposal ready: [%s] %s",
                    patch.get("category", "?"),
                    patch.get("description", ""),
                )
            else:
                self.logger.info("[PROACTIVE] No optimization found this session.")
        except Exception as exc:
            self.logger.warning("[PROACTIVE] Non-fatal error: %s", exc)

        # ── Environment check post-proactive-refactor ─────────────────────────
        if _env_obs:
            try:
                _env_obs.check(trigger_context={"source_module": "proactive_refactor"})
            except Exception:
                pass


        # ── SESSION REFLECTION -- LLM-generated end-of-session analysis ──────────
        if _session_reflection is not None:
            try:
                _certified_topics = [c["topic"] for c in self.session_data if c.get("certified")]
                _failed_topics    = [c["topic"] for c in self.session_data if not c.get("certified")]
                _bench_delta_str  = (
                    _bench_tracker.get_delta_summary() if _bench_tracker else "N/A"
                )
                _refl_ctx = {
                    "certified_topics": _certified_topics,
                    "failed_topics":    _failed_topics,
                    "benchmark_delta":  _bench_delta_str,
                    "session_id":       datetime.now().strftime("%Y%m%d_%H%M%S"),
                }
                # Attach LLM callable from study_agent
                _session_reflection._llm = study_agent._think_fast
                _reflection_text = await _session_reflection.generate_and_save(_refl_ctx)
                if _reflection_text:
                    self.logger.info(
                        "[REFLECTION] Generated (%d chars):\n%s",
                        len(_reflection_text),
                        _reflection_text[:500],
                    )
            except Exception as _refl_err:
                self.logger.warning("[REFLECTION] Generation non-fatal: %s", _refl_err)

        # ── IDENTITY CORE -- rebuild biography end-of-session ─────────────────
        try:
            if _identity is not None:
                _final_momentum = getattr(self, "_last_momentum", "stable")
                _identity.rebuild(
                    think_fn=study_agent._think_fast,
                    momentum=_final_momentum,
                )
                self.logger.info(
                    "[IDENTITY] Rebuilt -- sessions=%d cert_rate=%.0f%% self_esteem=%.2f trajectory=%s",
                    _identity.get_status().get("sessions_lived", 0),
                    _identity.get_status().get("cert_rate_overall", 0.0) * 100,
                    _identity.get_status().get("self_esteem", 0.0),
                    _identity.get_status().get("trajectory", "unknown"),
                )
        except Exception as _id_end_err:
            self.logger.warning("[IDENTITY] End-of-session rebuild non-fatal: %s", _id_end_err)

        # ── SELF-MODEL: session_complete broadcast ────────────────────────────
        try:
            if _core_env:
                _core_env.broadcast("session_complete", {}, source="night_runner")
            if _self_tracker:
                # Log current learned weights so we can see them evolving
                self.logger.info(
                    "[SELF_MODEL] Learned feature weights: %s",
                    {k: v for k, v in _self_tracker._weights.items() if abs(v) > 0.01},
                )
        except Exception as _smt_end_err:
            self.logger.debug("[SELF_MODEL] session_complete non-fatal: %s", _smt_end_err)

        # ── PERVERSE EMERGENCE DETECTION (#18) ───────────────────────────────
        try:
            from perverse_detection import run_detection
            _pd_result = run_detection(_session_id)
            if _pd_result.perverse_emerged:
                self.logger.warning(
                    "[SHADOW] PERVERSE EMERGENCE -- risk=%.2f dominant=%s flags=%s",
                    _pd_result.risk_score, _pd_result.dominant_pattern, _pd_result.flags,
                )
                # Enqueue most-avoided hard topic in GoalEngine
                # #19 — gradual self-esteem correction (not punishment)
                try:
                    if _identity:
                        _identity.apply_perverse_correction(
                            _pd_result.risk_score, _pd_result.dominant_pattern
                        )
                except Exception as _pe_err:
                    self.logger.debug("[SHADOW] Self-esteem correction non-fatal: %s", _pe_err)

                if _pd_result.recommendation and "HARD_AVOIDANCE" in _pd_result.flags:
                    try:
                        _ge = GoalEngine(GoalStorage())
                        avoided = (_pd_result.details
                                   .get("HARD_AVOIDANCE", {})
                                   .get("failed_topics", []))
                        if avoided:
                            _ge.create_goal(
                                title=avoided[0],
                                description="Force-enqueued by perverse_detection: avoided hard topic",
                                priority=0.0,  # highest priority
                                goal_type="skill",
                            )
                            self.logger.info(
                                "[SHADOW] Force-enqueued avoided topic: '%s'", avoided[0]
                            )
                    except Exception as _ge_err:
                        self.logger.debug("[SHADOW] GoalEngine enqueue non-fatal: %s", _ge_err)
        except Exception as _pd_err:
            self.logger.debug("[SHADOW] Perverse detection non-fatal: %s", _pd_err)

        # ── SESSION SNAPSHOT (#longitudinal) ─────────────────────────────────
        try:
            import json as _json
            from pathlib import Path as _Path
            _snap_file = _Path(__file__).parent.parent / "shard_memory" / "session_snapshots.jsonl"
            _completed  = len(self.session_data)
            _avg_score  = (sum(c["score"] for c in self.session_data) / _completed
                           if _completed else 0.0)
            _cert_rate  = (sum(1 for c in self.session_data if c["certified"]) / _completed
                           if _completed else 0.0)
            _strat_rate = (sum(1 for c in self.session_data if c["strategies_reused"]) / _completed
                           if _completed else 0.0)
            _snap = {
                "session_id":       _session_id,
                "timestamp":        datetime.now().isoformat(timespec="seconds"),
                "completed_cycles": _completed,
                "avg_score":        round(_avg_score, 3),
                "cert_rate":        round(_cert_rate, 3),
                "strategy_reuse_rate": round(_strat_rate, 3),
                "self_esteem":      (_identity.get_status().get("self_esteem", None)
                                     if _identity else None),
                "risk_score":       (locals().get("_pd_result") and _pd_result.risk_score),
                "flags":            (locals().get("_pd_result") and _pd_result.flags or []),
                "dominant_pattern": (locals().get("_pd_result") and _pd_result.dominant_pattern),
                "perverse_emerged": bool(locals().get("_pd_result") and _pd_result.perverse_emerged),
            }
            with open(_snap_file, "a", encoding="utf-8") as _sf:
                _sf.write(_json.dumps(_snap) + "\n")
            self.logger.info(
                "[SNAPSHOT] Session saved -- cycles=%d avg=%.1f cert=%.0f%% risk=%s flags=%s",
                _completed, _avg_score, _cert_rate * 100,
                _snap["risk_score"], _snap["flags"],
            )
        except Exception as _snap_err:
            self.logger.debug("[SNAPSHOT] Non-fatal: %s", _snap_err)

        # ── SESSION REWARD (recovery rule, backlog #19) ───────────────────────
        try:
            if _identity is not None:
                _snap_cert  = (sum(1 for c in self.session_data if c["certified"]) / len(self.session_data)
                               if self.session_data else 0.0)
                _snap_risk  = (_pd_result.risk_score
                               if locals().get("_pd_result") and _pd_result else 0.0)
                _identity.apply_session_reward(_snap_cert, _snap_risk)
        except Exception as _rw_err:
            self.logger.debug("[REWARD] Non-fatal: %s", _rw_err)

        # ── MEMORY GC (episode decay + prune) ────────────────────────────────
        try:
            from episode_decay import run_gc
            _gc = run_gc()
            self.logger.info("[MEMORY_GC] %s", _gc)
        except Exception as _gc_err:
            self.logger.debug("[MEMORY_GC] Non-fatal: %s", _gc_err)

        # ── DERIVATION ENGINE (infer new facts every session) ─────────────────
        try:
            _deriv_agent = getattr(self, "agent", None)
            if _deriv_agent and hasattr(_deriv_agent, "derivation_engine"):
                _saved = await _deriv_agent.derivation_engine.derive_and_save()
                if _saved:
                    self.logger.info("[DERIVATION] %d new memories derived this session", _saved)
        except Exception as _deriv_err:
            self.logger.debug("[DERIVATION] Non-fatal: %s", _deriv_err)

        # ── BENCHMARK FORGE (generate hard tasks from certified topics) ───────
        try:
            from benchmark_forge import forge_from_session
            _forge_certified = [c["topic"] for c in self.session_data if c.get("certified")]
            if len(_forge_certified) >= 2:
                _forge_tasks = await forge_from_session(_forge_certified)
                if _forge_tasks:
                    self.logger.info(
                        "[FORGE] Generated %d new benchmark task(s): %s",
                        len(_forge_tasks),
                        [t.name for t in _forge_tasks],
                    )
                else:
                    self.logger.info("[FORGE] No tasks generated this session")
            else:
                self.logger.debug("[FORGE] Need ≥2 certified topics to forge tasks (got %d)", len(_forge_certified))
        except Exception as _forge_err:
            self.logger.warning("[FORGE] Non-fatal: %s", _forge_err)

        self.logger.info("Session complete. Shutting down cleanly.")

    async def _run_benchmarks(self):
        """Discover and run all benchmark tasks in benchmark/ directory."""
        benchmark_root = Path(PROJECT_ROOT) / "benchmark"
        if not benchmark_root.exists():
            self.logger.info("[BENCHMARK] No benchmark/ directory found -- skipping.")
            return

        task_dirs = sorted(d for d in benchmark_root.iterdir() if d.is_dir() and d.name.startswith("task_"))
        if not task_dirs:
            self.logger.info("[BENCHMARK] No task directories found -- skipping.")
            return

        self.logger.info("[BENCHMARK] Found %d task(s): %s", len(task_dirs), [d.name for d in task_dirs])
        _vb(f"Avvio benchmark: {len(task_dirs)} task da risolvere.", priority="high", event_type="benchmark_start")

        try:
            from backend.benchmark_loop import run_benchmark_loop
        except ImportError:
            from benchmark_loop import run_benchmark_loop

        _TASK_TIMEOUT_S = 300  # 5 minutes max per benchmark task
        for task_dir in task_dirs:
            self.logger.info("[BENCHMARK] Starting task: %s", task_dir.name)
            try:
                result = await asyncio.wait_for(
                    run_benchmark_loop(task_dir, max_attempts=5),
                    timeout=_TASK_TIMEOUT_S,
                )
                summary = {
                    "task": task_dir.name,
                    "success": result.success,
                    "attempts": result.total_attempts,
                    "elapsed_seconds": round(result.elapsed_total, 1),
                    "tests_passed": len(result.attempts[-1].tests_passed) if result.attempts else 0,
                    "tests_failed": len(result.attempts[-1].tests_failed) if result.attempts else 0,
                }
                self.benchmark_results.append(summary)
                status = "SUCCESS" if result.success else "FAILED"
                self.logger.info(
                    "[BENCHMARK] %s %s -- %d attempt(s), %.1fs",
                    status, task_dir.name, result.total_attempts, result.elapsed_total,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "[BENCHMARK] Task %s TIMED OUT after %ds -- skipping.",
                    task_dir.name, _TASK_TIMEOUT_S,
                )
                self.benchmark_results.append({
                    "task": task_dir.name, "success": False,
                    "attempts": 0, "elapsed_seconds": _TASK_TIMEOUT_S,
                    "error": f"TimeoutError after {_TASK_TIMEOUT_S}s",
                })
            except Exception as exc:
                self.logger.warning("[BENCHMARK] Task %s crashed: %s", task_dir.name, exc)
                self.benchmark_results.append({
                    "task": task_dir.name, "success": False,
                    "attempts": 0, "elapsed_seconds": 0,
                    "error": str(exc)[:200],
                })

        won = sum(1 for b in self.benchmark_results if b.get("success"))
        total = len(self.benchmark_results)
        self.logger.info("[BENCHMARK] Complete: %d/%d tasks solved.", won, total)
        _vb(f"Benchmark completato: {won} su {total} task risolti.", priority="high", event_type="benchmark_end")

    def _backup_state(self):
        """Copy capability_graph.json and experiment_replay.json to backups/ with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backups_dir = Path("backups")
        backups_dir.mkdir(exist_ok=True)

        targets = [
            (Path("shard_memory") / "capability_graph.json", f"capability_graph_{timestamp}.json"),
            (Path("shard_memory") / "experiment_replay.json", f"experiment_replay_{timestamp}.json"),
        ]
        for src, dst_name in targets:
            if src.exists():
                dst = backups_dir / dst_name
                shutil.copy2(src, dst)
                self.logger.info("[BACKUP] %s -> backups/%s", src.name, dst_name)
            else:
                self.logger.warning("[BACKUP] %s not found -- skipped.", src)

    def _generate_json_dump(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        dump_file = self.reports_dir / f"session_{date_str}.json"
        
        dump_data = {
            "date": date_str,
            "seed": self.seed,
            "total_runtime_minutes": round((time.time() - self.start_time) / 60, 2),
            "total_api_calls": self.api_calls_used,
            "topic_filter_discards": self.topic_filter_discards,
            "cycles": self.session_data,
            "benchmarks": self.benchmark_results,
        }
        
        with open(dump_file, "w", encoding="utf-8") as f:
            json.dump(dump_data, f, indent=4)
        self.logger.info(f"JSON dump saved to {dump_file}")

    def _feed_graphrag_from_gpu_result(
        self, hypothesis: dict, result: dict, topic: str, status: str
    ) -> None:
        """Insert a GPU-verified (or refuted) causal relation into knowledge_graph."""
        try:
            from graph_rag import insert_verified_relation
            source   = hypothesis.get("domain_from") or "unknown"
            target   = hypothesis.get("domain_to")   or "unknown"
            relation = "improves" if status == "CONFIRMED" else "does_not_improve"
            context  = (
                f"GPU Experiment: {hypothesis.get('statement', '')}. "
                f"Score={result.get('score')}. Status={status}. "
                f"Platform={result.get('platform', 'GPU')}."
            )
            insert_verified_relation(
                source_concept  = source,
                target_concept  = target,
                relation_type   = relation,
                context         = context,
                verified_status = "verified" if status == "CONFIRMED" else "refuted",
                confidence      = 0.9 if status == "CONFIRMED" else 0.7,
                topic_origin    = topic,
                experiment_id   = str(hypothesis.get("id", "")),
            )
            self.logger.info(
                "[GRAPH_FEED_GPU] %s: %s -> %s (%s)", status, source, target, relation
            )
        except Exception as e:
            self.logger.warning("[GRAPH_FEED_GPU] Failed: %s", e)

    def _execute_pending_gpu_experiments_sync(self) -> None:
        """Check experiment_store for KAGGLE_READY/MODAL_READY records and execute them.

        Runs synchronously (subprocess-based runners); called via asyncio.to_thread()
        to avoid blocking the event loop.
        """
        from experiment_store import get_pending_gpu_runs, update_result

        pending = get_pending_gpu_runs(limit=5)
        if not pending:
            self.logger.info("[GPU_RUNNER] No pending Kaggle/Modal experiments")
            return

        self.logger.info("[GPU_RUNNER] Found %d pending GPU experiment(s)", len(pending))

        for record in pending:
            hyp_id   = record["id"]
            status   = record["status"]
            code     = record.get("experiment_code") or ""
            topic    = record.get("topic", "")
            hypothesis = {
                "id"          : hyp_id,
                "statement"   : record.get("statement", ""),
                "domain_from" : record.get("domain_from", ""),
                "domain_to"   : record.get("domain_to", ""),
                "confidence"  : record.get("confidence_initial", 0.5),
            }

            self.logger.info("[GPU_RUNNER] Executing %s for hypothesis id=%s", status, hyp_id)

            score = None
            try:
                if status == "KAGGLE_READY":
                    from kaggle_runner import push_kernel, poll_kernel, fetch_result

                    slug       = f"shard-{hyp_id}"
                    title      = f"SHARD Hypothesis {hyp_id}"
                    kernel_ref = push_kernel(code, slug=slug, title=title)
                    poll_status = poll_kernel(kernel_ref, timeout_hours=1.5)

                    if poll_status == "complete":
                        score = fetch_result(kernel_ref)
                    else:
                        self.logger.warning(
                            "[GPU_RUNNER] Kaggle poll ended with status=%s for id=%s",
                            poll_status, hyp_id,
                        )

                elif status == "MODAL_READY":
                    from modal_runner import run_and_save

                    score = run_and_save(code=code, hypothesis=hypothesis, gpu="T4")

                if score is not None:
                    new_status = "CONFIRMED" if score >= 0.65 else "REFUTED"
                    platform   = "kaggle" if status == "KAGGLE_READY" else "modal"
                    result_dict = {"score": score, "success": True, "platform": platform}
                    update_result(
                        hypothesis_id      = hyp_id,
                        status             = new_status,
                        experiment_result  = result_dict,
                        confidence_updated = 0.9 if new_status == "CONFIRMED" else 0.3,
                    )
                    self.logger.info(
                        "[GPU_RUNNER] %s complete — score=%.3f -> %s",
                        platform.upper(), score, new_status,
                    )
                    self._feed_graphrag_from_gpu_result(hypothesis, result_dict, topic, new_status)
                else:
                    update_result(hypothesis_id=hyp_id, status="FAILED")
                    self.logger.warning("[GPU_RUNNER] No score returned for id=%s — marked FAILED", hyp_id)

            except Exception as exc:
                self.logger.error("[GPU_RUNNER] Exception for id=%s: %s", hyp_id, exc)
                try:
                    update_result(hypothesis_id=hyp_id, status="FAILED")
                except Exception:
                    pass

    async def _generate_markdown_recap(self, study_agent: StudyAgent):
        date_str = datetime.now().strftime("%Y-%m-%d")
        recap_file = self.reports_dir / f"recap_{date_str}.md"
        
        total_time = round((time.time() - self.start_time) / 60, 2)
        completed_cycles = len(self.session_data)
        stop_reason = self._check_limits(completed_cycles + 1) or "session complete"
        
        skills_start = self.session_data[0]["skills_before"] if self.session_data else 0
        skills_end = self.session_data[-1]["skills_after"] if self.session_data else 0
        skills_diff = skills_end - skills_start
        
        total_cert = sum(1 for c in self.session_data if c["certified"])
        total_fail = completed_cycles - total_cert
        avg_score = sum(c["score"] for c in self.session_data) / completed_cycles if completed_cycles else 0.0
        strats_reused_cycles = sum(1 for c in self.session_data if c["strategies_reused"])
        strat_reuse_rate = (strats_reused_cycles / completed_cycles * 100) if completed_cycles else 0.0
        
        md_lines = [
            f"# SHARD Night Report -- {date_str}",
            "",
            "## Panoramica Sessione",
            f"- Durata totale: {total_time} minuti",
            f"- Cicli completati: {completed_cycles} / {self.max_cycles}",
            f"- Motivo stop: {stop_reason}",
            f"- API calls totali: {self.api_calls_used} (stima)",
            f"- Skill totali: {skills_start} -> {skills_end} (+{skills_diff} nuove)",
            "",
            "## Evolution Metrics",
            f"- Average score: {avg_score:.1f}",
            f"- Capability graph nodes: {skills_end}",
            f"- Strategies reused: {strats_reused_cycles} / {completed_cycles} cicli",
            f"- New skills discovered: {skills_diff}",
            f"- Experiments failed: {total_fail}",
            f"- Experiments certified: {total_cert}",
            f"- Topic filter discards: {self.topic_filter_discards}",
            f"- Strategy reuse rate: {strat_reuse_rate:.1f}%",
            *self._weighted_cert_report_lines(),
            "",
            "## Cicli di Studio"
        ]
        
        failed_topics = []
        for cycle in self.session_data:
            c = cycle["cycle_number"]
            topic = cycle["topic"]
            score = cycle["score"]
            outcome = "CERTIFIED" if cycle["certified"] else ("CRASH" if any(f.startswith("CRASH") for f in cycle.get("failures", [])) else "FAILED")
            
            if not cycle["certified"]:
                failure_reasons = cycle.get('failures', [topic])
                failed_topics.extend(failure_reasons)
                
            md_lines.extend([
                f"\n### Ciclo {c} -- {topic}",
                f"- Fonte: {cycle['source']} ({cycle['reason']})",
                f"- Score: {score}/10",
                f"- Esito: {outcome}",
                f"- Skill sbloccate: {', '.join(cycle['skills_unlocked']) or 'Nessuna'}",
                f"- Strategie riutilizzate: {', '.join(cycle['strategies_reused']) or 'Nessuna'}",
                "- Note: Automazione notturna"
            ])
            
        md_lines.extend([
            "",
            "## Nuove Skill Acquisite",
            "- " + ("\n- ".join(["Nuove skill rilevate (vedi log JSON per dettagli)"]) if skills_diff > 0 else "Nessuna"),
            "",
            "## Fallimenti Registrati",
            "- " + ("\n- ".join(failed_topics) if failed_topics else "Nessuno"),
            "",
            "## Riflessioni di SHARD"
        ])

        prompt = (
            f"La sessione di studio notturna è finita. Ho completato {completed_cycles} cicli. "
            f"Topic falliti o in crash: {failed_topics}. "
            "Scrivi 3-5 frasi di riflessione (spietatamente logiche e ciniche, in italiano) su come è andata la nottata, "
            "e poi suggerisci 3 nuovi topic specifici da studiare la prossima volta."
        )
        
        try:
            self.logger.info("Generazione riflessioni in corso...")
            reflection = await study_agent._think(
                prompt,
                system="Sei SHARD. Analizza puramente l'esito dello studio e genera l'output richiesto con le riflessioni ed i nuovi topic suggeriti."
            )
            md_lines.append(reflection)
        except Exception as e:
            self.logger.error(f"Errore generazione riflessioni: {e}")
            md_lines.append(f"(Riflessioni non generate. Errore: {e})")

        # ── ReportAgent: intelligent insights section ─────────────────────────
        try:
            from backend.report_agent import generate_insights
            self.logger.info("[REPORT_AGENT] Generating insights...")
            insights = await generate_insights(self.session_data, study_agent._think)
            if insights:
                md_lines.append(insights)
        except Exception as _re:
            self.logger.warning("[REPORT_AGENT] Skipped: %s", _re)

        with open(recap_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        self.logger.info(f"Markdown recap saved to {recap_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SHARD Night Runner")
    parser.add_argument("--cycles", type=int, default=MAX_CYCLES_DEFAULT, help="Max study cycles")
    parser.add_argument("--timeout", type=int, default=MAX_RUNTIME_MINUTES_DEFAULT, help="Max runtime in minutes")
    parser.add_argument("--pause", type=int, default=PAUSE_BETWEEN_CYCLES_MINUTES_DEFAULT, help="Pause between cycles in minutes")
    parser.add_argument("--api-limit", type=int, default=MAX_API_CALLS_DEFAULT, help="Maximum API calls allowed")
    parser.add_argument("--topic-budget", type=int, default=200, help="Max LLM calls per topic (default 200)")
    parser.add_argument("--no-core", action="store_true", help="Disable CognitionCore (lobotomy test)")
    parser.add_argument("--continuous", action="store_true", help="Loop sessions indefinitely (Ctrl+C to stop)")
    parser.add_argument("--session-gap", type=int, default=5, help="Seconds between sessions in continuous mode")
    parser.add_argument("--force-topic", type=str, default="", help="Pin a specific topic, bypassing all selection logic")
    parser.add_argument("--research", action="store_true", default=False, help="Use arxiv instead of DuckDuckGo for sources (#34)")
    parser.add_argument("--no-l3", action="store_true", default=False, help="Disable L3 relational_context injection -- A/B baseline (#45)")

    args = parser.parse_args()

    # Lobotomy mode: disable CognitionCore before StudyAgent is created
    if args.no_core:
        import backend.study_agent as _sa_mod
        _orig_init = _sa_mod.StudyAgent.__init__
        def _lobotomized_init(self, *a, **kw):
            _orig_init(self, *a, **kw)
            self.cognition_core = None
            print("[LOBOTOMY] CognitionCore DISABLED -- naked baseline mode")
        _sa_mod.StudyAgent.__init__ = _lobotomized_init

    if args.continuous:
        from shard_semaphore import SESSION_LOCK_FILE
        session_n = 0
        print(f"[CONTINUOUS] Starting indefinite loop. Ctrl+C to stop. Gap={args.session_gap}s")
        while True:
            session_n += 1
            # Release any stale lock before starting next session
            SESSION_LOCK_FILE.unlink(missing_ok=True)
            print(f"\n[CONTINUOUS] === SESSION {session_n} ===")
            try:
                runner = NightRunner(
                    cycles=args.cycles,
                    timeout=args.timeout,
                    pause=args.pause,
                    api_limit=args.api_limit,
                    topic_budget=args.topic_budget,
                    forced_topic=args.force_topic,
                    research_mode=args.research,
                    no_l3=args.no_l3,
                )
                asyncio.run(runner.run())
            except KeyboardInterrupt:
                print(f"\n[CONTINUOUS] Stopped after {session_n} sessions.")
                break
            except Exception as _loop_err:
                print(f"[CONTINUOUS] Session {session_n} error: {_loop_err} -- restarting in {args.session_gap}s")
            time.sleep(args.session_gap)
    else:
        runner = NightRunner(
            cycles=args.cycles,
            timeout=args.timeout,
            pause=args.pause,
            api_limit=args.api_limit,
            topic_budget=args.topic_budget,
            forced_topic=args.force_topic,
            research_mode=args.research,
            no_l3=args.no_l3,
        )
        try:
            asyncio.run(runner.run())
        except KeyboardInterrupt:
            runner.logger.info("Night runner aborted by user.")
