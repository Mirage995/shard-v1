"""d14_b_analyze.py -- Verdict engine for D14-B validation pack results.

Reads raw_results.json produced by d14_b_validation_pack.py and emits a
structured verdict (PASS_STRONG / PASS_WEAK / FAIL / INCONCLUSIVE) based on
the D14-B promotion gate.

Promotion gate:
  1. Mean forgetting_magnitude (ANV+OGD) < mean forgetting_magnitude (OGD-only)
  2. Mean final_average_accuracy (ANV+OGD) >= mean final_average_accuracy (OGD-only) - 0.01
  3. PASS_STRONG requires both conditions + Wilcoxon p < 0.05 on forgetting_magnitude
  4. PASS_WEAK requires both conditions with p >= 0.05 (or too few seeds for the test)

This script does NOT update Hypothesis #14 provenance.
Promotion to benchmark_validated is a manual step after human review.

Usage:
  python backend/d14_b_analyze.py shard_workspace/d14_b_runs/<timestamp>/raw_results.json
  python backend/d14_b_analyze.py shard_workspace/d14_b_runs/<timestamp>/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ─────────────────────────────────────────────────────────────────

FORGETTING_THRESHOLD      = 0.0    # ANV+OGD must be strictly lower
ACC_DEGRADATION_THRESHOLD = 0.01   # max allowed final_avg_acc drop (1 pp)
WILCOXON_P_THRESHOLD      = 0.05
MIN_SEEDS_FOR_WILCOXON    = 5

VERDICT_PASS_STRONG   = "PASS_STRONG"
VERDICT_PASS_WEAK     = "PASS_WEAK"
VERDICT_FAIL          = "FAIL"
VERDICT_INCONCLUSIVE  = "INCONCLUSIVE"

# Condition names as produced by d14_b_validation_pack.py
COND_OGD_ONLY = "OGD only"
COND_ANV_OGD  = "ANV + OGD"


# ── Data extraction ───────────────────────────────────────────────────────────

def _extract_per_seed_metric(
    results: List[Dict[str, Any]],
    condition: str,
    metric: str,
) -> List[float]:
    """Return list of per-seed values for a given condition and metric key."""
    vals = []
    for seed_res in results:
        if condition in seed_res and metric in seed_res[condition]:
            vals.append(float(seed_res[condition][metric]))
    return vals


def _mean_std(values: List[float]) -> Tuple[float, float]:
    import statistics
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    return statistics.mean(values), statistics.stdev(values)


# ── Wilcoxon test (scipy optional) ───────────────────────────────────────────

def _wilcoxon_pvalue(x: List[float], y: List[float]) -> Optional[float]:
    """Run Wilcoxon signed-rank test on paired samples. Returns p-value or None."""
    if len(x) != len(y) or len(x) < MIN_SEEDS_FOR_WILCOXON:
        return None
    try:
        from scipy.stats import wilcoxon  # type: ignore[import]
        diffs = [a - b for a, b in zip(x, y)]
        if all(d == 0.0 for d in diffs):
            return 1.0   # no difference → p=1
        _, p = wilcoxon(diffs)
        return float(p)
    except ImportError:
        return None
    except Exception:
        return None


# ── Verdict logic ─────────────────────────────────────────────────────────────

def compute_verdict(
    ogd_forget: List[float],
    anv_forget: List[float],
    ogd_acc:    List[float],
    anv_acc:    List[float],
) -> Dict[str, Any]:
    """Core verdict computation (pure function, importable for tests).

    Parameters are per-seed lists for OGD-only and ANV+OGD on:
      - forgetting_magnitude (lower is better)
      - final_average_accuracy (higher is better)

    Returns a dict:
      verdict           str
      gate1_passed      bool   ANV+OGD forgetting < OGD-only
      gate2_passed      bool   ANV+OGD acc >= OGD-only - 0.01
      wilcoxon_p        float | None
      wilcoxon_tested   bool
      ogd_forgetting    dict   mean, std
      anv_forgetting    dict   mean, std
      ogd_acc           dict   mean, std
      anv_acc           dict   mean, std
      n_seeds           int
      notes             list[str]
    """
    notes: List[str] = []

    if not ogd_forget or not anv_forget:
        return {
            "verdict":         VERDICT_INCONCLUSIVE,
            "gate1_passed":    False,
            "gate2_passed":    False,
            "wilcoxon_p":      None,
            "wilcoxon_tested": False,
            "ogd_forgetting":  {"mean": 0.0, "std": 0.0},
            "anv_forgetting":  {"mean": 0.0, "std": 0.0},
            "ogd_acc":         {"mean": 0.0, "std": 0.0},
            "anv_acc":         {"mean": 0.0, "std": 0.0},
            "n_seeds":         0,
            "notes":           ["No data found for one or both conditions."],
        }

    ogd_f_mean, ogd_f_std = _mean_std(ogd_forget)
    anv_f_mean, anv_f_std = _mean_std(anv_forget)
    ogd_a_mean, ogd_a_std = _mean_std(ogd_acc)
    anv_a_mean, anv_a_std = _mean_std(anv_acc)

    # Gate 1: forgetting
    gate1 = anv_f_mean < ogd_f_mean - FORGETTING_THRESHOLD
    if not gate1:
        notes.append(
            f"Gate1 FAILED: ANV+OGD forgetting ({anv_f_mean:.4f}) "
            f"not < OGD-only ({ogd_f_mean:.4f})"
        )

    # Gate 2: accuracy degradation
    acc_gap = anv_a_mean - ogd_a_mean   # positive = ANV+OGD is better
    gate2 = acc_gap >= -ACC_DEGRADATION_THRESHOLD
    if not gate2:
        notes.append(
            f"Gate2 FAILED: ANV+OGD acc ({anv_a_mean:.4f}) degraded "
            f"{-acc_gap*100:.2f} pp vs OGD-only ({ogd_a_mean:.4f}) — threshold 1.0 pp"
        )

    # Wilcoxon
    p_val = _wilcoxon_pvalue(anv_forget, ogd_forget)
    tested = p_val is not None

    n_seeds = min(len(ogd_forget), len(anv_forget))
    if not tested and n_seeds < MIN_SEEDS_FOR_WILCOXON:
        notes.append(
            f"Wilcoxon not performed: only {n_seeds} seeds "
            f"(need {MIN_SEEDS_FOR_WILCOXON})"
        )
    elif not tested:
        notes.append("Wilcoxon not performed: scipy unavailable")

    # Verdict
    if not gate1 or not gate2:
        verdict = VERDICT_FAIL
    elif gate1 and gate2 and tested and p_val is not None and p_val < WILCOXON_P_THRESHOLD:
        verdict = VERDICT_PASS_STRONG
    elif gate1 and gate2:
        verdict = VERDICT_PASS_WEAK
        if tested and p_val is not None:
            notes.append(
                f"Wilcoxon p={p_val:.4f} >= {WILCOXON_P_THRESHOLD} — "
                "gates passed but result is not statistically significant at α=0.05"
            )
    else:
        verdict = VERDICT_INCONCLUSIVE

    return {
        "verdict":         verdict,
        "gate1_passed":    gate1,
        "gate2_passed":    gate2,
        "wilcoxon_p":      round(p_val, 6) if p_val is not None else None,
        "wilcoxon_tested": tested,
        "ogd_forgetting":  {"mean": round(ogd_f_mean, 6), "std": round(ogd_f_std, 6)},
        "anv_forgetting":  {"mean": round(anv_f_mean, 6), "std": round(anv_f_std, 6)},
        "ogd_acc":         {"mean": round(ogd_a_mean, 6), "std": round(ogd_a_std, 6)},
        "anv_acc":         {"mean": round(anv_a_mean, 6), "std": round(anv_a_std, 6)},
        "n_seeds":         n_seeds,
        "notes":           notes,
    }


# ── Condition table ───────────────────────────────────────────────────────────

def build_condition_table(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return one row per condition with mean±std for all three metrics."""
    metrics = ["forgetting_magnitude", "final_average_accuracy", "signed_bwt"]
    condition_names = ["Baseline SGD", "ANV only", "OGD only", "ANV + OGD"]
    rows = []
    for name in condition_names:
        row: Dict[str, Any] = {"condition": name}
        for m in metrics:
            vals = _extract_per_seed_metric(results, name, m)
            mean, std = _mean_std(vals)
            row[f"{m}_mean"] = round(mean, 6)
            row[f"{m}_std"]  = round(std,  6)
            row[f"{m}_n"]    = len(vals)
        rows.append(row)
    return rows


# ── Report ────────────────────────────────────────────────────────────────────

def _format_verdict_report(
    verdict_dict: Dict[str, Any],
    table: List[Dict[str, Any]],
    raw_meta: Dict[str, Any],
) -> str:
    lines = [
        "# D14-B Analysis — Verdict Report",
        "",
        f"**Verdict: {verdict_dict['verdict']}**",
        "",
        f"- Gate 1 (forgetting improvement): {'PASS' if verdict_dict['gate1_passed'] else 'FAIL'}",
        f"- Gate 2 (accuracy not degraded >1pp): {'PASS' if verdict_dict['gate2_passed'] else 'FAIL'}",
        f"- Wilcoxon test performed: {verdict_dict['wilcoxon_tested']}",
    ]
    if verdict_dict["wilcoxon_p"] is not None:
        lines.append(f"- Wilcoxon p-value: {verdict_dict['wilcoxon_p']:.4f}")

    lines += [
        f"- Seeds analysed: {verdict_dict['n_seeds']}",
        "",
        "## Condition Table",
        "",
        "| Condition | forgetting_mag (mean±std) | final_avg_acc (mean±std) | signed_bwt (mean±std) |",
        "|---|---|---|---|",
    ]
    for row in table:
        n = row["condition"]
        fm  = f"{row['forgetting_magnitude_mean']:.4f} ± {row['forgetting_magnitude_std']:.4f}"
        fa  = f"{row['final_average_accuracy_mean']:.4f} ± {row['final_average_accuracy_std']:.4f}"
        bwt = f"{row['signed_bwt_mean']:.4f} ± {row['signed_bwt_std']:.4f}"
        lines.append(f"| {n} | {fm} | {fa} | {bwt} |")

    lines += [
        "",
        "## Comparison: OGD-only vs ANV+OGD",
        "",
        f"| Metric | OGD-only | ANV+OGD | Delta |",
        f"|---|---|---|---|",
    ]
    ogd_fm  = verdict_dict["ogd_forgetting"]["mean"]
    anv_fm  = verdict_dict["anv_forgetting"]["mean"]
    ogd_am  = verdict_dict["ogd_acc"]["mean"]
    anv_am  = verdict_dict["anv_acc"]["mean"]
    lines += [
        f"| forgetting_magnitude | {ogd_fm:.4f} | {anv_fm:.4f} | {anv_fm - ogd_fm:+.4f} |",
        f"| final_average_accuracy | {ogd_am:.4f} | {anv_am:.4f} | {anv_am - ogd_am:+.4f} |",
    ]

    if verdict_dict["notes"]:
        lines += ["", "## Notes", ""]
        for note in verdict_dict["notes"]:
            lines.append(f"- {note}")

    lines += [
        "",
        "## Promotion Decision",
        "",
        "**This script does NOT update Hypothesis #14 provenance.**",
    ]
    v = verdict_dict["verdict"]
    if v == VERDICT_PASS_STRONG:
        lines.append(
            "Both gates passed and the result is statistically significant. "
            "Manual promotion to `benchmark_validated` is warranted — run "
            "`experiment_store.set_provenance(14, 'kaggle', 'public_benchmark', 'benchmark_validated')` "
            "after human review."
        )
    elif v == VERDICT_PASS_WEAK:
        lines.append(
            "Both gates passed but statistical significance was not established. "
            "Consider running more seeds before promoting."
        )
    elif v == VERDICT_FAIL:
        lines.append(
            "One or more promotion gates failed. Do NOT promote Hypothesis #14."
        )
    else:
        lines.append(
            "Result is inconclusive. Insufficient data to make a determination."
        )

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def analyze(raw_results_path: str | Path) -> Dict[str, Any]:
    """Load raw_results.json and return full analysis dict (importable for tests)."""
    path = Path(raw_results_path)
    if path.is_dir():
        path = path / "raw_results.json"
    if not path.exists():
        raise FileNotFoundError(f"raw_results.json not found at {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    results: List[Dict] = data.get("results", [])

    ogd_forget = _extract_per_seed_metric(results, COND_OGD_ONLY, "forgetting_magnitude")
    anv_forget = _extract_per_seed_metric(results, COND_ANV_OGD,  "forgetting_magnitude")
    ogd_acc    = _extract_per_seed_metric(results, COND_OGD_ONLY, "final_average_accuracy")
    anv_acc    = _extract_per_seed_metric(results, COND_ANV_OGD,  "final_average_accuracy")

    verdict_dict = compute_verdict(ogd_forget, anv_forget, ogd_acc, anv_acc)
    table        = build_condition_table(results)

    raw_meta = {k: v for k, v in data.items() if k != "results"}
    report   = _format_verdict_report(verdict_dict, table, raw_meta)

    return {
        "verdict":       verdict_dict,
        "table":         table,
        "report":        report,
        "raw_meta":      raw_meta,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="D14-B verdict analyzer")
    parser.add_argument(
        "path",
        help="Path to raw_results.json or directory containing it",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Write verdict.json and verdict.md to this directory (default: same dir as input)",
    )
    args = parser.parse_args(argv)

    result = analyze(args.path)

    # Determine output dir
    in_path = Path(args.path)
    out_dir = Path(args.output) if args.output else (
        in_path if in_path.is_dir() else in_path.parent
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    verdict_json = out_dir / "verdict.json"
    verdict_md   = out_dir / "verdict.md"

    verdict_json.write_text(
        json.dumps({"verdict": result["verdict"], "table": result["table"],
                    "raw_meta": result["raw_meta"]}, indent=2),
        encoding="utf-8",
    )
    verdict_md.write_text(result["report"], encoding="utf-8")

    v = result["verdict"]["verdict"]
    print(f"[D14-B ANALYZE] Verdict: {v}")
    print(f"  Gate1 (forgetting):  {'PASS' if result['verdict']['gate1_passed'] else 'FAIL'}")
    print(f"  Gate2 (accuracy):    {'PASS' if result['verdict']['gate2_passed'] else 'FAIL'}")
    if result["verdict"]["wilcoxon_p"] is not None:
        print(f"  Wilcoxon p:          {result['verdict']['wilcoxon_p']:.4f}")
    print(f"[D14-B ANALYZE] Reports saved → {out_dir}")


if __name__ == "__main__":
    main()
