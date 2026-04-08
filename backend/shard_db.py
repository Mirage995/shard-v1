"""SHARD SQLite Database Manager -- Single source of truth.

Replaces the 13-file JSON sprawl with a single WAL-mode SQLite database.
Thread-safe singleton: one connection per process, safe for concurrent
reads from server.py while NightRunner writes.

Usage:
    from shard_db import get_db, query, execute, executemany

    # Read (returns list of Row dicts)
    rows = query("SELECT * FROM experiments WHERE certified = 1")

    # Write (auto-commit)
    execute("INSERT INTO experiments (topic, score) VALUES (?, ?)", (t, s))

    # Bulk write
    executemany("INSERT INTO capabilities (name, acquired_at) VALUES (?, ?)", rows)

    # Raw connection (for transactions)
    with get_db() as conn:
        conn.execute(...)
        conn.execute(...)
        # auto-commits on exit
"""

import logging
import os
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger("shard.db")

# ── Path constants ────────────────────────────────────────────────────────────

_BACKEND_DIR = Path(__file__).parent.resolve()
_ROOT_DIR = _BACKEND_DIR.parent.resolve()
_SHARD_MEMORY = _ROOT_DIR / "shard_memory"

DB_PATH: str = str(_SHARD_MEMORY / "shard.db")
SCHEMA_PATH: str = str(_BACKEND_DIR / "schema.sql")

# ── Singleton ─────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_connection: sqlite3.Connection | None = None


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    """Return rows as dicts instead of tuples."""
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def _init_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql if the database has no tables yet, then run migrations."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    if not cursor.fetchone():
        if not os.path.exists(SCHEMA_PATH):
            raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)
        logger.info("[SHARD_DB] Schema v1 applied to %s", DB_PATH)

    _run_migrations(conn)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply incremental migrations for databases already at v1."""
    cursor = conn.execute("SELECT MAX(version) as v FROM schema_version")
    row = cursor.fetchone()
    current = row["v"] if row and row["v"] else 1

    if current < 2:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS activation_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT    NOT NULL,
                topic           TEXT    NOT NULL,
                timestamp       TEXT    NOT NULL,
                score           REAL,
                certified       INTEGER DEFAULT 0,
                predicted_score REAL,
                source          TEXT,
                sig_episodic    REAL    DEFAULT 0.0,
                sig_strategy    REAL    DEFAULT 0.0,
                sig_near_miss   REAL    DEFAULT 0.0,
                sig_first_try   REAL    DEFAULT 0.0,
                sig_graphrag    REAL    DEFAULT 0.0,
                sig_improvement REAL    DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_act_session   ON activation_log(session_id);
            CREATE INDEX IF NOT EXISTS idx_act_topic     ON activation_log(topic);
            CREATE INDEX IF NOT EXISTS idx_act_certified ON activation_log(certified);
            CREATE INDEX IF NOT EXISTS idx_act_timestamp ON activation_log(timestamp);

            CREATE TABLE IF NOT EXISTS synaptic_weights (
                source_citizen  TEXT    NOT NULL,
                target_citizen  TEXT    NOT NULL,
                weight          REAL    DEFAULT 1.0,
                ltp_count       INTEGER DEFAULT 0,
                ltd_count       INTEGER DEFAULT 0,
                last_updated    TEXT,
                PRIMARY KEY (source_citizen, target_citizen)
            );

            INSERT OR REPLACE INTO schema_version (version, applied_at)
            VALUES (2, datetime('now'));
        """)
        logger.info("[SHARD_DB] Migration v2 applied -- activation_log + synaptic_weights")

    if current < 3:
        conn.executescript("""
            ALTER TABLE activation_log ADD COLUMN sig_desire     REAL DEFAULT 0.0;
            ALTER TABLE activation_log ADD COLUMN sig_difficulty REAL DEFAULT 0.5;

            INSERT OR REPLACE INTO schema_version (version, applied_at)
            VALUES (3, datetime('now'));
        """)
        logger.info("[SHARD_DB] Migration v3 applied -- sig_desire + sig_difficulty")

    if current < 4:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pivot_events (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id          TEXT    NOT NULL,
                topic               TEXT    NOT NULL,
                timestamp           TEXT    NOT NULL,
                reason              TEXT    NOT NULL,
                fail_streak         INTEGER DEFAULT 0,
                variance_std        REAL,
                prev_strategies     INTEGER DEFAULT 0,
                cleared             INTEGER DEFAULT 0,
                pre_fingerprint     TEXT,
                post_fingerprint    TEXT,
                distance            REAL
            );
            CREATE INDEX IF NOT EXISTS idx_pivot_topic   ON pivot_events(topic);
            CREATE INDEX IF NOT EXISTS idx_pivot_session ON pivot_events(session_id);

            INSERT OR REPLACE INTO schema_version (version, applied_at)
            VALUES (4, datetime('now'));
        """)
        logger.info("[SHARD_DB] Migration v4 applied -- pivot_events table")

    if current < 5:
        conn.executescript("""
            -- Typed memory store: facts extracted from study, sessions, connectors
            CREATE TABLE IF NOT EXISTS memories (
                id           TEXT PRIMARY KEY,          -- UUID
                content      TEXT NOT NULL,             -- The fact in natural language
                memory_type  TEXT NOT NULL,             -- FACT | PREFERENCE | EPISODE | GOAL | RELATION
                entities     TEXT DEFAULT '[]',         -- JSON array of named entities
                confidence   REAL DEFAULT 1.0,          -- 0.0-1.0
                is_latest    INTEGER DEFAULT 1,         -- 0/1 — superseded memories set to 0
                expires_at   TEXT,                      -- ISO 8601, NULL = never expires
                updates      TEXT,                      -- ID of memory this supersedes (FK-like)
                source_type  TEXT NOT NULL,             -- study | session_log | derivation | connector
                source_ref   TEXT,                      -- topic name, session_id, etc.
                container_tag TEXT NOT NULL DEFAULT 'shard', -- scoping (shard, andrea, project, etc.)
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_mem_type      ON memories(memory_type);
            CREATE INDEX IF NOT EXISTS idx_mem_latest    ON memories(is_latest);
            CREATE INDEX IF NOT EXISTS idx_mem_container ON memories(container_tag);
            CREATE INDEX IF NOT EXISTS idx_mem_source    ON memories(source_type, source_ref);
            CREATE INDEX IF NOT EXISTS idx_mem_expires   ON memories(expires_at);
            CREATE INDEX IF NOT EXISTS idx_mem_created   ON memories(created_at);

            INSERT OR REPLACE INTO schema_version (version, applied_at)
            VALUES (5, datetime('now'));
        """)
        logger.info("[SHARD_DB] Migration v5 applied -- memories table")

    if current < 6:
        conn.executescript("""
            -- Predictions log (replaces predictions.jsonl)
            CREATE TABLE IF NOT EXISTS predictions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                topic      TEXT    NOT NULL,
                predicted  REAL,
                actual     REAL,
                error      REAL,
                certified  INTEGER DEFAULT 0,
                features   TEXT,
                context    TEXT,
                ts         TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_pred_topic ON predictions(topic);
            CREATE INDEX IF NOT EXISTS idx_pred_ts    ON predictions(ts);

            -- Self inconsistencies log (replaces self_inconsistencies.jsonl)
            CREATE TABLE IF NOT EXISTS self_inconsistencies (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                topic      TEXT,
                event_type TEXT    NOT NULL DEFAULT 'inconsistency',
                feature    TEXT,
                context    TEXT,
                global_w   REAL,
                contextual_w REAL,
                gap        REAL,
                error      REAL,
                severity   TEXT,
                resolution TEXT,
                explanation TEXT,
                extra      TEXT,
                ts         TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_incons_topic ON self_inconsistencies(topic);
            CREATE INDEX IF NOT EXISTS idx_incons_ts    ON self_inconsistencies(ts);

            -- Session reflections log (replaces session_reflections.jsonl)
            CREATE TABLE IF NOT EXISTS session_reflections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                ts         TEXT    NOT NULL DEFAULT (datetime('now')),
                certified  TEXT    DEFAULT '[]',
                failed     TEXT    DEFAULT '[]',
                text       TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_refl_session ON session_reflections(session_id);
            CREATE INDEX IF NOT EXISTS idx_refl_ts      ON session_reflections(ts);

            INSERT OR REPLACE INTO schema_version (version, applied_at)
            VALUES (6, datetime('now'));
        """)
        logger.info("[SHARD_DB] Migration v6 applied -- predictions + self_inconsistencies + session_reflections tables")


def get_db() -> sqlite3.Connection:
    """Return the singleton SQLite connection.

    Creates the database and applies the schema on first call.
    Thread-safe via double-checked locking.
    The connection uses WAL mode and 5s busy timeout for concurrency.
    """
    global _connection

    if _connection is not None:
        return _connection

    with _lock:
        if _connection is not None:
            return _connection

        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

        conn = sqlite3.connect(
            DB_PATH,
            check_same_thread=False,   # We manage thread safety via _lock
            timeout=10.0,              # Wait up to 10s for locks
        )
        conn.row_factory = _row_factory

        # Core pragmas for performance and safety
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")  # Safe with WAL

        _init_schema(conn)

        _connection = conn
        logger.info("[SHARD_DB] Connection established: %s (WAL mode)", DB_PATH)
        return _connection


# ── Convenience API ───────────────────────────────────────────────────────────

def query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT and return all rows as dicts."""
    conn = get_db()
    cursor = conn.execute(sql, params)
    return cursor.fetchall()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """Execute a SELECT and return the first row as a dict, or None."""
    conn = get_db()
    cursor = conn.execute(sql, params)
    return cursor.fetchone()


def execute(sql: str, params: tuple = ()) -> int:
    """Execute an INSERT/UPDATE/DELETE and return lastrowid.

    Auto-commits. For multi-statement transactions, use get_db() directly.
    """
    conn = get_db()
    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.lastrowid


def executemany(sql: str, params_list: list[tuple]) -> int:
    """Execute a parameterized statement for each param tuple.

    Wraps everything in a single transaction for performance.
    Returns the number of rows affected.
    """
    conn = get_db()
    cursor = conn.executemany(sql, params_list)
    conn.commit()
    return cursor.rowcount


def execute_transaction(statements: list[tuple[str, tuple]]) -> None:
    """Execute multiple statements in a single transaction.

    Each element is (sql, params). Rolls back on any error.
    """
    conn = get_db()
    try:
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close() -> None:
    """Close the singleton connection. Called on shutdown."""
    global _connection
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None
            logger.info("[SHARD_DB] Connection closed")


# ── Schema migration helpers ─────────────────────────────────────────────────

def get_schema_version() -> int:
    """Return the current schema version."""
    try:
        row = query_one("SELECT MAX(version) as v FROM schema_version")
        return row["v"] if row and row["v"] else 0
    except sqlite3.OperationalError:
        return 0


def set_schema_version(version: int) -> None:
    """Record a schema migration."""
    execute(
        "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
        (version,),
    )
