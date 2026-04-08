#!/usr/bin/env python3
"""migrate_jsonl_to_sqlite.py -- One-shot migration of .jsonl files to SQLite.

Migrates:
  - predictions.jsonl        -> predictions table
  - self_inconsistencies.jsonl -> self_inconsistencies table
  - session_reflections.jsonl  -> session_reflections table
  - desire_state.json          -> kv_store (key='desire_state')

Safe to run multiple times -- uses INSERT OR IGNORE where possible.
Creates a backup of shard.db before any writes.

Usage:
    python backend/migrate_jsonl_to_sqlite.py [--dry-run]
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARD_MEMORY = ROOT / "shard_memory"
DB_PATH = SHARD_MEMORY / "shard.db"

sys.path.insert(0, str(Path(__file__).parent))


def backup_db() -> Path:
    bak = DB_PATH.with_suffix(".db.bak")
    shutil.copy2(str(DB_PATH), str(bak))
    print(f"[BACKUP] {bak}")
    return bak


def migrate_predictions(db, dry_run: bool) -> int:
    path = SHARD_MEMORY / "predictions.jsonl"
    if not path.exists():
        print("[SKIP] predictions.jsonl not found")
        return 0
    existing = db.execute("SELECT COUNT(*) AS n FROM predictions").fetchone()["n"]
    if existing > 0:
        print(f"[SKIP] predictions table already has {existing} rows")
        return 0
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            rows.append((
                r.get("topic", ""),
                r.get("predicted"),
                r.get("actual"),
                r.get("error"),
                1 if r.get("certified") else 0,
                json.dumps(r.get("features") or {}),
                r.get("context", ""),
                r.get("timestamp", ""),
            ))
        except Exception as e:
            print(f"[WARN] predictions parse error: {e}")
    if not dry_run:
        db.executemany(
            "INSERT INTO predictions (topic,predicted,actual,error,certified,features,context,ts) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        db.commit()
    print(f"[predictions] {'would insert' if dry_run else 'inserted'} {len(rows)} rows")
    if not dry_run:
        path.rename(path.with_suffix(".jsonl.migrated"))
    return len(rows)


def migrate_inconsistencies(db, dry_run: bool) -> int:
    path = SHARD_MEMORY / "self_inconsistencies.jsonl"
    if not path.exists():
        print("[SKIP] self_inconsistencies.jsonl not found")
        return 0
    existing = db.execute("SELECT COUNT(*) AS n FROM self_inconsistencies").fetchone()["n"]
    if existing > 0:
        print(f"[SKIP] self_inconsistencies table already has {existing} rows")
        return 0
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            # Two schemas: self_model (feature/gap) and cert_contradiction (contradiction_type)
            event_type = r.get("event", "inconsistency")
            rows.append((
                r.get("topic", ""),
                event_type,
                r.get("feature", ""),
                r.get("context", ""),
                r.get("global_w"),
                r.get("contextual_w"),
                r.get("gap"),
                r.get("error"),
                r.get("severity"),
                r.get("resolution"),
                r.get("explanation"),
                json.dumps({k: v for k, v in r.items()
                            if k not in ("topic", "feature", "context", "global_w",
                                         "contextual_w", "gap", "error", "severity",
                                         "resolution", "explanation", "timestamp", "event")}),
                r.get("timestamp", ""),
            ))
        except Exception as e:
            print(f"[WARN] inconsistencies parse error: {e}")
    if not dry_run:
        db.executemany(
            "INSERT INTO self_inconsistencies "
            "(topic,event_type,feature,context,global_w,contextual_w,gap,error,"
            "severity,resolution,explanation,extra,ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        db.commit()
    print(f"[self_inconsistencies] {'would insert' if dry_run else 'inserted'} {len(rows)} rows")
    if not dry_run:
        path.rename(path.with_suffix(".jsonl.migrated"))
    return len(rows)


def migrate_reflections(db, dry_run: bool) -> int:
    path = SHARD_MEMORY / "session_reflections.jsonl"
    if not path.exists():
        print("[SKIP] session_reflections.jsonl not found")
        return 0
    existing = db.execute("SELECT COUNT(*) AS n FROM session_reflections").fetchone()["n"]
    if existing > 0:
        print(f"[SKIP] session_reflections table already has {existing} rows")
        return 0
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            certified = r.get("certified", [])
            failed = r.get("failed", [])
            rows.append((
                r.get("session_id", ""),
                r.get("ts", ""),
                json.dumps(certified) if isinstance(certified, list) else str(certified),
                json.dumps(failed) if isinstance(failed, list) else str(failed),
                r.get("text", ""),
            ))
        except Exception as e:
            print(f"[WARN] reflections parse error: {e}")
    if not dry_run:
        db.executemany(
            "INSERT INTO session_reflections (session_id,ts,certified,failed,text) "
            "VALUES (?,?,?,?,?)",
            rows,
        )
        db.commit()
    print(f"[session_reflections] {'would insert' if dry_run else 'inserted'} {len(rows)} rows")
    if not dry_run:
        path.rename(path.with_suffix(".jsonl.migrated"))
    return len(rows)


def migrate_desire(db, dry_run: bool) -> int:
    path = SHARD_MEMORY / "desire_state.json"
    if not path.exists():
        print("[SKIP] desire_state.json not found")
        return 0
    existing = db.execute(
        "SELECT value FROM kv_store WHERE key='desire_state'"
    ).fetchone()
    if existing:
        print("[SKIP] desire_state already in kv_store")
        return 0
    data = path.read_text(encoding="utf-8", errors="replace")
    if not dry_run:
        db.execute(
            "INSERT OR REPLACE INTO kv_store (key, value) VALUES ('desire_state', ?)",
            (data,),
        )
        db.commit()
        path.rename(path.with_suffix(".json.migrated"))
    print(f"[desire_state] {'would insert' if dry_run else 'inserted'} {len(json.loads(data))} topics into kv_store")
    return 1


def main():
    parser = argparse.ArgumentParser(description="Migrate .jsonl files to SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen, no writes")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}")
        sys.exit(1)

    if not args.dry_run:
        backup_db()

    # Import after path setup so shard_db finds the right DB
    from shard_db import get_db
    db = get_db()

    total = 0
    total += migrate_predictions(db, args.dry_run)
    total += migrate_inconsistencies(db, args.dry_run)
    total += migrate_reflections(db, args.dry_run)
    total += migrate_desire(db, args.dry_run)

    print(f"\n[DONE] {'Would migrate' if args.dry_run else 'Migrated'} {total} records total")
    if not args.dry_run:
        print("[INFO] Original .jsonl/.json files renamed to *.migrated")
        print("[INFO] Backup at:", DB_PATH.with_suffix(".db.bak"))


if __name__ == "__main__":
    main()
