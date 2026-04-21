"""
verify_graphrag.py — Verify causal relations in the knowledge_graph via Groq.

Each relation is queried twice. Agreement → verified/disputed. Disagreement → unsure.
Results are written to the verified_status column (never deletes relations).

Usage:
    python backend/verify_graphrag.py            # all relations with confidence > 0.6
    python backend/verify_graphrag.py --limit 10 # test on 10 first
    python backend/verify_graphrag.py --retry    # re-check only unsure/null
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shard_db import execute as db_exec, query as db_query


# ── Migration: add verified_status column if missing ──────────────────────────

def _ensure_column() -> None:
    try:
        db_exec("ALTER TABLE knowledge_graph ADD COLUMN verified_status TEXT DEFAULT NULL")
        print("[VERIFY] Added column verified_status to knowledge_graph.")
    except Exception:
        pass  # column already exists — normal


# ── Groq call ─────────────────────────────────────────────────────────────────

def _get_groq_client():
    key = os.getenv("GROQ_API_KEY")
    if not key:
        _env = Path(__file__).parent.parent / ".env"
        if _env.exists():
            for line in _env.read_text().splitlines():
                if line.startswith("GROQ_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise RuntimeError("GROQ_API_KEY not set. Add it to .env or export it.")
    from groq import Groq
    return Groq(api_key=key)


def _ask(client, source: str, relation: str, target: str, domain: str, context: str) -> str:
    """Ask Groq once. Returns 'yes', 'no', or 'unsure'."""
    ctx_line = f"\nContext: {context}" if context and context.strip() else ""
    prompt = (
        f"In the domain of {domain}, is it true that "
        f"'{source} {relation} {target}'?{ctx_line}\n"
        "Answer only: yes, no, or unsure."
    )
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0,
        )
        text = resp.choices[0].message.content.strip().lower()
        if re.search(r"\byes\b", text):
            return "yes"
        if re.search(r"\bno\b", text):
            return "no"
        return "unsure"
    except Exception as e:
        print(f"  [WARN] Groq error: {e}")
        return "unsure"


def _decide(a: str, b: str) -> str:
    if a == "yes"  and b == "yes":  return "verified"
    if a == "no"   and b == "no":   return "disputed"
    return "unsure"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Verify knowledge_graph relations via Groq.")
    parser.add_argument("--limit", type=int, default=0, help="Process only N relations (0 = all)")
    parser.add_argument("--retry", action="store_true", help="Re-check null and unsure only")
    args = parser.parse_args()

    _ensure_column()

    where = "confidence > 0.6"
    if args.retry:
        where += " AND (verified_status IS NULL OR verified_status = 'unsure')"
    else:
        where += " AND verified_status IS NULL"

    limit_clause = f"LIMIT {args.limit}" if args.limit > 0 else ""
    rows = db_query(
        f"SELECT id, source_concept, relation_type, target_concept, "
        f"confidence, topic_origin, context FROM knowledge_graph "
        f"WHERE {where} ORDER BY confidence DESC {limit_clause}"
    )

    total = len(rows)
    print(f"[VERIFY] Relations to check: {total}")
    if total == 0:
        print("[VERIFY] Nothing to do.")
        return

    client = _get_groq_client()

    verified = disputed = unsure = errors = 0

    for i, row in enumerate(rows, 1):
        rid      = row["id"]
        source   = row["source_concept"]
        relation = row["relation_type"]
        target   = row["target_concept"]
        domain   = row["topic_origin"] or "general"
        context  = row["context"] or ""

        print(f"[{i}/{total}] {source} {relation} {target}  (conf={row['confidence']:.2f})", end="  ")

        ans1 = _ask(client, source, relation, target, domain, context)
        time.sleep(0.5)
        ans2 = _ask(client, source, relation, target, domain, context)
        time.sleep(0.5)

        status = _decide(ans1, ans2)
        print(f"{ans1}+{ans2} -> {status}")

        if status == "unsure" and ans1 == "unsure" and ans2 == "unsure":
            print(f"  [NOTE] Both answers unsure — relation may be too abstract.")

        db_exec(
            "UPDATE knowledge_graph SET verified_status=? WHERE id=?",
            (status, rid)
        )

        if status == "verified":   verified  += 1
        elif status == "disputed": disputed  += 1
        else:                      unsure    += 1

    print(f"\n[VERIFY] Done. verified={verified} disputed={disputed} unsure={unsure}")
    print(f"[VERIFY] Total processed: {verified + disputed + unsure} / {total}")


if __name__ == "__main__":
    main()
