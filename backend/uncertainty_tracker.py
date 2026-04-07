"""uncertainty_tracker.py -- Epistemic confidence layer for certified capabilities.

Computes an uncertainty score [0, 1] for each certified topic based on:
  1. Certification score   -- higher score → lower uncertainty
  2. Attempts before cert  -- more failures before success → lower confidence
  3. Time decay            -- knowledge gets stale; exponential decay over 90 days

Public API:
    get_uncertainty(topic: str) -> float
    get_high_uncertainty_topics(threshold=0.5, top_n=10) -> List[str]

Used by DesireEngine to add a fourth signal to desire_score, enabling SHARD
to proactively re-study fragile knowledge — not just blocked topics.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger("shard.uncertainty_tracker")

# Time constant for age decay (days). At T=TAU_DAYS, confidence is multiplied by 1/e ≈ 0.37.
_TAU_DAYS: float = 90.0


def _get_db():
    """Lazy import to avoid circular deps at module load time."""
    try:
        from shard_db import get_db
    except ImportError:
        from backend.shard_db import get_db
    return get_db()


# ── Core math (pure function — testable without DB) ───────────────────────────

def _compute_uncertainty(
    score: float,
    attempts_before_cert: int,
    days_since_cert: float,
) -> float:
    """Return uncertainty in [0, 1] given three evidence signals.

    Formula:
        cert_score_factor = score / 10.0
        attempt_penalty   = 1 / (1 + attempts_before_cert)
        age_decay         = exp(-days_since_cert / TAU_DAYS)
        confidence        = cert_score_factor * attempt_penalty * age_decay
        uncertainty       = 1.0 - confidence

    Args:
        score:                Certification score (0–10).
        attempts_before_cert: Number of failed attempts before the first success.
        days_since_cert:      Calendar days since certification timestamp.

    Returns:
        Uncertainty score in [0.0, 1.0].
    """
    cert_score_factor = max(0.0, min(1.0, score / 10.0))
    attempt_penalty   = 1.0 / (1.0 + max(0, attempts_before_cert))
    age_decay         = math.exp(-days_since_cert / _TAU_DAYS)

    confidence  = cert_score_factor * attempt_penalty * age_decay
    uncertainty = 1.0 - confidence
    return round(max(0.0, min(1.0, uncertainty)), 4)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _days_since(iso_timestamp: str) -> float:
    """Return calendar days elapsed since an ISO-8601 timestamp."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        # Make timezone-aware if naive
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0.0, delta.total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _attempts_before_cert(conn, topic: str) -> int:
    """Count failed experiment rows for topic before the first certified row."""
    try:
        rows = conn.execute(
            "SELECT certified FROM experiments WHERE topic = ? ORDER BY created_at ASC",
            (topic,),
        ).fetchall()
        failed = 0
        for row in rows:
            certified = row["certified"] if hasattr(row, "__getitem__") else row[0]
            if certified:
                break
            failed += 1
        return failed
    except Exception:
        return 0


# ── Public API ────────────────────────────────────────────────────────────────

def get_uncertainty(topic: str) -> float:
    """Return uncertainty score [0, 1] for a certified topic.

    Returns 0.0 if the topic is not found in skill_library (not yet certified —
    uncertainty is undefined, not high).
    """
    try:
        conn = _get_db()

        # Fetch cert data from skill_library
        row = conn.execute(
            "SELECT score, certified_at FROM skill_library WHERE topic = ?",
            (topic,),
        ).fetchone()

        if row is None:
            return 0.0  # Not certified — not tracked here

        score        = float(row["score"] if hasattr(row, "__getitem__") else row[0])
        certified_at = row["certified_at"] if hasattr(row, "__getitem__") else row[1]
        days         = _days_since(certified_at)
        attempts     = _attempts_before_cert(conn, topic)

        return _compute_uncertainty(score, attempts, days)

    except Exception as e:
        logger.debug("[UNCERTAINTY] get_uncertainty('%s') failed: %s", topic, e)
        return 0.0


def get_high_uncertainty_topics(
    threshold: float = 0.5,
    top_n: int = 10,
) -> List[str]:
    """Return certified topics with uncertainty above threshold, sorted descending.

    Args:
        threshold: Minimum uncertainty score to include (default 0.5).
        top_n:     Maximum number of topics to return.

    Returns:
        List of topic strings ordered by uncertainty (highest first).
    """
    try:
        conn  = _get_db()
        rows  = conn.execute(
            "SELECT topic, score, certified_at FROM skill_library ORDER BY certified_at ASC"
        ).fetchall()

        scored: list[tuple[float, str]] = []
        for row in rows:
            topic        = row["topic"]        if hasattr(row, "__getitem__") else row[0]
            score        = float(row["score"]  if hasattr(row, "__getitem__") else row[1])
            certified_at = row["certified_at"] if hasattr(row, "__getitem__") else row[2]
            days         = _days_since(certified_at)
            attempts     = _attempts_before_cert(conn, topic)
            u            = _compute_uncertainty(score, attempts, days)
            if u >= threshold:
                scored.append((u, topic))

        scored.sort(reverse=True)
        return [t for _, t in scored[:top_n]]

    except Exception as e:
        logger.debug("[UNCERTAINTY] get_high_uncertainty_topics() failed: %s", e)
        return []
