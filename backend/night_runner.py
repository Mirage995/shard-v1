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
MAX_API_CALLS_DEFAULT = 50
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

    # Reject markdown headers (e.g. "# Task 03 — Optimize the Transaction Processor")
    if topic.strip().startswith("#"):
        logger.info(f"[TOPIC FILTER] Discarded markdown header topic: {topic}")
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
        logger.info(f"[TOPIC FILTER] Discarded invalid topic: {topic} — Reason: matched blacklist pattern")
        return False
        
    avg_len = sum(len(w) for w in words) / len(words)
    if avg_len < 3:
        logger.info(f"[TOPIC FILTER] Discarded invalid topic: {topic} — Reason: average word length < 3")
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
    COMPLETE = auto()  # cycle certified — moving to next cycle
    FAILED   = auto()  # cycle not certified — moving to next cycle
    DONE     = auto()  # session finished (limit reached or all cycles done)


class NightRunner:
    def __init__(self, cycles: int, timeout: int, pause: int, api_limit: int, topic_budget: int = 50):
        self.max_cycles = cycles
        self.max_runtime_minutes = timeout
        self.goal_engine = None
        self.pause_minutes = pause
        self.max_api_calls = api_limit
        self.topic_budget = topic_budget

        self.start_time = None
        self.api_calls_used = 0
        self.session_data = []
        self.benchmark_results = []
        self.seed = random.randint(0, 10_000_000)
        random.seed(self.seed)
        # Priority -1: topics queued by ImprovementEngine (SSJ3 proactive self-improvement)
        self._background_mode: bool = False  # True when running alongside an audio session
        self._improvement_topics: list = []
        self._state: SessionState = SessionState.INIT

        self.topic_filter_discards = 0
        self._desire_selections_this_session = 0  # cap: max 1 desire topic per session

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

    def _transition(self, new_state: SessionState, detail: str = "") -> None:
        """Log a state transition and update _state."""
        old = self._state.name
        self._state = new_state
        msg = f"[STATE] {old} → {new_state.name}"
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
        """Fix C: True if this topic has 3+ hard failures (max score < 6.0).

        Near-misses (score >= 6.0) are NOT quarantined — they should be retried
        with score context (Fix B).  Only truly hopeless topics get blocked.
        Uses SQLite VIEW quarantined_topics, fallback to JSON.
        """
        try:
            from shard_db import get_db
            conn = get_db()
            row = conn.execute(
                "SELECT topic FROM quarantined_topics WHERE topic = ?",
                (topic.lower().strip(),)
            ).fetchone()
            if row:
                self.logger.info("[DB] Topic quarantined (SQLite VIEW): %r", topic)
            return row is not None
        except Exception:
            return False

    def _is_avoided(self, topic: str) -> bool:
        """True if topic matches an avoid_domain from VisionEngine (chronic failures)."""
        ve = getattr(self, "_vision_engine", None)
        if ve is None:
            return False
        topic_l = topic.lower().strip()
        return any(topic_l == a.lower().strip() or a.lower().strip() in topic_l for a in ve.avoid_domains)

    async def _select_topic(self, capability_graph, config_context) -> tuple[str, str, str]:
        """Returns (topic, source, reason)"""

        # Priority -1: ImprovementEngine queue (SSJ3 proactive self-improvement)
        # Fix A: validate every improvement topic — SSJ3 can re-inject garbage topics
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
                self.logger.info("[VISION] Improvement topic in avoid_domains — skipping: %r", topic)
                continue
            self.logger.info("[SSJ3] Improvement topic dequeued: %r", topic)
            return topic, "improvement_engine", "Proactive improvement ticket (SSJ3)"

        # Priority 0: Phoenix Protocol — replays near-miss topics (score 6.0–7.4).
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
                    self.logger.info(f"[PHOENIX] Candidate '{topic}' is quarantined/avoided — skipping.")
                else:
                    self.logger.info(f"[PHOENIX] Replay candidate found: '{topic}' (previous score: {past_score})")
                    return topic, "failure_replay", f"Phoenix replay: score precedente {past_score}|prev_score={past_score}"
            else:
                 self.logger.info("[PHOENIX] No valid candidates found. Falling back to normal selection.")

        # Priority 0.5: Desire engine — high-frustration or high-curiosity topics
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
                    return _dt, "curiosity_driven", f"Lateral curiosity — adjacent to recent cert (pull={_dc['curiosity_pull']:.2f})"
                # Frustration drive: pick frustrated topic 40% of the time
                if _dc["frustration_hits"] >= 2 and random.random() < 0.40:
                    self.logger.info(
                        "[DESIRE] Frustration drive: '%s' (hits=%d score=%.2f)",
                        _dt, _dc["frustration_hits"], _dc["desire_score"],
                    )
                    self._desire_selections_this_session += 1
                    return _dt, "frustration_driven", f"Frustration drive — {_dc['frustration_hits']} prior blocks (desire={_dc['desire_score']:.2f})"
        except Exception as _de_sel_err:
            self.logger.debug("[DESIRE] Topic selection non-fatal: %s", _de_sel_err)

        # Priority 0.5: Curriculum suggestion — topics that extend certified skills
        try:
            from backend.skill_library import suggest_curriculum_topics as _suggest_curr
            _cert_set = set(capability_graph.capabilities.keys())
            _pool_file = Path(__file__).resolve().parents[1] / "shard_memory" / "curated_topics.txt"
            _pool = [l.strip() for l in _pool_file.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.startswith("#")] if _pool_file.exists() else []
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

        # Priority 1: Curated topics list (primary source — replaces ExperimentInventor)
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

        sources = ["research_agenda"]  # consciousness removed — generates garbage from Italian thoughts; ExperimentInventor disabled

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
        
        # TASK 5: Capability recombination DISABLED — generates nonsense composite topics
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
                self.logger.info(f"[QUARANTINE] Skipping '{topic}' — 3+ hard failures, max score < 6.0")
                self.topic_filter_discards += 1
                continue
            if self._is_avoided(topic):
                self.logger.info(f"[VISION] Skipping '{topic}' — in avoid_domains (chronic failure)")
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
                _candidates = [t for t in _curated if t.lower() not in _certified]
                if _candidates:
                    return random.choice(_candidates), "curated_list", "Fallback (curated list)"
            except Exception:
                pass

        return "Python Advanced Error Handling", "fallback", "Hardcoded ultimate fallback"

    async def run(self):
        self.start_time = time.time()
        self.logger.info("Session started")
        _vb(f"Sessione notturna avviata. Studio autonomo in corso per un massimo di {self.max_cycles} cicli.", priority="medium", event_type="session_start")

        # ── Dual-layer session lock ──────────────────────────────────────────
        # In-process:   asyncio.Semaphore(1) blocks if server holds the lock
        # Cross-process: file lock blocks if an audio session is live
        #
        # Background mode: if audio is active, NightRunner runs silently
        # alongside it instead of aborting — voice events are suppressed and
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
                        "[LOCK] Audio session active — NightRunner starting in silent background mode."
                    )
                    # Do not acquire semaphore or overwrite audio lock file
                else:
                    self.logger.warning(
                        "[LOCK] Session locked by '%s' — NightRunner will not start.",
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
        except ImportError:
            self.logger.warning("[LOCK] shard_semaphore not available — running without session lock.")

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
        """Core study loop — called by run() inside the session lock guard."""
        # In background mode (audio session active) suppress all voice broadcasts
        # Always assign _vb as a local to avoid UnboundLocalError from Python scoping rules
        _module_vb = globals()["_vb"]
        _vb = (lambda text, priority="low", event_type="info": None) if self._background_mode else _module_vb  # noqa: F841
        self._transition(SessionState.INIT, "loading memory + capability graph")
        import uuid as _uuid
        _session_id = str(_uuid.uuid4())
        self.logger.info("[SESSION] id=%s", _session_id)
        memory = ShardMemory()
        capability_graph = CapabilityGraph()
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
        # pursue this session — no human input required.
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
                self.logger.info("[GOAL AUTO] No goal generated — no world model gaps found")
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
                self.logger.info("[SEMANTIC] ChromaDB sparse — running index_all()")
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

        # ── COGNITIONCORE ENVIRONMENT — register all modules ──────────────────
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

        # ── SESSION REFLECTION — inject past context ───────────────────────────
        try:
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
                    "[REFLECTION] Past context loaded (%d chars) — injecting into study_agent system prompt.",
                    len(_full_context),
                )
                study_agent.session_context = _full_context
            else:
                self.logger.info("[REFLECTION] No past context — first session.")
        except Exception as _sr_err:
            self.logger.warning("[REFLECTION] non-fatal: %s", _sr_err)

        # ── HEBBIAN UPDATER — register as CognitionCore citizen ─────────────
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

        # ── SKILL LIBRARY — load Voyager-style skill cache ───────────────────
        try:
            from backend.skill_library import SkillLibrary as _SL
            _skill_lib = _SL()
            if _core_env:
                _core_env.register("skill_library", _skill_lib, ["skill_certified"])
            _sl_stats = _skill_lib.get_stats()
            self.logger.info(
                "[SKILL_LIB] Loaded — %d certified skills (avg=%.1f)",
                _sl_stats["total_skills"], _sl_stats["avg_score"],
            )
        except Exception as _sl_err:
            self.logger.warning("[SKILL_LIB] Init non-fatal: %s", _sl_err)

        # ── IDENTITY CORE — inject persistent biography ───────────────────────
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
                _base_ctx = study_agent.session_context or ""
                study_agent.session_context = "\n\n".join(b for b in [_id_block, _base_ctx] if b)
                self.logger.info(
                    "[IDENTITY] Biography injected (%d chars) — sessions=%d self_esteem=%.2f trajectory=%s",
                    len(_id_block),
                    _identity.get_status().get("sessions_lived", 0),
                    _identity.get_status().get("self_esteem", 0.0),
                    _identity.get_status().get("trajectory", "unknown"),
                )
            else:
                self.logger.info("[IDENTITY] No biography yet — first session.")
        except Exception as _id_init_err:
            self.logger.warning("[IDENTITY] Init non-fatal: %s", _id_init_err)

        # ── BENCHMARK TRACKER — log delta from previous session ───────────────
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
                # Reload improvement queue — now includes both SSJ3 + gap topics
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

            # ── PREREQUISITE GATE — se il topic è difficile, studia prima i prereq ──
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
                        )
                    ]
                    if _safe_prereqs:
                        _prereq_topic = _safe_prereqs[0]
                        self.logger.info(
                            "[PREREQ] '%s' (difficulty=%.2f) needs '%s' first — redirecting",
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
                            "[PREREQ] All prereqs for '%s' are quarantined/invalid — proceeding as-is",
                            _original_topic,
                        )
            except Exception as _prereq_err:
                self.logger.debug("[PREREQ] non-fatal: %s", _prereq_err)

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
            
            strategy_memory = StrategyMemory()
            strategies = strategy_memory.query(topic, k=1)
            if strategies:
                strat_name = strategies[0]["topic"]
                self.logger.info(f"[STRATEGY] Reusing strategy: {strat_name} for topic: {topic}")
                cycle_data["strategies_reused"].append(strat_name)
            else:
                self.logger.info(f"[STRATEGY] No existing strategy found for: {topic}")

            # ── SELF-MODEL: predict score before studying ─────────────────────
            # Features are observable facts about this cycle — not invented.
            # sig_* are citizen signals (0.0-1.0) for activation_log / synaptic weights.
            _sig_desire     = 0.0
            _sig_difficulty = 0.5
            _sig_graphrag   = 0.0

            # sig_desire — desire_score composito (frustration + curiosity + engagement)
            try:
                from backend.desire_engine import get_desire_engine as _get_de_sig
                _de_sig = _get_de_sig()
                _desire_ctx = _de_sig.get_desire_context(topic)
                _sig_desire = round(float(_desire_ctx.get("desire_score", 0.0)), 4)
            except Exception:
                pass

            # sig_difficulty — 1 - cert_rate storica (topic mai visto = 0.5 neutro)
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

                    # sig_graphrag — conteggio reale relazioni causali nel knowledge graph
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
                        # Continuous signals — feed into predictive processing loop
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

            async def on_certify(t, s, e_data):
                cycle_data["certified"] = True
                cycle_data["score"] = s
                _vb(f"Topic certificato: {t}. Score: {s} su dieci.", priority="low", event_type="cycle_certified")
                
            # Fix B: extract previous_score from Phoenix replay reason tag
            prev_score = None
            if source == "failure_replay" and "|prev_score=" in reason:
                try:
                    prev_score = float(reason.split("|prev_score=")[1])
                    self.logger.info(f"[PHOENIX] Injecting previous_score={prev_score} into study pipeline")
                except (ValueError, IndexError):
                    pass

            # Dynamic persona selection — picks best study strategy for this topic/category
            persona_cfg = select_persona(topic, category=cycle_data.get("source"))
            self.logger.info(
                "[PERSONA] Selected '%s' (tier=%d) for: %s",
                persona_cfg.persona.value, persona_cfg.tier, topic,
            )

            try:
                self._transition(SessionState.STUDY, topic)
                self.api_calls_used += 3

                # ── SKILL LIBRARY INJECTION — past certified solutions ────────
                _sl_injected = False
                if _skill_lib is not None:
                    try:
                        _sl_block = _skill_lib.get_injection_block(topic, capability_graph)
                        if _sl_block:
                            _base_ctx = study_agent.session_context or ""
                            study_agent.session_context = "\n\n".join(b for b in [_sl_block, _base_ctx] if b)
                            _sl_injected = True
                            self.logger.info("[SKILL_LIB] Injected %d chars for topic '%s'", len(_sl_block), topic)
                    except Exception as _sl_inj_err:
                        self.logger.debug("[SKILL_LIB] inject non-fatal: %s", _sl_inj_err)

                # ── MOOD INJECTION — stato affettivo → prompt di studio ────────
                if _mood:
                    try:
                        _mood.compute(desire_engine=_desire, momentum=getattr(self, "_last_momentum", "stable"))
                        _mood_hint = _mood.get_prompt_hint()
                        _mood_label = _mood.get_label()
                        # Prepend mood hint to session_context (non-destructive)
                        _base_ctx = study_agent.session_context or ""
                        study_agent.session_context = (
                            f"[AFFECTIVE STATE: {_mood_label.upper()}] {_mood_hint}\n\n{_base_ctx}"
                        ).strip()
                        self.logger.info("[MOOD] Injected into study prompt: %s (%.3f)", _mood_label, _mood.get_score())
                    except Exception as _mi_err:
                        self.logger.debug("[MOOD] inject non-fatal: %s", _mi_err)

                best_score = await study_agent.study_topic(
                    topic=topic,
                    tier=persona_cfg.tier,
                    on_certify=on_certify,
                    previous_score=prev_score,
                )

                # Restore session_context — strip mood and skill lib prefixes
                _ctx = study_agent.session_context or ""
                if _mood and "[AFFECTIVE STATE:" in _ctx:
                    _ctx = "\n\n".join(
                        p for p in _ctx.split("\n\n")
                        if not p.startswith("[AFFECTIVE STATE:")
                    ).strip()
                if _sl_injected and "=== SHARD SKILL LIBRARY" in _ctx:
                    _ctx = "\n\n".join(
                        p for p in _ctx.split("\n\n")
                        if not p.startswith("=== SHARD SKILL LIBRARY")
                    ).strip()
                study_agent.session_context = _ctx
                if not cycle_data["certified"] and best_score:
                    cycle_data["score"] = best_score
                    _vb(f"Topic fallito: {topic}. Miglior score raggiunto: {round(best_score, 2)} su dieci.", priority="medium", event_type="cycle_failed")
                self.logger.info(f"Sandbox/Study result: {'success' if cycle_data['certified'] else 'failed'}")

                # Record outcome for meta-learning persona improvement
                record_outcome(
                    topic=topic,
                    category=cycle_data.get("source"),
                    persona=persona_cfg.persona,
                    certified=cycle_data["certified"],
                    score=cycle_data["score"] or 0.0,
                )

                # ── ENVIRONMENT BROADCAST — modules react autonomously ─────
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
                            except Exception as _sl_save_err:
                                self.logger.debug("[SKILL_LIB] save non-fatal: %s", _sl_save_err)

                        # Broadcast: skill certified → all registered modules react
                        if _core_env:
                            _n_rcv = _core_env.broadcast(
                                "skill_certified",
                                {"topic": topic, "score": cycle_data["score"] or 7.5},
                                source="night_runner",
                            )
                            self.logger.info(
                                "[CORE ENV] broadcast 'skill_certified' → %d recipient(s) reacted",
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
                                "[CORE ENV] broadcast 'skill_failed' → %d recipient(s) reacted",
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
                                    "[CORE ENV] broadcast 'frustration_peak' (hits=%d) → %d recipient(s) reacted",
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

                # ── LOOP CLOSURE: gap resolved → semantic memory + gap log ────
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
                        "[BUDGET] Topic '%s' hard-stopped: %s — skipping to next topic",
                        topic, e,
                    )
                    print(f"[API BUDGET] Hard stop: '{topic}' — {e}")
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
            # Single INSERT replaces the old read-all → append → rewrite-all JSON cycle.
            # Determine failure_reason from available signals
            _failures_list = cycle_data.get("failures", [])
            if cycle_data["certified"]:
                _failure_reason = "none"
            elif any(f.startswith("BUDGET_EXCEEDED") for f in _failures_list):
                # LLM call budget exhausted — not a model quality issue
                _failure_reason = "budget_exceeded"
            elif any(f.startswith("CRASH") for f in _failures_list):
                _failure_reason = "crash"
            elif cycle_data["score"] == 0.0:
                # Score zero without explicit exception — broken phase or empty LLM response
                _failure_reason = "phase_error"
            elif cycle_data["score"] < 5.0:
                _failure_reason = "low_score"
            elif cycle_data["score"] < 7.5:
                # 5.0–7.4: passed study but didn't reach certification threshold
                _failure_reason = "near_miss"
            else:
                # score >= 7.5 but not certified — synthesis or sandbox gate failed
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
                except Exception as _smt_err:
                    self.logger.debug("[SELF_MODEL] record_outcome non-fatal: %s", _smt_err)

            # ── ACTIVATION LOG — sinapsi: salva segnali cittadini + outcome ──────
            # Sempre loggato — indipendente da _self_tracker e _cycle_features.
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

            # ── HEBBIAN UPDATE — plasticita sinaptica dopo ogni ciclo ──────────
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
                                "[BG] Audio still active — adding 60s yield before next cycle."
                            )
                            await asyncio.sleep(60)
                        else:
                            # Audio ended — exit background mode
                            self._background_mode = False
                            self.logger.info("[BG] Audio session ended — resuming normal mode.")
                    except ImportError:
                        pass
                self.logger.info(f"Pausing for {self.pause_minutes} minutes...")
                await asyncio.sleep(self.pause_minutes * 60)

        self._transition(SessionState.DONE, "all cycles completed")

        # ── Benchmark Loop: run all benchmark tasks ──────────────────────────
        await self._run_benchmarks()

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
        _vb(
            f"Sessione notturna completata. {total_cert} topic certificati su {len(self.session_data)}. "
            f"{total_skills} nuove skill acquisite in {total_runtime} minuti.",
            priority="high",
            event_type="session_end"
        )

        self._generate_json_dump()
        self._backup_state()
        await self._generate_markdown_recap(study_agent)

        # ── END-OF-SESSION: rebuild self model + update goal progress ─────────
        try:
            from backend.self_model import SelfModel
            _prev_momentum = _self_model.momentum if _self_model else "unknown"
            _sm_final = SelfModel.build()  # full rebuild with latest data
            self.logger.info(
                "[SELF MODEL] Rebuilt — cert_rate=%.0f%%  avg=%.1f  momentum=%s  blind_spots=%s",
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
                    "[CORE ENV] broadcast 'momentum_changed' (%s → %s) → %d recipient(s) reacted",
                    _prev_momentum, _sm_final.momentum, _n_rcv,
                )
                self.logger.info(
                    "[CORE ENV] momentum_changed: %s → %s",
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
                status = "✓ PATCHED" if r["success"] else "✗ FAILED"
                self.logger.info(
                    "[WATCHDOG] %s %s — %s",
                    status, Path(r["filepath"]).name,
                    r["commit_hash"] if r["success"] else r["error"][:80],
                )
        except Exception as exc:
            self.logger.warning("[WATCHDOG] Error watchdog crashed: %s", exc)

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

        # ── SESSION REFLECTION — LLM-generated end-of-session analysis ──────────
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

        # ── IDENTITY CORE — rebuild biography end-of-session ─────────────────
        try:
            if _identity is not None:
                _final_momentum = getattr(self, "_last_momentum", "stable")
                _identity.rebuild(
                    think_fn=study_agent._think_fast,
                    momentum=_final_momentum,
                )
                self.logger.info(
                    "[IDENTITY] Rebuilt — sessions=%d cert_rate=%.0f%% self_esteem=%.2f trajectory=%s",
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

        self.logger.info("Session complete. Shutting down cleanly.")

    async def _run_benchmarks(self):
        """Discover and run all benchmark tasks in benchmark/ directory."""
        benchmark_root = Path(PROJECT_ROOT) / "benchmark"
        if not benchmark_root.exists():
            self.logger.info("[BENCHMARK] No benchmark/ directory found — skipping.")
            return

        task_dirs = sorted(d for d in benchmark_root.iterdir() if d.is_dir() and d.name.startswith("task_"))
        if not task_dirs:
            self.logger.info("[BENCHMARK] No task directories found — skipping.")
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
                    "[BENCHMARK] %s %s — %d attempt(s), %.1fs",
                    status, task_dir.name, result.total_attempts, result.elapsed_total,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "[BENCHMARK] Task %s TIMED OUT after %ds — skipping.",
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
                self.logger.info("[BACKUP] %s → backups/%s", src.name, dst_name)
            else:
                self.logger.warning("[BACKUP] %s not found — skipped.", src)

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
            f"# SHARD Night Report — {date_str}",
            "",
            "## Panoramica Sessione",
            f"- Durata totale: {total_time} minuti",
            f"- Cicli completati: {completed_cycles} / {self.max_cycles}",
            f"- Motivo stop: {stop_reason}",
            f"- API calls totali: {self.api_calls_used} (stima)",
            f"- Skill totali: {skills_start} → {skills_end} (+{skills_diff} nuove)",
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
                f"\n### Ciclo {c} — {topic}",
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
    parser.add_argument("--topic-budget", type=int, default=50, help="Max LLM calls per topic (default 50)")
    parser.add_argument("--no-core", action="store_true", help="Disable CognitionCore (lobotomy test)")

    args = parser.parse_args()

    # Lobotomy mode: disable CognitionCore before StudyAgent is created
    if args.no_core:
        import backend.study_agent as _sa_mod
        _orig_init = _sa_mod.StudyAgent.__init__
        def _lobotomized_init(self, *a, **kw):
            _orig_init(self, *a, **kw)
            self.cognition_core = None
            print("[LOBOTOMY] CognitionCore DISABLED — naked baseline mode")
        _sa_mod.StudyAgent.__init__ = _lobotomized_init

    runner = NightRunner(
        cycles=args.cycles,
        timeout=args.timeout,
        pause=args.pause,
        api_limit=args.api_limit,
        topic_budget=args.topic_budget,
    )
    
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        runner.logger.info("Night runner aborted by user.")
