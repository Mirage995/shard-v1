"""Meta Learning -- SHARD learns HOW to learn.

Observes outcomes across study sessions and builds a statistical model
of what approaches work best for which categories of topics.

Storage: shard_memory/shard.db (experiments table + category_stats/global_stats views).
Fallback: reads legacy meta_learning.json if DB is unavailable.

Core responsibilities:
  - suggest_best_strategy(topic): surface the historically best approach
    for this type of topic before the study pipeline starts
  - update(topic, score, ...): record the outcome of a completed cycle
    (inserts into experiments table; stats are computed live by SQL views)
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("shard.meta_learning")

META_DB_PATH: Path = Path(__file__).parent.parent / "shard_memory" / "meta_learning.json"


def _get_db():
    """Lazy import to avoid circular deps."""
    from shard_db import get_db
    return get_db()

# ── Topic keyword classifier ──────────────────────────────────────────────────
# Maps a category name to a list of substrings that indicate the topic belongs
# to that category.  First match wins (order matters for ambiguous topics).
TOPIC_CATEGORIES: Dict[str, List[str]] = {
    "algorithms":       ["algorithm", "sort", "search", "graph", "tree",
                         "dynamic programming", "pathfinding", "recursion",
                         "greedy", "divide", "backtrack", "bfs", "dfs", "topological"],
    "data_structures":  ["linked list", "queue", "stack", "hash", "heap",
                         "trie", "deque", "binary tree", "red-black", "segment tree"],
    "concurrency":      ["async", "thread", "lock", "semaphore", "concurrent",
                         "parallel", "coroutine", "event loop", "asyncio",
                         "race condition", "deadlock", "mutex"],
    "machine_learning": ["neural", "machine learning", "deep learning",
                         "classifier", "regression", "cluster", "perceptron",
                         "gradient", "backpropagation", "training", "inference",
                         "transformer", "attention"],
    "systems":          ["filesystem", "process", "virtual memory", "page",
                         "kernel", "syscall", "buffer", "ipc", "pipe", "signal"],
    "web":              ["http", "rest api", "websocket", "tcp", "udp",
                         "client-server", "request", "response", "endpoint"],
    "math":             ["matrix", "vector", "optimization", "probability",
                         "statistics", "linear algebra", "calculus",
                         "fourier", "polynomial", "prime"],
    "oop":              ["class", "inheritance", "polymorphism", "design pattern",
                         "interface", "abstract", "decorator", "factory",
                         "singleton", "observer", "solid"],
    "parsing":          ["parser", "lexer", "tokenizer", "ast", "grammar",
                         "regex", "compiler", "interpreter", "json", "xml"],
}

# Rolling window for trend computation: last N sessions
HISTORY_WINDOW: int = 20


def _classify_topic(topic: str) -> str:
    """Return the best-fit category for a topic string."""
    t = topic.lower()
    for category, keywords in TOPIC_CATEGORIES.items():
        if any(kw in t for kw in keywords):
            return category
    return "general"


def _linear_trend(values: List[float]) -> float:
    """Compute the slope of a best-fit line through the score history.

    Positive  -> scores are improving over time.
    Negative  -> scores are declining.
    Near zero -> stable.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return round(num / den, 3) if den else 0.0


# ── MetaLearning ──────────────────────────────────────────────────────────────

class MetaLearning:
    """SHARD meta-learning: learns HOW to learn across sessions.

    Data model (meta_learning.json):
    {
      "sessions": [...],                 # full history, one record per study cycle
      "score_history": [7.0, 8.5, ...], # last HISTORY_WINDOW scores for trend
      "topic_categories": {
        "algorithms": {
          "total": 12, "certified": 9,
          "scores": [...],
          "avg_score": 7.8, "cert_rate": 0.75
        },
        ...
      },
      "global_stats": {
        "total_sessions": 150,
        "certified": 100,
        "avg_score": 7.2,
        "cert_rate": 0.67,
        "score_trend": 0.05,          # slope; positive = improving
        "best_category": "algorithms",
        "worst_category": "machine_learning"
      }
    }
    """

    def __init__(self, strategy_memory):
        self.strategy_memory = strategy_memory
        self._data: Dict[str, Any] = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        """Load state from SQLite views, fallback to legacy JSON."""
        try:
            conn = _get_db()
            # Global stats from VIEW
            gs_row = conn.execute("SELECT * FROM global_stats").fetchone()
            # Category stats from VIEW
            cat_rows = conn.execute("SELECT * FROM category_stats").fetchall()
            # Score history (last HISTORY_WINDOW scores)
            score_rows = conn.execute(
                "SELECT score FROM experiments WHERE score IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT ?", (HISTORY_WINDOW,)
            ).fetchall()

            gs = {
                "total_sessions": gs_row["total_sessions"] if gs_row else 0,
                "certified": gs_row["certified_count"] if gs_row else 0,
                "avg_score": gs_row["avg_score"] if gs_row else 0.0,
                "cert_rate": gs_row["cert_rate"] if gs_row else 0.0,
                "score_trend": 0.0,
                "best_category": None,
                "worst_category": None,
            }

            cats = {}
            for r in cat_rows:
                cats[r["category"]] = {
                    "total": r["total"],
                    "certified": r["certified_count"],
                    "scores": [],  # populated from experiments if needed
                    "avg_score": r["avg_score"],
                    "cert_rate": r["cert_rate"],
                }

            scores = [r["score"] for r in reversed(score_rows)]  # oldest first
            gs["score_trend"] = _linear_trend(scores)

            # Best/worst category (min 3 sessions)
            significant = {k: v for k, v in cats.items() if v["total"] >= 3}
            if significant:
                gs["best_category"] = max(significant, key=lambda k: significant[k]["avg_score"])
                gs["worst_category"] = min(significant, key=lambda k: significant[k]["avg_score"])

            n = gs["total_sessions"]
            logger.info("[DB] MetaLearning loaded from SQLite -- %d sessions.", n)

            return {
                "sessions": [],  # not cached in-memory; queried from DB on demand
                "score_history": scores,
                "topic_categories": cats,
                "global_stats": gs,
            }
        except Exception as exc:
            logger.warning("[DB] MetaLearning SQLite load failed (%s) -- falling back to JSON", exc)

        # Fallback: legacy JSON
        try:
            if META_DB_PATH.exists():
                data = json.loads(META_DB_PATH.read_text(encoding="utf-8"))
                n = len(data.get("sessions", []))
                logger.info("[META] Loaded from JSON fallback -- %d sessions.", n)
                return data
        except Exception as exc:
            logger.warning("[META] Could not load meta_learning.json (%s) -- starting fresh.", exc)
        return {
            "sessions": [],
            "score_history": [],
            "topic_categories": {},
            "global_stats": {
                "total_sessions": 0,
                "certified": 0,
                "avg_score": 0.0,
                "cert_rate": 0.0,
                "score_trend": 0.0,
                "best_category": None,
                "worst_category": None,
            },
        }

    def _save(self) -> None:
        """No-op: data lives in SQLite experiments table.

        Stats are computed live by SQL views -- no need to persist separately.
        Kept for backwards compatibility (callers still call _save).
        """
        pass

    # ── Public API ────────────────────────────────────────────────────────────

    def suggest_best_strategy(self, topic: Optional[str] = None) -> Optional[str]:
        """Return the description of the historically best-performing strategy.

        Algorithm:
        1. Load all strategies from StrategyMemory.
        2. Classify the topic into a category.
        3. Prefer strategies whose topic matches the same category.
        4. Rank by avg_score desc, then success_rate desc.
        5. Return a formatted summary of the top strategy, or None.

        Returns None when no history exists yet (cold start).
        """
        try:
            strategies = self.strategy_memory.get_all_strategies()
        except Exception as exc:
            logger.warning("[META] Cannot query strategy_memory: %s", exc)
            return None

        if not strategies:
            return None

        category = _classify_topic(topic) if topic else "general"

        def _score(s: dict) -> tuple:
            return (
                float(s.get("avg_score") or s.get("score") or 0),
                float(s.get("success_rate") or 0),
            )

        # Prefer same-category strategies; fall back to all strategies
        if category != "general":
            same_cat = [
                s for s in strategies
                if _classify_topic(str(s.get("topic", "") or s.get("name", ""))) == category
            ]
            pool = same_cat if same_cat else strategies
        else:
            pool = strategies

        pool = [s for s in pool if _score(s)[0] > 0]
        if not pool:
            return None

        pool.sort(key=_score, reverse=True)
        best = pool[0]

        doc = (
            best.get("strategy")
            or best.get("description")
            or best.get("name")
            or ""
        )
        if not doc:
            return None

        avg = float(best.get("avg_score") or best.get("score") or 0)
        sr = float(best.get("success_rate") or 0)
        label = f"[{category}] " if category != "general" else ""
        return f"{label}{doc[:280]} (avg={avg:.1f} sr={sr:.0%})"

    def update(
        self,
        topic: str,
        score: float,
        certified: bool,
        eval_data: Optional[Dict] = None,
        sandbox_result: Optional[Dict] = None,
        attempts: int = 1,
    ) -> None:
        """Record the outcome of a completed study cycle and recompute all stats.

        Called by StudyAgent.study_topic() at the end of every run,
        regardless of whether the topic was certified or failed.
        """
        if eval_data is None:
            eval_data = {}

        category = _classify_topic(topic)
        sandbox_ok = bool(
            sandbox_result and sandbox_result.get("success")
        ) if sandbox_result is not None else False
        verdict = eval_data.get("verdict", "FAIL")
        now = datetime.now().isoformat()

        # ── 1. Write to SQLite experiments table ─────────────────────────────
        try:
            conn = _get_db()
            conn.execute(
                """INSERT INTO experiments
                   (topic, score, certified, sandbox_success, timestamp,
                    category, attempts, verdict)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (topic, score, 1 if certified else 0, 1 if sandbox_ok else 0,
                 now, category, attempts, verdict),
            )
            conn.commit()
            logger.info("[DB] MetaLearning recorded: '%s' [%s] score=%.1f cert=%s",
                        topic, category, score, certified)
        except Exception as exc:
            logger.error("[DB] MetaLearning INSERT failed: %s", exc)

        # ── 2. Refresh in-memory stats from DB views ─────────────────────────
        try:
            conn = _get_db()
            gs_row = conn.execute("SELECT * FROM global_stats").fetchone()
            if gs_row:
                gs = self._data.setdefault("global_stats", {})
                gs["total_sessions"] = gs_row["total_sessions"]
                gs["certified"] = gs_row["certified_count"]
                gs["avg_score"] = gs_row["avg_score"] or 0.0
                gs["cert_rate"] = gs_row["cert_rate"] or 0.0

                # Trend from last N scores
                score_rows = conn.execute(
                    "SELECT score FROM experiments WHERE score IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT ?", (HISTORY_WINDOW,)
                ).fetchall()
                scores = [r["score"] for r in reversed(score_rows)]
                gs["score_trend"] = _linear_trend(scores)

                # Best/worst category
                cat_rows = conn.execute("SELECT * FROM category_stats").fetchall()
                cats = {}
                for r in cat_rows:
                    cats[r["category"]] = {
                        "total": r["total"],
                        "certified": r["certified_count"],
                        "avg_score": r["avg_score"],
                        "cert_rate": r["cert_rate"],
                    }
                self._data["topic_categories"] = cats
                significant = {k: v for k, v in cats.items() if v["total"] >= 3}
                if significant:
                    gs["best_category"] = max(significant, key=lambda k: significant[k]["avg_score"])
                    gs["worst_category"] = min(significant, key=lambda k: significant[k]["avg_score"])
        except Exception as exc:
            logger.warning("[DB] MetaLearning stats refresh failed: %s", exc)

        # ── 3. Log ───────────────────────────────────────────────────────────
        gs = self._data.get("global_stats", {})
        trend = gs.get("score_trend", 0)
        trend_sym = "+" if trend > 0.05 else ("-" if trend < -0.05 else "=")
        logger.info(
            "[META] #%d | '%s' [%s] score=%.1f cert=%s | "
            "global avg=%.1f%s best=%s worst=%s",
            gs.get("total_sessions", 0), topic, category, score, certified,
            gs.get("avg_score", 0), trend_sym,
            gs.get("best_category", "?"),
            gs.get("worst_category", "?"),
        )

    def get_stats(self) -> Dict:
        """Return a summary of meta-learning statistics.

        Reads live from SQLite views -- always up to date.
        """
        try:
            conn = _get_db()
            gs_row = conn.execute("SELECT * FROM global_stats").fetchone()
            cat_rows = conn.execute("SELECT * FROM category_stats").fetchall()
            return {
                "global": {
                    "total_sessions": gs_row["total_sessions"] if gs_row else 0,
                    "certified": gs_row["certified_count"] if gs_row else 0,
                    "avg_score": gs_row["avg_score"] or 0.0 if gs_row else 0.0,
                    "cert_rate": gs_row["cert_rate"] or 0.0 if gs_row else 0.0,
                },
                "categories": {
                    r["category"]: {
                        "total": r["total"],
                        "cert_rate": r["cert_rate"],
                        "avg_score": r["avg_score"],
                    }
                    for r in cat_rows
                },
            }
        except Exception as exc:
            logger.warning("[DB] get_stats SQLite failed (%s), using cached data", exc)
            return {
                "global": self._data.get("global_stats", {}),
                "categories": {
                    k: {
                        "total": v.get("total", 0),
                        "cert_rate": v.get("cert_rate", 0),
                        "avg_score": v.get("avg_score", 0),
                    }
                    for k, v in self._data.get("topic_categories", {}).items()
                },
            }
