"""analyze.py -- Statistical analysis and visualization of DiffDock hypothesis test.

Reads results/raw_results.csv and produces:
  - results/plot_rmsd_vs_steps.png   -- line chart per flexibility class
  - results/plot_success_rate.png    -- % poses with RMSD < 2Å per class
  - results/statistical_test.json   -- Mann-Whitney U test results
  - results/verdict.txt             -- human-readable hypothesis verdict
"""
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import scipy.stats as stats

RESULTS_DIR = Path("results")
RAW_CSV = RESULTS_DIR / "raw_results.csv"

COLORS = {
    "rigid":    "#2ecc71",
    "medium":   "#f39c12",
    "flexible": "#e74c3c",
}

SUCCESS_THRESHOLD = 2.0   # Å — standard docking success criterion


def load_results() -> pd.DataFrame:
    if not RAW_CSV.exists():
        print(f"ERROR: {RAW_CSV} not found. Run run_experiment.py first.")
        sys.exit(1)
    df = pd.read_csv(RAW_CSV)
    print(f"Loaded {len(df)} results ({df['pdb_id'].nunique()} complexes)")
    return df


def plot_rmsd_vs_steps(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))

    for flex_class, color in COLORS.items():
        subset = df[df["flexibility_class"] == flex_class]
        if subset.empty:
            continue
        grouped = subset.groupby("inference_steps")["best_rmsd"].agg(["mean", "std"])
        steps = grouped.index.values
        mean_rmsd = grouped["mean"].values
        std_rmsd = grouped["std"].values

        ax.plot(steps, mean_rmsd, "o-", color=color, label=flex_class, linewidth=2, markersize=7)
        ax.fill_between(steps, mean_rmsd - std_rmsd, mean_rmsd + std_rmsd,
                        alpha=0.15, color=color)

    ax.axhline(SUCCESS_THRESHOLD, color="gray", linestyle="--", alpha=0.7, label=f"Success threshold ({SUCCESS_THRESHOLD}Å)")
    ax.set_xlabel("Inference Steps", fontsize=12)
    ax.set_ylabel("Mean Best RMSD (Å)", fontsize=12)
    ax.set_title("DiffDock: Inference Steps vs Docking Accuracy\nby Conformational Flexibility Class", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xticks([10, 20, 50, 100])

    plt.tight_layout()
    out = RESULTS_DIR / "plot_rmsd_vs_steps.png"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"Saved: {out}")


def plot_success_rate(df: pd.DataFrame):
    df = df.copy()
    df["success"] = df["best_rmsd"] < SUCCESS_THRESHOLD

    fig, ax = plt.subplots(figsize=(9, 5))
    steps_list = sorted(df["inference_steps"].unique())
    x = np.arange(len(steps_list))
    width = 0.25

    for i, (flex_class, color) in enumerate(COLORS.items()):
        subset = df[df["flexibility_class"] == flex_class]
        if subset.empty:
            continue
        rates = [
            subset[subset["inference_steps"] == s]["success"].mean() * 100
            for s in steps_list
        ]
        ax.bar(x + i * width, rates, width, label=flex_class, color=color, alpha=0.85)

    ax.set_xlabel("Inference Steps", fontsize=12)
    ax.set_ylabel("Success Rate (% poses RMSD < 2Å)", fontsize=12)
    ax.set_title("DiffDock: Docking Success Rate by Steps and Flexibility", fontsize=13)
    ax.set_xticks(x + width)
    ax.set_xticklabels([str(s) for s in steps_list])
    ax.legend(fontsize=10)
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    out = RESULTS_DIR / "plot_success_rate.png"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"Saved: {out}")


def statistical_tests(df: pd.DataFrame) -> dict:
    """Mann-Whitney U test: low steps vs high steps, per flexibility class."""
    results = {}
    low_steps = 10
    high_steps = 100

    for flex_class in ["rigid", "medium", "flexible"]:
        subset = df[df["flexibility_class"] == flex_class]
        low = subset[subset["inference_steps"] == low_steps]["best_rmsd"].dropna()
        high = subset[subset["inference_steps"] == high_steps]["best_rmsd"].dropna()

        if len(low) < 3 or len(high) < 3:
            results[flex_class] = {"error": "insufficient data"}
            continue

        stat, p = stats.mannwhitneyu(low, high, alternative="greater")
        results[flex_class] = {
            "test": "Mann-Whitney U (one-sided: low_steps > high_steps in RMSD)",
            "n_low": int(len(low)),
            "n_high": int(len(high)),
            "mean_rmsd_low_steps": round(float(low.mean()), 3),
            "mean_rmsd_high_steps": round(float(high.mean()), 3),
            "delta_rmsd": round(float(low.mean() - high.mean()), 3),
            "p_value": round(float(p), 4),
            "significant": bool(p < 0.05),
        }

    return results


def verdict(stat_results: dict) -> str:
    lines = [
        "=" * 60,
        "  HYPOTHESIS TEST VERDICT",
        "=" * 60,
        "",
        "HYPOTHESIS: Increasing inference steps improves docking",
        "accuracy for FLEXIBLE complexes but NOT for RIGID ones.",
        "",
    ]

    flex_sig = stat_results.get("flexible", {}).get("significant", None)
    rigid_sig = stat_results.get("rigid", {}).get("significant", None)

    for cls in ["rigid", "medium", "flexible"]:
        r = stat_results.get(cls, {})
        if "error" in r:
            lines.append(f"{cls.upper():10s}: insufficient data")
            continue
        sig = "SIGNIFICANT (p<0.05)" if r["significant"] else "not significant"
        lines.append(
            f"{cls.upper():10s}: delta={r['delta_rmsd']:+.2f}Å  p={r['p_value']:.4f}  [{sig}]"
        )

    lines.append("")

    if flex_sig is True and rigid_sig is False:
        verdict_str = "HYPOTHESIS SUPPORTED"
        explanation = (
            "More steps significantly improve flexible docking accuracy\n"
            "but have no significant effect on rigid complexes.\n"
            "-> Conformational sampling is the bottleneck for flexible cases."
        )
    elif flex_sig is False and rigid_sig is False:
        verdict_str = "HYPOTHESIS REJECTED"
        explanation = (
            "More steps do NOT significantly improve accuracy for any class.\n"
            "-> Inference steps are NOT the limiting factor. Architecture or\n"
            "   training data are more likely bottlenecks."
        )
    elif flex_sig is True and rigid_sig is True:
        verdict_str = "PARTIALLY SUPPORTED"
        explanation = (
            "More steps improve accuracy across ALL flexibility classes.\n"
            "-> Sampling helps universally, not specifically for flexible cases.\n"
            "   Hypothesis partially wrong: effect is not class-specific."
        )
    else:
        verdict_str = "INCONCLUSIVE"
        explanation = "Mixed or insufficient results. Expand dataset."

    lines += [f"VERDICT: {verdict_str}", "", explanation, "", "=" * 60]
    return "\n".join(lines)


def main():
    df = load_results()
    print()

    plot_rmsd_vs_steps(df)
    plot_success_rate(df)

    stat_results = statistical_tests(df)
    stat_path = RESULTS_DIR / "statistical_test.json"
    with open(stat_path, "w") as f:
        json.dump(stat_results, f, indent=2)
    print(f"Saved: {stat_path}")

    verdict_text = verdict(stat_results)
    verdict_path = RESULTS_DIR / "verdict.txt"
    verdict_path.write_text(verdict_text)
    print(f"Saved: {verdict_path}")

    print()
    print(verdict_text)


if __name__ == "__main__":
    main()
