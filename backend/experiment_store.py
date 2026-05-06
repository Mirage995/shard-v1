"""experiment_store.py -- Persistence layer for research_hypotheses table.

Manages hypothesis lifecycle for the SHARD Experiment Engine (#34).
No LLM logic -- pure SQLite read/write following the experiment_cache.py pattern.

Lifecycle:
    PENDING -> CONFIRMED | REFUTED | INCONCLUSIVE | SKIPPED_TOO_COMPLEX | KAGGLE_READY
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("shard.experiment_store")


def _get_db():
    """Lazy import to avoid circular deps at module load time."""
    from shard_db import get_db
    return get_db()


def _ensure_table():
    """Create research_hypotheses table if not present (idempotent)."""
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_hypotheses (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            topic               TEXT    NOT NULL,
            statement           TEXT    NOT NULL,
            domain_from         TEXT,
            domain_to           TEXT,
            rationale           TEXT,
            falsifiable         INTEGER DEFAULT 0,
            minimum_experiment  TEXT,
            confidence_initial  REAL,
            confidence_updated  REAL,
            status              TEXT    DEFAULT 'PENDING',
            experiment_code     TEXT,
            experiment_result   TEXT,
            source_papers       TEXT,
            created_at          TEXT    DEFAULT (datetime('now')),
            updated_at          TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hypotheses_topic ON research_hypotheses(topic)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON research_hypotheses(status)"
    )
    conn.commit()
    _migrate_provenance_columns(conn)


def _migrate_provenance_columns(conn) -> None:
    """Add provenance columns to existing databases (idempotent, safe on re-run).

    Three axes of scientific validity:
      execution_backend : WHERE the experiment ran (local_sandbox | kaggle | modal | external | unknown)
      data_provenance   : WHAT data was used (synthetic | toy_benchmark | public_benchmark | real_world | unknown)
      validation_tier   : HOW STRONG the validation is
                          (code_runs | sandbox_replicated | gpu_replicated | benchmark_validated | external_replicated)
      manual_backfill   : True if provenance was set retroactively by a human, not the pipeline
    """
    cols = [
        ("execution_backend", "TEXT    DEFAULT 'local_sandbox'"),
        ("data_provenance",   "TEXT    DEFAULT 'synthetic'"),
        ("validation_tier",   "TEXT    DEFAULT 'sandbox_replicated'"),
        ("manual_backfill",   "INTEGER DEFAULT 0"),
    ]
    for col, definition in cols:
        try:
            conn.execute(f"ALTER TABLE research_hypotheses ADD COLUMN {col} {definition}")
            conn.commit()
        except Exception:
            pass  # column already exists — SQLite raises OperationalError on duplicate ADD


def _row_to_dict(row) -> Dict:
    """Convert sqlite3.Row to plain dict, deserializing JSON fields."""
    d = dict(row)
    for field in ("experiment_result", "source_papers"):
        if d.get(field) and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def store_hypothesis(topic: str, hypothesis: Dict, source_papers: Optional[List[Dict]] = None) -> Optional[int]:
    """Insert a new hypothesis with status PENDING. Returns the new row id.

    Args:
        topic           : study topic that generated the hypothesis
        hypothesis      : dict with keys: statement, domain_from, domain_to,
                          rationale, falsifiable, minimum_experiment, confidence
        source_papers   : optional list of {title, year, url} dicts

    Returns:
        int row id on success, None on error.
    """
    try:
        conn = _get_db()
        _ensure_table()
        cursor = conn.execute(
            """
            INSERT INTO research_hypotheses
                (topic, statement, domain_from, domain_to, rationale,
                 falsifiable, minimum_experiment, confidence_initial,
                 status, source_papers, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, datetime('now'), datetime('now'))
            """,
            (
                topic,
                hypothesis.get("statement", ""),
                hypothesis.get("domain_from"),
                hypothesis.get("domain_to"),
                hypothesis.get("rationale"),
                1 if hypothesis.get("falsifiable") else 0,
                hypothesis.get("minimum_experiment"),
                hypothesis.get("confidence"),
                json.dumps(source_papers) if source_papers else None,
            ),
        )
        conn.commit()
        row_id = cursor.lastrowid
        logger.info("[EXPERIMENT_STORE] Stored hypothesis id=%d topic='%s'", row_id, topic[:60])
        return row_id
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] store_hypothesis failed: %s", exc)
        return None


def update_result(
    hypothesis_id: int,
    status: str,
    experiment_code: Optional[str] = None,
    experiment_result: Optional[Dict] = None,
    confidence_updated: Optional[float] = None,
    execution_backend: Optional[str] = None,
    data_provenance: Optional[str] = None,
    validation_tier: Optional[str] = None,
    manual_backfill: bool = False,
) -> bool:
    """Update a hypothesis after experiment execution.

    Args:
        hypothesis_id       : row id returned by store_hypothesis()
        status              : CONFIRMED | REFUTED | INCONCLUSIVE | SKIPPED_TOO_COMPLEX | KAGGLE_READY
        experiment_code     : Python code that was executed
        experiment_result   : dict with stdout/stderr/exit_code/success
        confidence_updated  : empirical confidence post-test (0.0-1.0)
        execution_backend   : where the experiment ran (local_sandbox | kaggle | modal | external | unknown)
        data_provenance     : type of data used (synthetic | toy_benchmark | public_benchmark | real_world | unknown)
        validation_tier     : strength of validation (code_runs | sandbox_replicated | gpu_replicated |
                              benchmark_validated | external_replicated)
        manual_backfill     : True if provenance was set retroactively by a human

    Returns:
        True on success, False on error.
    """
    try:
        conn = _get_db()
        _migrate_provenance_columns(conn)

        set_clauses = [
            "status             = ?",
            "experiment_code    = ?",
            "experiment_result  = ?",
            "confidence_updated = ?",
            "updated_at         = datetime('now')",
        ]
        params: list = [
            status,
            experiment_code,
            json.dumps(experiment_result) if experiment_result else None,
            confidence_updated,
        ]

        if execution_backend is not None:
            set_clauses.append("execution_backend = ?")
            params.append(execution_backend)
        if data_provenance is not None:
            set_clauses.append("data_provenance = ?")
            params.append(data_provenance)
        if validation_tier is not None:
            set_clauses.append("validation_tier = ?")
            params.append(validation_tier)
        if manual_backfill:
            set_clauses.append("manual_backfill = 1")

        params.append(hypothesis_id)
        conn.execute(
            f"UPDATE research_hypotheses SET {', '.join(set_clauses)} WHERE id = ?",
            params,
        )
        conn.commit()
        logger.info("[EXPERIMENT_STORE] Updated id=%d status=%s", hypothesis_id, status)
        return True
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] update_result failed: %s", exc)
        return False


def set_provenance(
    hypothesis_id: int,
    execution_backend: str,
    data_provenance: str,
    validation_tier: str,
    manual_backfill: bool = True,
) -> bool:
    """Manually set provenance fields on an existing hypothesis (backfill helper).

    Use for retroactive classification of results that predate automatic provenance
    tracking. Sets manual_backfill=True by default to mark retroactive updates.

    Example — Hypothesis #14 (Split-MNIST, Kaggle GPU run):
        set_provenance(14, "kaggle", "public_benchmark", "gpu_replicated")
    """
    try:
        conn = _get_db()
        _migrate_provenance_columns(conn)
        conn.execute(
            """
            UPDATE research_hypotheses
            SET execution_backend = ?,
                data_provenance   = ?,
                validation_tier   = ?,
                manual_backfill   = ?,
                updated_at        = datetime('now')
            WHERE id = ?
            """,
            (execution_backend, data_provenance, validation_tier, 1 if manual_backfill else 0, hypothesis_id),
        )
        conn.commit()
        logger.info(
            "[EXPERIMENT_STORE] Provenance set id=%d backend=%s provenance=%s tier=%s manual=%s",
            hypothesis_id, execution_backend, data_provenance, validation_tier, manual_backfill,
        )
        return True
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] set_provenance failed: %s", exc)
        return False


def get_by_topic(topic: str) -> List[Dict]:
    """Return all hypotheses for a topic, newest first."""
    try:
        conn = _get_db()
        _ensure_table()
        rows = conn.execute(
            "SELECT * FROM research_hypotheses WHERE topic = ? ORDER BY created_at DESC",
            (topic,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] get_by_topic failed: %s", exc)
        return []


def get_pending(min_confidence: float = 0.6) -> List[Dict]:
    """Return PENDING hypotheses with confidence_initial >= min_confidence."""
    try:
        conn = _get_db()
        _ensure_table()
        rows = conn.execute(
            """
            SELECT * FROM research_hypotheses
            WHERE status = 'PENDING'
              AND falsifiable = 1
              AND confidence_initial >= ?
            ORDER BY confidence_initial DESC
            """,
            (min_confidence,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] get_pending failed: %s", exc)
        return []


def get_confirmed() -> List[Dict]:
    """Return all CONFIRMED hypotheses, newest first."""
    try:
        conn = _get_db()
        _ensure_table()
        rows = conn.execute(
            "SELECT * FROM research_hypotheses WHERE status = 'CONFIRMED' ORDER BY updated_at DESC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] get_confirmed failed: %s", exc)
        return []


def get_skipped_complex() -> List[Dict]:
    """Return hypotheses skipped because they need external resources.

    These are candidates for testing outside the local sandbox:
    cloud VMs, Colab, full training pipelines, etc.
    Ordered by confidence_initial DESC -- most promising first.
    """
    try:
        conn = _get_db()
        _ensure_table()
        rows = conn.execute(
            """
            SELECT * FROM research_hypotheses
            WHERE status = 'SKIPPED_TOO_COMPLEX'
            ORDER BY confidence_initial DESC, created_at DESC
            """
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] get_skipped_complex failed: %s", exc)
        return []


def get_kaggle_ready() -> List[Dict]:
    """Return hypotheses that need GPU/external data but have generated Kaggle code.

    These are ready to run on Kaggle/Colab — the experiment_code column holds
    the notebook-ready Python. Ordered by confidence_initial DESC.
    """
    try:
        conn = _get_db()
        _ensure_table()
        rows = conn.execute(
            """
            SELECT * FROM research_hypotheses
            WHERE status = 'KAGGLE_READY'
            ORDER BY confidence_initial DESC, created_at DESC
            """
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] get_kaggle_ready failed: %s", exc)
        return []


def get_pending_gpu_runs(limit: int = 5) -> List[Dict]:
    """Return KAGGLE_READY and MODAL_READY hypotheses that have not yet produced a result.

    Used by NightRunner._execute_pending_gpu_experiments() to auto-dispatch
    experiments to Kaggle or Modal and close the science loop.
    Capped at `limit` per call to stay within Kaggle parallel kernel limits.
    """
    try:
        conn = _get_db()
        _ensure_table()
        rows = conn.execute(
            """
            SELECT * FROM research_hypotheses
            WHERE status IN ('KAGGLE_READY', 'MODAL_READY')
              AND status != 'FAILED'
              AND (experiment_result IS NULL
                   OR experiment_result = ''
                   OR experiment_result = '{}')
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error("[EXPERIMENT_STORE] get_pending_gpu_runs failed: %s", exc)
        return []
