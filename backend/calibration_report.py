"""calibration_report.py — post-run alignment calibration analysis.

Usage:
    python backend/calibration_report.py [path/to/alignment_log_*.jsonl]
    python backend/calibration_report.py --all   # aggregate all logs

If no path given, uses the most recent alignment_log_*.jsonl in
shard_workspace/experiments/.
"""
import glob
import json
import math
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

def find_all_logs() -> list[str]:
    return sorted(
        glob.glob(os.path.join(EXPERIMENTS_DIR, "alignment_log_*.jsonl")),
        key=os.path.getmtime,
    )

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

def _entropy(counts: dict) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((v/total) * math.log2(v/total) for v in counts.values() if v > 0)

def analyse(records: list[dict], path: str = "") -> None:
    if not records:
        print("No records found.")
        return

    total = len(records)
    valid_recs     = [r for r in records if r.get("final_verdict") == "VALID"]
    invalid_recs   = [r for r in records if r.get("final_verdict") == "INVALID"]
    exhausted_recs = [r for r in records if r.get("final_verdict") == "REWRITE_EXHAUSTED"]

    had_rewrite   = [r for r in records if r.get("num_rewrites", 0) > 0]
    rewrite_valid = [r for r in had_rewrite if r.get("final_verdict") == "VALID"]
    rewrite_bad   = [r for r in had_rewrite if r.get("final_verdict") != "VALID"]

    kaggle_count  = sum(1 for r in records if r.get("kaggle_feasible"))

    print("=" * 65)
    print(f"ALIGNMENT CALIBRATION REPORT  ({total} hypotheses)")
    print("=" * 65)

    # ── Distribution ──────────────────────────────────────────────────────
    print(f"\n--- DISTRIBUTION ---")
    print(f"  VALID              : {len(valid_recs):3d}  ({100*len(valid_recs)/total:.0f}%)")
    print(f"  INVALID            : {len(invalid_recs):3d}  ({100*len(invalid_recs)/total:.0f}%)")
    print(f"  REWRITE_EXHAUSTED  : {len(exhausted_recs):3d}  ({100*len(exhausted_recs)/total:.0f}%)")
    print(f"  Had >= 1 rewrite   : {len(had_rewrite):3d}  ({100*len(had_rewrite)/total:.0f}%)")

    # ── Rewrite quality ───────────────────────────────────────────────────
    print(f"\n--- REWRITE QUALITY ---")
    if had_rewrite:
        print(f"  REWRITE -> VALID   : {len(rewrite_valid):3d}  ({100*len(rewrite_valid)/len(had_rewrite):.0f}%)")
        print(f"  REWRITE -> FAIL    : {len(rewrite_bad):3d}  ({100*len(rewrite_bad)/len(had_rewrite):.0f}%)")
    else:
        print("  No rewrites observed.")

    # ── Protocol compliance ───────────────────────────────────────────────
    all_attempts = [a for r in records for a in r.get("attempts", [])]
    invalid_format = [a for a in all_attempts if a.get("evaluation_status") in ("INVALID_FORMAT", "MODEL_FAILURE")]
    no_criteria    = [a for a in all_attempts if not a.get("criteria") and a.get("evaluation_status","VALID") == "VALID"]

    # ── Alignment score distribution ──────────────────────────────────────
    # Only include attempts with real numeric scores (skip None = protocol failure)
    all_scores = []
    for r in records:
        for a in r.get("attempts", []):
            if a.get("verdict") == r.get("final_verdict") or (
                r.get("final_verdict") == "VALID" and a.get("verdict") == "VALID"
            ):
                s = a.get("score")
                if s is not None:
                    all_scores.append(float(s))
                break

    print(f"\n--- PROTOCOL COMPLIANCE ---")
    print(f"  Total attempts     : {len(all_attempts)}")
    if invalid_format:
        print(f"  [!] INVALID_FORMAT / MODEL_FAILURE : {len(invalid_format)}  "
              f"({100*len(invalid_format)/len(all_attempts):.0f}%)")
    if no_criteria:
        print(f"  [!] Missing criteria (schema drift): {len(no_criteria)}  "
              f"({100*len(no_criteria)/len(all_attempts):.0f}%)")
    if not invalid_format and not no_criteria:
        print(f"  [OK] All attempts returned valid schema")

    print(f"\n--- ALIGNMENT SCORES ---")
    none_scores = len(all_attempts) - len(all_scores)
    if none_scores:
        print(f"  [!] {none_scores} attempts had score=None (protocol failure, excluded)")
    if all_scores:
        avg = sum(all_scores) / len(all_scores)
        buckets = {"<0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.9": 0, ">=0.9": 0}
        for s in all_scores:
            if s < 0.3:       buckets["<0.3"] += 1
            elif s < 0.5:     buckets["0.3-0.5"] += 1
            elif s < 0.7:     buckets["0.5-0.7"] += 1
            elif s < 0.9:     buckets["0.7-0.9"] += 1
            else:             buckets[">=0.9"] += 1
        print(f"  Average            : {avg:.3f}")
        print(f"  Distribution       : " + "  ".join(f"{k}:{v}" for k, v in buckets.items()))
        spike_at_1 = sum(1 for s in all_scores if s >= 0.99)
        if spike_at_1:
            print(f"  [!] {spike_at_1}/{len(all_scores)} scores >= 0.99 — possible validator collapse")

    # ── Per-criterion breakdown ───────────────────────────────────────────
    crit_sums = defaultdict(list)
    for r in records:
        for a in r.get("attempts", []):
            for k, v in a.get("criteria", {}).items():
                crit_sums[k].append(float(v))

    if crit_sums:
        print(f"\n--- CRITERIA AVERAGES ---")
        for k in ("causal_link", "domain_fidelity", "falsifiability", "implementability"):
            vals = crit_sums.get(k, [])
            if vals:
                print(f"  {k:<20}: {sum(vals)/len(vals):.3f}  (n={len(vals)})")

    # ── Domain diversity / entropy ────────────────────────────────────────
    domain_pairs = defaultdict(int)
    domain_froms = defaultdict(int)
    for r in records:
        pair = f"{r.get('domain_from','?')} -> {r.get('domain_to','?')}"
        domain_pairs[pair] += 1
        domain_froms[r.get('domain_from', '?')] += 1

    pair_entropy   = _entropy(domain_pairs)
    from_entropy   = _entropy(domain_froms)
    top_pairs = sorted(domain_pairs.items(), key=lambda x: -x[1])[:6]

    print(f"\n--- DOMAIN DIVERSITY ---")
    print(f"  Unique pairs       : {len(domain_pairs)}")
    print(f"  Pair entropy (bits): {pair_entropy:.2f}  (max={math.log2(max(len(domain_pairs),1)):.2f})")
    print(f"  Domain-from entropy: {from_entropy:.2f}  (max={math.log2(max(len(domain_froms),1)):.2f})")
    print(f"  Top pairs:")
    for pair, cnt in top_pairs:
        print(f"    {cnt:2d}x  {pair}")

    # Check if blocked pairs were respected
    violated = 0
    for r in records:
        blocked = r.get("domain_blocked", [])
        pair_str = f"- {r.get('domain_from','?')} -> {r.get('domain_to','?')}"
        if pair_str in blocked:
            violated += 1
    if violated:
        print(f"  [!] {violated} hypotheses generated a domain pair that was in the block list")

    print(f"\n--- KAGGLE ---")
    print(f"  Flagged kaggle     : {kaggle_count:3d}  ({100*kaggle_count/total:.0f}%)")

    # ── Diagnosis ─────────────────────────────────────────────────────────
    valid_pct   = 100 * len(valid_recs) / total
    rewrite_pct = 100 * len(had_rewrite) / total
    avg_score   = sum(all_scores) / len(all_scores) if all_scores else 1.0
    spike_at_1  = sum(1 for s in all_scores if s >= 0.99)

    print(f"\n--- DIAGNOSIS ---")
    if spike_at_1 == len(all_scores) and total >= 3:
        print(f"  [!!] VALIDATOR COLLAPSE: all scores >= 0.99.")
        print(f"       Raise temperature to 0.3, add stricter anchor examples.")
    elif valid_pct < 30:
        print(f"  [!] Caso A - TROPPO SEVERO: VALID < 30%.")
        print(f"       Abbassa soglia VALID (0.70 -> 0.60).")
    elif valid_pct > 75 and avg_score > 0.85 and total >= 5:
        print(f"  [!] Caso B - TROPPO PERMISSIVO: VALID > 75%, avg_score={avg_score:.2f}.")
        print(f"       Alza soglia o rafforza CAUSAL_LINK nel prompt.")
    elif rewrite_pct > 50:
        print(f"  [!] Caso C - REWRITE DOMINANTE: generator debole.")
        print(f"       Migliora prompt SynthesizePhase.")
    elif had_rewrite and len(rewrite_bad) / len(had_rewrite) > 0.5:
        print(f"  [!] Caso D - REWRITE INEFFICACE: molti REWRITE -> FAIL.")
        print(f"       Forza rewrite piu strutturato.")
    elif pair_entropy < 1.0 and total >= 5:
        print(f"  [!] DOMAIN COLLAPSE: entropia pair={pair_entropy:.2f}. "
              f"Generator converge su pochi domini.")
    else:
        print(f"  [OK] Distribuzione nei range accettabili.")

    # ── Sample output for manual review ───────────────────────────────────
    print(f"\n--- SAMPLE: 3 VALID (sanity check) ---")
    for r in valid_recs[:3]:
        score = next((a["score"] for a in r.get("attempts", []) if a.get("verdict") == "VALID"), "?")
        crit_str = ""
        for a in r.get("attempts", []):
            if a.get("criteria"):
                c = a["criteria"]
                crit_str = f" CL={c.get('causal_link','?')} DF={c.get('domain_fidelity','?')}"
                break
        print(f"  score={score}{crit_str}  rewrites={r.get('num_rewrites',0)}")
        print(f"  hyp: {r.get('hypothesis','')[:80]}")

    print(f"\n--- SAMPLE: 3 INVALID/EXHAUSTED (false positive check) ---")
    for r in (invalid_recs + exhausted_recs)[:3]:
        score = next((a["score"] for a in r.get("attempts", [])), "?")
        issues = r.get("attempts", [{}])[-1].get("issues", [])
        print(f"  score={score}  verdict={r.get('final_verdict')}")
        print(f"  hyp: {r.get('hypothesis','')[:80]}")
        if issues:
            print(f"  issues: {'; '.join(issues)[:80]}")

    print("=" * 65)
    if path:
        print(f"Log: {path}")


if __name__ == "__main__":
    aggregate = "--all" in sys.argv
    if aggregate:
        paths = find_all_logs()
        if not paths:
            print(f"No alignment logs found in {EXPERIMENTS_DIR}")
            sys.exit(1)
        all_records = []
        for p in paths:
            all_records.extend(load_records(p))
        print(f"Aggregating {len(paths)} log files, {len(all_records)} total records")
        analyse(all_records, path=f"{len(paths)} log files")
    else:
        path = sys.argv[1] if len(sys.argv) > 1 else find_latest_log()
        if not path or not os.path.exists(path):
            print(f"No alignment log found in {EXPERIMENTS_DIR}")
            sys.exit(1)
        print(f"Loading: {path}")
        records = load_records(path)
        analyse(records, path=path)
