"""kaggle_quota.py -- Kaggle GPU-hours budget guard for SHARD's research engine.

Treats the 28 free Kaggle GPU-hours as a scientific budget. Prevents dispatching
weak or low-priority hypotheses that would waste GPU time before high-priority
experiments complete.

Config (env vars, all have safe defaults):
  KAGGLE_GPU_HOURS_AVAILABLE   = 28      total free hours remaining
  KAGGLE_MAX_HOURS_PER_RUN     = 2       hard cap per individual run
  KAGGLE_DISPATCH_ENABLED      = false   auto-dispatch guard (off by default)
  KAGGLE_REQUIRE_MANUAL_APPROVAL = true  requires manual go-ahead before dispatch

Ledger table: kaggle_quota_ledger (in shard.db, persistent across sessions).
"""
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("shard.kaggle_quota")

# ── Config readers (evaluated at call time for easy env-var override) ─────────

def _cfg_available() -> float:
    return float(os.environ.get("KAGGLE_GPU_HOURS_AVAILABLE", "28"))

def _cfg_max_per_run() -> float:
    return float(os.environ.get("KAGGLE_MAX_HOURS_PER_RUN", "2"))

def _cfg_dispatch_enabled() -> bool:
    return os.environ.get("KAGGLE_DISPATCH_ENABLED", "false").lower() == "true"

def _cfg_require_manual_approval() -> bool:
    return os.environ.get("KAGGLE_REQUIRE_MANUAL_APPROVAL", "true").lower() != "false"


# ── Keyword sets for deterministic hour estimation ────────────────────────────

_HEAVY_KEYWORDS: frozenset = frozenset({
    "gpt", "llm", "large model", "large language", "fine-tuning", "fine-tune",
    "bert", "pretrained", "pre-trained", "full training run", "pretraining",
})

_MEDIUM_KEYWORDS: frozenset = frozenset({
    "train", "training", "epoch", "optimization", "gradient descent",
    "backprop", "backpropagation", "neural network training", "deep learning",
})


def estimate_gpu_hours(hypothesis: dict) -> float:
    """Deterministic estimate of Kaggle GPU-hours needed for a hypothesis experiment.

    Heuristic tiers (capped at KAGGLE_MAX_HOURS_PER_RUN):
      heavy  (LLM/fine-tuning keywords) → 1.5 h
      medium (training/epoch keywords)  → 1.0 h
      light  (default)                  → 0.5 h
    """
    text = " ".join(filter(None, [
        hypothesis.get("statement", ""),
        hypothesis.get("minimum_experiment", ""),
        hypothesis.get("rationale", ""),
    ])).lower()

    if any(k in text for k in _HEAVY_KEYWORDS):
        hours = 1.5
    elif any(k in text for k in _MEDIUM_KEYWORDS):
        hours = 1.0
    else:
        hours = 0.5

    return min(hours, _cfg_max_per_run())


# ── Ledger persistence ────────────────────────────────────────────────────────

def _get_db():
    try:
        from shard_db import get_db
    except ImportError:
        from backend.shard_db import get_db
    return get_db()


def _ensure_ledger(conn) -> None:
    """Create kaggle_quota_ledger table if not present (idempotent)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kaggle_quota_ledger (
            run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            hypothesis_id       INTEGER NOT NULL,
            estimated_gpu_hours REAL    NOT NULL,
            actual_gpu_hours    REAL,
            status              TEXT    NOT NULL DEFAULT 'PENDING',
            created_at          TEXT    DEFAULT (datetime('now')),
            completed_at        TEXT,
            backend             TEXT    NOT NULL DEFAULT 'kaggle',
            validation_tier_target TEXT DEFAULT 'gpu_replicated',
            validation_goal     TEXT,
            priority_score      REAL    DEFAULT 0.5
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_kql_status ON kaggle_quota_ledger(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_kql_hyp_id ON kaggle_quota_ledger(hypothesis_id)"
    )
    conn.commit()


def get_pending_ledger_hours(conn=None) -> float:
    """Return sum of estimated_gpu_hours for all PENDING runs in the ledger."""
    if conn is None:
        conn = _get_db()
    _ensure_ledger(conn)
    row = conn.execute(
        "SELECT COALESCE(SUM(estimated_gpu_hours), 0.0) AS total "
        "FROM kaggle_quota_ledger WHERE status = 'PENDING'"
    ).fetchone()
    if row is None:
        return 0.0
    val = row["total"] if isinstance(row, dict) else row[0]
    return float(val or 0.0)


# ── Quota check ───────────────────────────────────────────────────────────────

def check_quota(estimated_hours: float, conn=None) -> Dict:
    """Check whether a new run is within budget.

    Returns a dict with:
      allowed           (bool)
      reason            (str)  — empty string when allowed
      estimated_hours   (float)
      pending_hours     (float)
      available_hours   (float)
      max_per_run       (float)
    """
    if conn is None:
        conn = _get_db()

    max_per_run = _cfg_max_per_run()
    available   = _cfg_available()
    pending     = get_pending_ledger_hours(conn)

    if estimated_hours > max_per_run:
        return {
            "allowed":          False,
            "reason":           f"EXCEEDS_MAX_PER_RUN: {estimated_hours:.2f}h > {max_per_run:.2f}h limit",
            "estimated_hours":  estimated_hours,
            "pending_hours":    pending,
            "available_hours":  available,
            "max_per_run":      max_per_run,
        }

    if pending + estimated_hours > available:
        return {
            "allowed":          False,
            "reason":           (
                f"QUOTA_EXHAUSTED: pending={pending:.2f}h + est={estimated_hours:.2f}h "
                f"> available={available:.2f}h"
            ),
            "estimated_hours":  estimated_hours,
            "pending_hours":    pending,
            "available_hours":  available,
            "max_per_run":      max_per_run,
        }

    return {
        "allowed":          True,
        "reason":           "",
        "estimated_hours":  estimated_hours,
        "pending_hours":    pending,
        "available_hours":  available,
        "max_per_run":      max_per_run,
    }


# ── Enqueue ───────────────────────────────────────────────────────────────────

def try_enqueue(
    hypothesis_id: int,
    hypothesis: dict,
    validation_goal: str = "",
    validation_tier_target: str = "gpu_replicated",
    conn=None,
) -> Dict:
    """Check quota and, if allowed, add a run to the kaggle_quota_ledger.

    Returns:
      allowed           (bool)
      run_id            (int | None) — row id if allowed, None if blocked
      estimated_hours   (float)
      pending_hours     (float)
      available_hours   (float)
      reason            (str)
    """
    if conn is None:
        conn = _get_db()

    _ensure_ledger(conn)

    estimated_hours = estimate_gpu_hours(hypothesis)
    priority_score  = float(hypothesis.get("confidence", 0.5) or 0.5)

    quota = check_quota(estimated_hours, conn)

    if not quota["allowed"]:
        logger.warning(
            "[KAGGLE_QUOTA_EXCEEDED] hyp_id=%s est=%.2fh reason=%s",
            hypothesis_id, estimated_hours, quota["reason"],
        )
        return {
            "allowed":          False,
            "run_id":           None,
            "estimated_hours":  estimated_hours,
            "pending_hours":    quota["pending_hours"],
            "available_hours":  quota["available_hours"],
            "reason":           quota["reason"],
        }

    cursor = conn.execute(
        """
        INSERT INTO kaggle_quota_ledger
            (hypothesis_id, estimated_gpu_hours, status,
             validation_tier_target, validation_goal, priority_score,
             backend, created_at)
        VALUES (?, ?, 'PENDING', ?, ?, ?, 'kaggle', datetime('now'))
        """,
        (hypothesis_id, estimated_hours, validation_tier_target,
         validation_goal[:500] if validation_goal else "",
         priority_score),
    )
    conn.commit()
    run_id = cursor.lastrowid

    logger.info(
        "[KAGGLE_QUOTA] Enqueued run_id=%d hyp_id=%s est=%.2fh "
        "pending_after=%.2fh available=%.2fh tier=%s",
        run_id, hypothesis_id, estimated_hours,
        quota["pending_hours"] + estimated_hours,
        quota["available_hours"],
        validation_tier_target,
    )
    return {
        "allowed":          True,
        "run_id":           run_id,
        "estimated_hours":  estimated_hours,
        "pending_hours":    quota["pending_hours"],
        "available_hours":  quota["available_hours"],
        "reason":           "",
    }


# ── Dispatch control ──────────────────────────────────────────────────────────

def can_dispatch() -> bool:
    """Return True only if auto-dispatch is explicitly enabled AND manual approval is off.

    Both conditions must hold. Either flag being in its safe default (dispatch=false,
    require_approval=true) keeps dispatch blocked.
    """
    return _cfg_dispatch_enabled() and not _cfg_require_manual_approval()


# ── Queue health ──────────────────────────────────────────────────────────────

def get_queue_health(conn=None) -> Dict:
    """Return queue health metrics and any warnings.

    Returns:
      pending_kaggle_runs       (int)
      pending_estimated_hours   (float)
      oldest_pending_age_days   (float | None)
      available_hours           (float)
      dispatch_enabled          (bool)
      require_manual_approval   (bool)
      can_dispatch              (bool)
      warnings                  (List[str])
    """
    if conn is None:
        conn = _get_db()

    _ensure_ledger(conn)

    available = _cfg_available()

    rows = conn.execute(
        """
        SELECT COUNT(*) AS cnt,
               COALESCE(SUM(estimated_gpu_hours), 0.0) AS total_est,
               MIN(created_at) AS oldest_created
        FROM kaggle_quota_ledger
        WHERE status = 'PENDING'
        """
    ).fetchone()

    if rows is None:
        cnt, total_est, oldest = 0, 0.0, None
    elif isinstance(rows, dict):
        cnt, total_est, oldest = rows["cnt"], rows["total_est"], rows["oldest_created"]
    else:
        cnt, total_est, oldest = rows[0], rows[1], rows[2]

    oldest_age_days = None
    if oldest:
        try:
            created_dt = datetime.fromisoformat(str(oldest).replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            oldest_age_days = (now - created_dt).total_seconds() / 86400.0
        except Exception:
            oldest_age_days = None

    warnings: List[str] = []
    if oldest_age_days is not None and oldest_age_days > 7:
        warnings.append(
            f"STALE_QUEUE: oldest pending run is {oldest_age_days:.1f} days old (> 7-day threshold)"
        )
    if float(total_est or 0.0) > available:
        warnings.append(
            f"OVER_BUDGET: pending={float(total_est or 0.0):.2f}h > available={available:.2f}h"
        )

    return {
        "pending_kaggle_runs":     int(cnt or 0),
        "pending_estimated_hours": float(total_est or 0.0),
        "oldest_pending_age_days": oldest_age_days,
        "available_hours":         available,
        "dispatch_enabled":        _cfg_dispatch_enabled(),
        "require_manual_approval": _cfg_require_manual_approval(),
        "can_dispatch":            can_dispatch(),
        "warnings":                warnings,
    }
