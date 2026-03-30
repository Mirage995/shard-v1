"""clean_strategy_db.py -- One-shot cleanup of strategy_memory ChromaDB.

Splits 442 entries into:
  KEEP       -- short, actionable, no noise markers
  QUARANTINE -- borderline (saved to JSON, removed from DB)
  DELETE     -- clear junk (noise markers present)

Run once:
  cd backend && python clean_strategy_db.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

QUARANTINE_FILE = ROOT / "shard_workspace" / "strategy_quarantine.json"

# ── Filter logic (same as strategy_memory._is_noise / _looks_actionable) ──────

NOISE_MARKERS = [
    "sandbox:", "success --", "traceback", "concepts:",
    "gaps identified:", "focus on:", "stdout", "output:",
    "code executed", "failed to", "docker", "success\xe2",  # "SUCCESS --" with em-dash
    "| sandbox", "| concepts", "| gaps", "| output",
]

ACTION_VERBS = [
    "use ", "replace ", "add ", "ensure ", "avoid ",
    "check ", "return ", "wrap ", "initialize ", "apply ",
    "acquire ", "sort ", "copy ", "deepcopy", "guard",
]


def is_noise(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in NOISE_MARKERS)


def looks_actionable(text: str) -> bool:
    if len(text) > 300:
        return False
    t = text.lower()
    return any(v in t for v in ACTION_VERBS)


def main() -> None:
    from strategy_memory import StrategyMemory

    sm = StrategyMemory()
    total = sm.collection.count()
    print(f"[cleanup] DB has {total} entries")

    if total == 0:
        print("[cleanup] Nothing to clean.")
        return

    # Fetch ALL entries (ChromaDB: include documents + metadatas + ids)
    all_data = sm.collection.get(include=["documents", "metadatas"])
    ids       = all_data["ids"]
    docs      = all_data["documents"]
    metas     = all_data["metadatas"]

    keep_ids       = []
    delete_ids     = []
    quarantine_ids = []
    quarantine_records = []

    for doc_id, doc, meta in zip(ids, docs, metas):
        if is_noise(doc):
            delete_ids.append(doc_id)
        elif looks_actionable(doc):
            keep_ids.append(doc_id)
        else:
            # Borderline -- quarantine
            quarantine_ids.append(doc_id)
            quarantine_records.append({"id": doc_id, "text": doc, "meta": meta})

    print(f"[cleanup] KEEP={len(keep_ids)}  QUARANTINE={len(quarantine_ids)}  DELETE={len(delete_ids)}")

    # Save quarantine to JSON before touching DB
    QUARANTINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_q = []
    if QUARANTINE_FILE.exists():
        try:
            existing_q = json.loads(QUARANTINE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing_q.extend(quarantine_records)
    QUARANTINE_FILE.write_text(json.dumps(existing_q, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[cleanup] Quarantine saved -> {QUARANTINE_FILE} ({len(quarantine_records)} new entries)")

    # Delete noise + quarantine from DB
    to_remove = delete_ids + quarantine_ids
    if to_remove:
        # ChromaDB delete in batches of 100
        batch = 100
        for i in range(0, len(to_remove), batch):
            sm.collection.delete(ids=to_remove[i:i + batch])
        print(f"[cleanup] Removed {len(to_remove)} entries from DB ({len(delete_ids)} noise, {len(quarantine_ids)} quarantine)")
    else:
        print("[cleanup] Nothing to remove.")

    remaining = sm.collection.count()
    print(f"[cleanup] DB after cleanup: {remaining} entries")
    print(f"[cleanup] Done.")


if __name__ == "__main__":
    main()
