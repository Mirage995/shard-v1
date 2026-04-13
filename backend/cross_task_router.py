"""cross_task_router.py -- SHARD v2 Cross-Task Transfer Layer (#22).

Maps topics and error signals to micro-clusters, then routes strategy
retrieval based on cluster membership rather than task identity.

Design (from analysis of 65 sessions):
  - exception_flow (87% win) is a META-STRATEGY: boost it on weak clusters
  - concurrency (36% win) is a FALSE NEGATIVE: SHARD knows threading (9.3)
    but fails to activate the right strategy -- force top strategy
  - mutation_state (63%) is GOLD ZONE: cross-inject exception_flow
  - swe_repair is a noisy fallback: penalize to 0.7x
  - bcrypt/argon2 is toxic (11% win): blacklist entirely

Architecture:
  task/topic --> classify_cluster() --> CLUSTER
  CLUSTER    --> get_boost_rules()  --> adjusted confidence
  CLUSTER    --> get_cross_inject() --> additional strategy topics to query
"""
from __future__ import annotations

import re
import logging
from typing import Optional

logger = logging.getLogger("shard.cross_task_router")

# ── Live near-miss cache (populated from DB at session start) ─────────────────
# Module-level mutable set so refresh_near_miss_from_db() can update it.
_live_near_miss: set[str] = set()


def _get_db_safe():
    """Return DB connection or None on import error (avoids circular deps)."""
    try:
        try:
            from shard_db import get_db
        except ImportError:
            from backend.shard_db import get_db
        return get_db()
    except Exception:
        return None


def refresh_near_miss_from_db() -> None:
    """Populate _live_near_miss from SQLite experiments table.

    Queries topics that scored 6.0–7.4 (near cert threshold) but were never
    certified. These get the 1.3x strategy boost at routing time.
    Call once at session start (e.g. from night_runner or benchmark_loop init).
    """
    conn = _get_db_safe()
    if conn is None:
        logger.debug("[ROUTER] refresh_near_miss_from_db: DB unavailable, skipping")
        return
    try:
        rows = conn.execute(
            """SELECT DISTINCT topic FROM experiments
               WHERE certified=0 AND score >= 6.0 AND score < 7.5
               ORDER BY score DESC LIMIT 30"""
        ).fetchall()
        fresh: set[str] = set()
        for row in rows:
            t = row["topic"] if hasattr(row, "__getitem__") else row[0]
            if t:
                fresh.add(t.lower().strip())
        _live_near_miss.clear()
        _live_near_miss.update(fresh)
        logger.info("[ROUTER] near-miss cache refreshed: %d live topics", len(_live_near_miss))
    except Exception as e:
        logger.debug("[ROUTER] refresh_near_miss_from_db failed: %s", e)

# ── Micro-cluster taxonomy ─────────────────────────────────────────────────────

MICRO_CLUSTERS: dict[str, list[str]] = {
    "boundary":       ["boundary", "off-by-one", "index", "range", "slice", "len-1", "out of range", "indexerror"],
    "mutation_state": ["mutation", "ghost", "idempotency", "mutable", "deepcopy", "state", "side effect", "double apply"],
    "concurrency":    ["race", "thread", "lock", "async", "concurrent", "await", "deadlock", "asyncio", "event loop"],
    "parsing_input":  ["parse", "template", "html", "whitespace", "token", "format", "csv", "config parser"],
    "exception_flow": ["exception", "error handling", "finally", "propagation", "raise", "eafp", "try/except", "guard"],
    "crypto_logic":   ["sha", "aes", "bb84", "quantum", "encryption", "hash", "bcrypt", "argon2", "key encapsulation"],
    "serialization":  ["json", "serial", "deserial", "marshal", "encode", "decode"],
    "algorithm":      ["complexity", "dynamic programming", "bfs", "dfs", "graph", "sort", "search", "binary search"],
    "ml_numerical":   ["gradient", "loss", "relu", "sigmoid", "perceptron", "neural", "regression", "leaky relu"],
    "network":        ["socket", "http", "tcp", "websocket", "dns", "request", "response", "rest api"],
    "architecture":   ["solid", "injection", "pattern", "circuit", "message", "redis", "event driven"],
}

# ── Near-miss registry (score >= 7.5, not certified) ──────────────────────────
# From analysis: these topics are close to certification -- force strategy boost

NEAR_MISS_TOPICS: set[str] = {
    "python asyncio event loop internals",
    "python generators and coroutines",
    "sorting algorithm tier 1",
    "binary search",
    "bfs algorithm",
    "perceptron",
}

# ── Strategy blacklist (win_rate < 0.30 -- toxic) ─────────────────────────────
STRATEGY_BLACKLIST: set[str] = {
    "password hashing bcrypt argon2",
    "bcrypt",
    "argon2",
}

# ── Strategy penalties (win_rate < 0.70 -- noisy) ─────────────────────────────
# Maps strategy name substring -> penalty multiplier
STRATEGY_PENALTIES: dict[str, float] = {
    "swe_repair": 0.50,           # 61% win, 67 misfires -- noisy fallback, penalty raised
    "rest api design patterns": 0.60,  # benchmark invalidi (#28)
}

# ── Cross-cluster injection rules ─────────────────────────────────────────────
# When a task belongs to cluster X, also fetch strategies from cluster Y
# Based on: exception_flow (87%) boosts mutation_state (63%) and network (52%)

CROSS_INJECT_RULES: dict[str, list[str]] = {
    "mutation_state": ["Python Advanced Error Handling", "exception flow", "guard clause"],
    "network":        ["Python Advanced Error Handling", "http client implementation python"],
    "concurrency":    ["concurrent programming threading python", "race condition handling and debugging"],
    "ml_numerical":   ["gradient descent", "algorithm complexity and performance optimization"],
}

# ── Boost rules by cluster ─────────────────────────────────────────────────────
# confidence multiplier applied when cluster is detected
CLUSTER_BOOST: dict[str, float] = {
    "exception_flow":  1.0,   # already dominant -- no extra boost
    "algorithm":       1.0,
    "serialization":   1.0,
    "parsing_input":   1.0,
    "mutation_state":  1.25,  # cross-inject exception_flow -- GOLD ZONE
    "network":         1.25,  # cross-inject exception_flow
    "concurrency":     1.40,  # FALSE NEGATIVE -- force top strategy
    "ml_numerical":    1.20,
    "boundary":        1.10,
    "crypto_logic":    0.70,  # benchmark rotti (#28) -- penalizza
    "architecture":    0.70,  # benchmark invalidi -- penalizza
}


# ── Public API ────────────────────────────────────────────────────────────────

def classify_cluster(topic: str, error_text: str = "") -> Optional[str]:
    """Map a topic (and optional error text) to a micro-cluster.

    Returns the cluster name or None if no match.
    Checks topic first, then error_text for fallback signals.
    """
    combined = (topic + " " + error_text).lower()

    for cluster, keywords in MICRO_CLUSTERS.items():
        if any(kw in combined for kw in keywords):
            logger.debug("[ROUTER] '%s' -> cluster '%s'", topic[:50], cluster)
            return cluster

    return None


def get_boost_factor(cluster: Optional[str], topic: str = "") -> float:
    """Return confidence multiplier for a cluster.

    Also applies near-miss boost (1.3x) if topic is in NEAR_MISS_TOPICS.
    """
    base = CLUSTER_BOOST.get(cluster, 1.0) if cluster else 1.0

    # Near-miss boost: topic is known to score high but not certify
    if _is_near_miss(topic):
        base = max(base, 1.30)
        logger.info("[ROUTER] Near-miss boost applied for '%s'", topic[:50])

    return base


def get_cross_inject_queries(cluster: Optional[str]) -> list[str]:
    """Return additional query strings to inject from other clusters."""
    return CROSS_INJECT_RULES.get(cluster, [])


def is_blacklisted(strategy_text: str) -> bool:
    """True if strategy should be completely excluded."""
    t = strategy_text.lower()
    return any(bl in t for bl in STRATEGY_BLACKLIST)


def get_strategy_penalty(strategy_text: str) -> float:
    """Return penalty multiplier for a strategy (1.0 = no penalty)."""
    t = strategy_text.lower()
    for pattern, penalty in STRATEGY_PENALTIES.items():
        if pattern in t:
            return penalty
    return 1.0


def _is_near_miss(topic: str) -> bool:
    """True if topic is in the near-miss registry (case-insensitive)."""
    tl = topic.lower().strip()
    if not tl:
        return False
    return any(nm in tl or tl in nm for nm in NEAR_MISS_TOPICS | _live_near_miss)


def apply_routing(
    strategies: list[dict],
    topic: str,
    error_text: str = "",
) -> tuple[list[dict], float]:
    """Full routing pipeline: filter, penalize, compute boost.

    Args:
        strategies : list of dicts from strategy_memory.query()
        topic      : current study/benchmark topic
        error_text : optional error message for cluster detection

    Returns:
        (filtered_strategies, boost_factor)
        filtered_strategies: strategies after blacklist/penalty applied
        boost_factor: multiplier to apply to final signal confidence
    """
    cluster = classify_cluster(topic, error_text)
    boost = get_boost_factor(cluster, topic)

    filtered = []
    for s in strategies:
        strat_text = s.get("strategy", "")

        # Hard filter: blacklisted strategies
        if is_blacklisted(strat_text):
            logger.info("[ROUTER] Blacklisted strategy dropped: '%s'", strat_text[:60])
            continue

        # Soft penalty: noisy strategies get score reduced
        penalty = get_strategy_penalty(strat_text)
        if penalty < 1.0:
            s = dict(s)  # don't mutate original
            s["score"] = round(float(s.get("score", 5.0)) * penalty, 2)
            logger.debug("[ROUTER] Penalty %.2f applied to: '%s'", penalty, strat_text[:60])

        filtered.append(s)

    if cluster:
        logger.info(
            "[ROUTER] cluster=%s | boost=%.2f | strategies: %d -> %d",
            cluster, boost, len(strategies), len(filtered)
        )

    return filtered, boost
