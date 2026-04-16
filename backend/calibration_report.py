"""calibration_report.py — post-run alignment calibration analysis.

Usage:
    python backend/calibration_report.py [path/to/alignment_log_*.jsonl]

If no path given, uses the most recent alignment_log_*.jsonl in
shard_workspace/experiments/.
"""
import glob
import json
import os
import sys
from collections import defaultdict

EXPERIMENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "shard_workspace", "experiments"
)

def find_latest_log() -> str | None:
    logs = sorted(
        glob.glob(os.path.join(EXPERIMENTS_DIR, "alignment_log_*.jsonl")),
        key=os.path.getmtime,
    )
    return logs[-1] if logs else None

def load_records(path: str) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records

def analyse(records: list[dict]) -> None:
    if not records:
        print("No records found.")
        return

    total = len(records)
    valid_recs    = [r for r in records if r.get("final_verdict") == "VALID"]
    invalid_recs  = [r for r in records if r.get("final_verdict") == "INVALID"]
    exhausted_recs = [r for r in records if r.get("final_verdict") == "REWRITE_EXHAUSTED"]

    had_rewrite   = [r for r in records if r.get("num_rewrites", 0) > 0]
    rewrite_valid = [r for r in had_rewrite if r.get("final_verdict") == "VALID"]
    rewrite_bad   = [r for r in had_rewrite if r.get("final_verdict") != "VALID"]

    kaggle_count  = sum(1 for r in records if r.get("kaggle_feasible"))

    def avg_score_for(recs: list[dict]) -> float:
        scores = []
        for r in recs:
            for a in r.get("attempts", []):
                if a.get("verdict") == r.get("final_verdict") or r.get("final_verdict") == "VALID" and a.get("verdict") == "VALID":
                    scores.append(a.get("score", 0.0))
                    break
        return sum(scores) / len(scores) if scores else 0.0

    print("=" * 60)
    print(f"ALIGNMENT CALIBRATION REPORT  ({total} hypotheses)")
    print("=" * 60)

    print(f"\n--- DISTRIBUTION ---")
    print(f"  VALID              : {len(valid_recs):3d}  ({100*len(valid_recs)/total:.0f}%)")
    print(f"  INVALID            : {len(invalid_recs):3d}  ({100*len(invalid_recs)/total:.0f}%)")
    print(f"  REWRITE_EXHAUSTED  : {len(exhausted_recs):3d}  ({100*len(exhausted_recs)/total:.0f}%)")
    print(f"  Had >= 1 rewrite   : {len(had_rewrite):3d}  ({100*len(had_rewrite)/total:.0f}%)")

    print(f"\n--- REWRITE QUALITY ---")
    if had_rewrite:
        print(f"  REWRITE -> VALID   : {len(rewrite_valid):3d}  ({100*len(rewrite_valid)/len(had_rewrite):.0f}%)")
        print(f"  REWRITE -> FAIL    : {len(rewrite_bad):3d}  ({100*len(rewrite_bad)/len(had_rewrite):.0f}%)")
    else:
        print("  No rewrites observed.")

    print(f"\n--- SCORES ---")
    v_scores = [a.get("score", 0.0) for r in valid_recs for a in r.get("attempts", []) if a.get("verdict") == "VALID"]
    i_scores = [a.get("score", 0.0) for r in invalid_recs for a in r.get("attempts", []) if a.get("verdict") == "INVALID"]
    if v_scores:
        print(f"  Avg score @ VALID  : {sum(v_scores)/len(v_scores):.3f}")
    if i_scores:
        print(f"  Avg score @ INVALID: {sum(i_scores)/len(i_scores):.3f}")

    print(f"\n--- KAGGLE ---")
    print(f"  Flagged kaggle     : {kaggle_count:3d}  ({100*kaggle_count/total:.0f}%)")

    # ── Domain diversity check ─────────────────────────────────────────────
    domain_pairs = defaultdict(int)
    for r in records:
        pair = f"{r.get('domain_from','?')} -> {r.get('domain_to','?')}"
        domain_pairs[pair] += 1
    top_pairs = sorted(domain_pairs.items(), key=lambda x: -x[1])[:5]
    print(f"\n--- DOMAIN PAIRS (top {len(top_pairs)}) ---")
    for pair, cnt in top_pairs:
        print(f"  {cnt:2d}x  {pair}")

    # ── Diagnosis ─────────────────────────────────────────────────────────
    valid_pct = 100 * len(valid_recs) / total
    rewrite_pct = 100 * len(had_rewrite) / total

    print(f"\n--- DIAGNOSIS ---")
    if valid_pct < 30:
        print("  [!] Caso A — TROPPO SEVERO: VALID < 30%.")
        print("      Abbassa soglia VALID (0.70 -> 0.60) o allarga prompt validator.")
    elif valid_pct > 70 and total >= 5:
        print("  [!] Caso B — TROPPO PERMISSIVO: VALID > 70%.")
        print("      Alza soglia o rafforza criterio CAUSAL_LINK nel prompt.")
    elif rewrite_pct > 50:
        print("  [!] Caso C — REWRITE DOMINANTE: generator debole.")
        print("      Migliora prompt SynthesizePhase (non il validator).")
    elif had_rewrite and len(rewrite_bad) / len(had_rewrite) > 0.5:
        print("  [!] Caso D — REWRITE INEFFICACE: molti REWRITE -> FAIL.")
        print("      Forzare rewrite piu strutturato nel prompt validator.")
    else:
        print("  [OK] Distribuzione nei range accettabili.")

    # ── Sample output for manual review ───────────────────────────────────
    print(f"\n--- SAMPLE: 3 VALID (sanity check) ---")
    for r in valid_recs[:3]:
        score = next((a["score"] for a in r.get("attempts", []) if a.get("verdict") == "VALID"), "?")
        print(f"  score={score}  rewrites={r.get('num_rewrites',0)}  hyp: {r.get('hypothesis','')[:80]}")

    print(f"\n--- SAMPLE: 3 INVALID (false positive check) ---")
    for r in (invalid_recs + exhausted_recs)[:3]:
        score = next((a["score"] for a in r.get("attempts", [])), "?")
        print(f"  score={score}  verdict={r.get('final_verdict')}  hyp: {r.get('hypothesis','')[:80]}")

    print("=" * 60)
    print(f"Log: {path if 'path' in dir() else '(loaded)'}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = find_latest_log()

    if not path or not os.path.exists(path):
        print(f"No alignment log found in {EXPERIMENTS_DIR}")
        sys.exit(1)

    print(f"Loading: {path}")
    records = load_records(path)
    analyse(records)
