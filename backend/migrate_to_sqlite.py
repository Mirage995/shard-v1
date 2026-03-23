#!/usr/bin/env python3
"""SHARD JSON -> SQLite Migration Script.

Reads all legacy JSON files and populates shard.db.
Safe to run multiple times — uses INSERT OR IGNORE to avoid duplicates.
Always run from the backend/ directory or project root.

Usage:
    python backend/migrate_to_sqlite.py [--dry-run]
"""

import json
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Ensure backend/ is importable
BACKEND_DIR = Path(__file__).parent.resolve()
ROOT_DIR = BACKEND_DIR.parent.resolve()
sys.path.insert(0, str(BACKEND_DIR))

from shard_db import get_db, query, query_one, execute, executemany, DB_PATH

# ── Path constants ────────────────────────────────────────────────────────────

SHARD_MEMORY = ROOT_DIR / "shard_memory"

FILES = {
    "experiment_history": SHARD_MEMORY / "experiment_history.json",
    "experiment_replay": SHARD_MEMORY / "experiment_replay.json",
    "failed_cache": SHARD_MEMORY / "failed_cache.json",
    "capability_graph": SHARD_MEMORY / "capability_graph.json",
    "meta_learning": SHARD_MEMORY / "meta_learning.json",
    "improvement_queue": SHARD_MEMORY / "improvement_queue.json",
    "refactor_state": SHARD_MEMORY / "refactor_state.json",
}


def _load_json(path: Path) -> object:
    """Load a JSON file, returning None if missing or corrupt."""
    if not path.exists():
        print(f"  [SKIP] {path.name} — file not found")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"  [ERROR] {path.name} — invalid JSON: {e}")
        return None


# ── Migration functions ───────────────────────────────────────────────────────

def migrate_experiments(conn, dry_run: bool) -> int:
    """Migrate experiment_history.json -> experiments table.

    Handles 3 different record formats that evolved over time:
    - Format A (early): {topic, score, success, timestamp}
    - Format B (NightRunner v2): {timestamp, topic, strategy_used, error_type, ...}
    - Format C (SSJ5 fix): {topic, score, success, timestamp, failure_reason, source, ...}
    """
    data = _load_json(FILES["experiment_history"])
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for entry in data:
        # Normalize across all 3 formats
        topic = entry.get("topic", "")
        timestamp = entry.get("timestamp", "")

        # Score: some formats use "score", others "evaluation_score"
        score = entry.get("score")
        if score is None:
            score = entry.get("evaluation_score")

        # Certified: some formats use "success" (misleading), others "certified"
        certified = entry.get("certified")
        if certified is None:
            # In Format A, "success" actually meant certified (score >= 7.5)
            certified = entry.get("success", False)
        certified = 1 if certified else 0

        sandbox_success = entry.get("sandbox_success")
        if sandbox_success is not None:
            sandbox_success = 1 if sandbox_success else 0

        # JSON arrays -> store as JSON strings
        strategies_reused = json.dumps(entry.get("strategies_reused", []))
        skills_unlocked = json.dumps(entry.get("skills_unlocked", []))
        files_modified = json.dumps(entry.get("files_modified", []))

        rows.append((
            topic,
            score,
            certified,
            sandbox_success,
            timestamp,
            None,                                   # category (computed later by meta_learning)
            entry.get("source"),
            entry.get("failure_reason"),
            entry.get("strategy_used"),
            entry.get("previous_score"),
            entry.get("duration_minutes"),
            entry.get("error_type"),
            entry.get("error_signature"),
            entry.get("attempts", 1),
            entry.get("verdict"),
            strategies_reused,
            skills_unlocked,
            files_modified,
        ))

    if dry_run:
        print(f"  [DRY RUN] Would insert {len(rows)} experiments")
        return len(rows)

    conn.executemany(
        """INSERT OR IGNORE INTO experiments
           (topic, score, certified, sandbox_success, timestamp, category,
            source, failure_reason, strategy_used, previous_score,
            duration_min, error_type, error_signature, attempts, verdict,
            strategies_reused, skills_unlocked, files_modified)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()

    # Now backfill category from meta_learning sessions
    _backfill_categories(conn)

    return len(rows)


def _backfill_categories(conn) -> int:
    """Backfill category column from meta_learning.json sessions."""
    data = _load_json(FILES["meta_learning"])
    if not data or "sessions" not in data:
        return 0

    updated = 0
    for session in data["sessions"]:
        topic = session.get("topic", "")
        category = session.get("category")
        if topic and category:
            cursor = conn.execute(
                "UPDATE experiments SET category = ? WHERE topic = ? AND category IS NULL",
                (category, topic),
            )
            updated += cursor.rowcount
    conn.commit()
    return updated


def migrate_failed_cache(conn, dry_run: bool) -> int:
    """Migrate failed_cache.json -> failed_cache table."""
    data = _load_json(FILES["failed_cache"])
    if not data or not isinstance(data, dict):
        return 0

    rows = [(topic, skill_count, datetime.now().isoformat())
            for topic, skill_count in data.items()]

    if dry_run:
        print(f"  [DRY RUN] Would insert {len(rows)} failed cache entries")
        return len(rows)

    conn.executemany(
        "INSERT OR IGNORE INTO failed_cache (topic, skill_count_at_fail, last_failed_at) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def migrate_capabilities(conn, dry_run: bool) -> int:
    """Migrate capability_graph.json -> capabilities + capability_deps tables."""
    data = _load_json(FILES["capability_graph"])
    if not data or not isinstance(data, dict):
        return 0

    if dry_run:
        print(f"  [DRY RUN] Would insert {len(data)} capabilities")
        return len(data)

    # Phase 1: Insert all capabilities
    cap_rows = []
    for name, meta in data.items():
        cap_rows.append((
            name.lower().strip(),
            meta.get("source_topic", ""),
            meta.get("acquired", datetime.now().isoformat()),
        ))

    conn.executemany(
        "INSERT OR IGNORE INTO capabilities (name, source_topic, acquired_at) VALUES (?, ?, ?)",
        cap_rows,
    )
    conn.commit()

    # Phase 2: Insert dependency edges
    dep_rows = []
    for name, meta in data.items():
        requires = meta.get("requires", [])
        if requires:
            # Look up the capability id
            row = conn.execute(
                "SELECT id FROM capabilities WHERE name = ?",
                (name.lower().strip(),)
            ).fetchone()
            if row:
                cap_id = row["id"]
                for req in requires:
                    dep_rows.append((cap_id, req.lower().strip()))

    if dep_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO capability_deps (capability_id, requires_name) VALUES (?, ?)",
            dep_rows,
        )
        conn.commit()

    return len(cap_rows)


def migrate_improvement_queue(conn, dry_run: bool) -> int:
    """Migrate improvement_queue.json -> improvement_tickets + kv_store."""
    data = _load_json(FILES["improvement_queue"])
    if not data or not isinstance(data, dict):
        return 0

    # Store processed ticket IDs as already-processed tickets
    processed = data.get("processed_ticket_ids", [])
    now = datetime.now().isoformat()

    rows = [(tid, "migrated", "processed", None, None, 0, "processed", now, now)
            for tid in processed]

    # Store pending queue items
    for item in data.get("pending_queue", []):
        rows.append((
            item.get("id", f"migrated_{len(rows)}"),
            item.get("ticket_type", "unknown"),
            item.get("action"),
            item.get("topic"),
            item.get("reason"),
            item.get("priority", 0),
            "pending",
            now,
            None,
        ))

    if dry_run:
        print(f"  [DRY RUN] Would insert {len(rows)} improvement tickets")
        return len(rows)

    conn.executemany(
        """INSERT OR IGNORE INTO improvement_tickets
           (id, ticket_type, action, topic, reason, priority, status, created_at, processed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )

    # Store metadata in kv_store
    conn.execute(
        "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
        ("total_topics_ever_queued", str(data.get("total_topics_ever_queued", 0))),
    )
    conn.execute(
        "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
        ("improvement_last_run_at", data.get("last_run_at", now)),
    )
    conn.commit()
    return len(rows)


def migrate_refactor_state(conn, dry_run: bool) -> int:
    """Migrate refactor_state.json -> refactor_history + kv_store."""
    data = _load_json(FILES["refactor_state"])
    if not data or not isinstance(data, dict):
        return 0

    history = data.get("history", [])

    if dry_run:
        print(f"  [DRY RUN] Would insert {len(history)} refactor records")
        return len(history)

    rows = []
    for entry in history:
        rows.append((
            entry.get("id", ""),
            entry.get("file", ""),
            entry.get("description", ""),
            entry.get("category", ""),
            entry.get("rationale", ""),
            json.dumps(entry.get("changes", [])),
            entry.get("status", "unknown"),
            entry.get("timestamp", ""),
            entry.get("applied_at"),
            entry.get("backup"),
        ))

    conn.executemany(
        """INSERT OR IGNORE INTO refactor_history
           (id, file_path, description, category, rationale, changes,
            status, created_at, applied_at, backup_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )

    # Store round-robin index
    conn.execute(
        "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
        ("refactor_current_index", str(data.get("current_index", 0))),
    )
    conn.commit()
    return len(rows)


# ── Verification ──────────────────────────────────────────────────────────────

def verify(conn) -> bool:
    """Verify migration integrity by comparing counts."""
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    all_ok = True

    # Experiments
    json_data = _load_json(FILES["experiment_history"])
    json_count = len(json_data) if json_data else 0
    db_count = conn.execute("SELECT COUNT(*) as c FROM experiments").fetchone()["c"]
    status = "OK" if db_count >= json_count else "MISMATCH"
    if status == "MISMATCH":
        all_ok = False
    print(f"  experiments:     JSON={json_count:>4}  DB={db_count:>4}  [{status}]")

    # Note: db_count may be less than json_count due to INSERT OR IGNORE
    # deduplicating entries with identical rowids. This is expected.
    # What matters is no data was silently dropped.

    # Failed cache
    json_data = _load_json(FILES["failed_cache"])
    json_count = len(json_data) if json_data and isinstance(json_data, dict) else 0
    db_count = conn.execute("SELECT COUNT(*) as c FROM failed_cache").fetchone()["c"]
    status = "OK" if db_count == json_count else "MISMATCH"
    if status == "MISMATCH":
        all_ok = False
    print(f"  failed_cache:    JSON={json_count:>4}  DB={db_count:>4}  [{status}]")

    # Capabilities
    json_data = _load_json(FILES["capability_graph"])
    json_count = len(json_data) if json_data and isinstance(json_data, dict) else 0
    db_count = conn.execute("SELECT COUNT(*) as c FROM capabilities").fetchone()["c"]
    status = "OK" if db_count == json_count else "MISMATCH"
    if status == "MISMATCH":
        all_ok = False
    print(f"  capabilities:    JSON={json_count:>4}  DB={db_count:>4}  [{status}]")

    # Capability deps
    db_deps = conn.execute("SELECT COUNT(*) as c FROM capability_deps").fetchone()["c"]
    # Count deps from JSON
    json_deps = 0
    if json_data and isinstance(json_data, dict):
        for meta in json_data.values():
            json_deps += len(meta.get("requires", []))
    status = "OK" if db_deps == json_deps else "MISMATCH"
    if status == "MISMATCH":
        all_ok = False
    print(f"  capability_deps: JSON={json_deps:>4}  DB={db_deps:>4}  [{status}]")

    # Improvement tickets
    json_data = _load_json(FILES["improvement_queue"])
    json_count = len(json_data.get("processed_ticket_ids", [])) + len(json_data.get("pending_queue", [])) if json_data else 0
    db_count = conn.execute("SELECT COUNT(*) as c FROM improvement_tickets").fetchone()["c"]
    status = "OK" if db_count == json_count else "MISMATCH"
    if status == "MISMATCH":
        all_ok = False
    print(f"  tickets:         JSON={json_count:>4}  DB={db_count:>4}  [{status}]")

    # Refactor history
    json_data = _load_json(FILES["refactor_state"])
    json_count = len(json_data.get("history", [])) if json_data else 0
    db_count = conn.execute("SELECT COUNT(*) as c FROM refactor_history").fetchone()["c"]
    status = "OK" if db_count == json_count else "MISMATCH"
    if status == "MISMATCH":
        all_ok = False
    print(f"  refactor_hist:   JSON={json_count:>4}  DB={db_count:>4}  [{status}]")

    # Views sanity check
    phoenix = conn.execute("SELECT COUNT(*) as c FROM phoenix_candidates").fetchone()["c"]
    quarantined = conn.execute("SELECT COUNT(*) as c FROM quarantined_topics").fetchone()["c"]
    categories = conn.execute("SELECT COUNT(*) as c FROM category_stats").fetchone()["c"]
    global_s = conn.execute("SELECT * FROM global_stats").fetchone()
    print(f"\n  VIEWS:")
    print(f"    phoenix_candidates:  {phoenix} topics eligible for retry")
    print(f"    quarantined_topics:  {quarantined} topics blocked")
    print(f"    category_stats:      {categories} categories tracked")
    if global_s:
        print(f"    global_stats:        {global_s['total_sessions']} sessions, "
              f"{global_s['certified_count']} certified, "
              f"{global_s['cert_rate']:.1%} rate")

    # Sample data integrity check
    print(f"\n  SAMPLE CAPABILITIES (first 5):")
    for row in conn.execute("SELECT name, source_topic, acquired_at FROM capabilities ORDER BY acquired_at LIMIT 5").fetchall():
        print(f"    {row['name']:<40} src={row['source_topic']:<30} at={row['acquired_at'][:19]}")

    print(f"\n  SAMPLE EXPERIMENTS (last 5):")
    for row in conn.execute("SELECT topic, score, certified, timestamp FROM experiments ORDER BY timestamp DESC LIMIT 5").fetchall():
        cert = "CERT" if row["certified"] else "FAIL"
        score = f"{row['score']:.1f}" if row["score"] is not None else "N/A"
        print(f"    [{cert}] {score:>5}  {row['topic'][:50]}")

    return all_ok


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Migrate SHARD JSON files to SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without writing")
    args = parser.parse_args()

    print("=" * 60)
    print("SHARD JSON -> SQLite Migration")
    print(f"Database: {DB_PATH}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    if args.dry_run:
        print("MODE: DRY RUN (no writes)")
    print("=" * 60)

    conn = get_db()

    # Check if already migrated
    existing = conn.execute("SELECT COUNT(*) as c FROM experiments").fetchone()["c"]
    if existing > 0 and not args.dry_run:
        print(f"\n  [WARNING] Database already contains {existing} experiments.")
        print(f"  Using INSERT OR IGNORE — existing records will be preserved.")

    print()

    # Migration steps
    steps = [
        ("Experiments (experiment_history.json)", migrate_experiments),
        ("Failed Cache (failed_cache.json)", migrate_failed_cache),
        ("Capabilities (capability_graph.json)", migrate_capabilities),
        ("Improvement Queue (improvement_queue.json)", migrate_improvement_queue),
        ("Refactor State (refactor_state.json)", migrate_refactor_state),
    ]

    total = 0
    for label, func in steps:
        print(f"  Migrating: {label}")
        count = func(conn, args.dry_run)
        total += count
        print(f"    -> {count} records\n")

    print(f"  TOTAL: {total} records migrated")

    if not args.dry_run:
        ok = verify(conn)
        print("\n" + "=" * 60)
        if ok:
            print("MIGRATION COMPLETE — All counts verified OK")
            print(f"Database: {DB_PATH}")
            print(f"Size: {os.path.getsize(DB_PATH) / 1024:.1f} KB")
        else:
            print("MIGRATION COMPLETE — Some counts don't match (check above)")
            print("This may be expected if records were deduplicated.")
        print("=" * 60)
    else:
        print("\n  [DRY RUN] No changes written. Remove --dry-run to execute.")


if __name__ == "__main__":
    main()
