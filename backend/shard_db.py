"""SHARD SQLite Database Manager — Single source of truth.

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
    """Apply schema.sql if the database has no tables yet."""
    # Check if schema is already applied
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    if cursor.fetchone():
        return  # Schema already exists

    if not os.path.exists(SCHEMA_PATH):
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn.executescript(schema_sql)
    logger.info("[SHARD_DB] Schema v1 applied to %s", DB_PATH)


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
