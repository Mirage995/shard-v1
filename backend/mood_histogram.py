"""mood_histogram.py -- Summarize mood_history.jsonl distribution.

Reads shard_memory/mood_history.jsonl (populated by MoodEngine.compute())
and prints sample size, basic stats, and threshold occupancy around the
ValenceField activation cuts (+/- 0.3) plus label distribution.

Use AFTER running at least one normal night session so there is data to
analyze. Output answers: "is the natural mood regime in the dead zone
of ValenceField, or does it cross threshold often enough to drive the
GWT lever organically?"

Usage:
    python backend/mood_histogram.py
"""
import json
import statistics
from collections import Counter
from pathlib import Path

_ROOT    = Path(__file__).resolve().parent.parent
_HIST    = _ROOT / "shard_memory" / "mood_history.jsonl"
_THRESH  = 0.3   # ValenceField activation threshold


def main():
    if not _HIST.exists():
        print(f"[mood_histogram] No history at {_HIST}")
        print("Run a night session first; MoodEngine.compute() appends to this file.")
        return

    samples = []
    labels  = []
    components_keys = ("frustration", "cert_rate", "momentum", "workspace_bias")
    components_acc  = {k: [] for k in components_keys}
    with _HIST.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            samples.append(float(row["mood_score"]))
            labels.append(row.get("label", "unknown"))
            comps = row.get("components", {})
            for k in components_keys:
                if k in comps:
                    components_acc[k].append(float(comps[k]))

    n = len(samples)
    if n == 0:
        print("[mood_histogram] history file is empty.")
        return

    mn = min(samples)
    mx = max(samples)
    mu = statistics.mean(samples)
    sd = statistics.stdev(samples) if n > 1 else 0.0

    below = sum(1 for s in samples if s <= -_THRESH)
    above = sum(1 for s in samples if s >=  _THRESH)
    dead  = n - below - above

    print("=" * 70)
    print(f"MOOD HISTOGRAM   (samples={n}, file={_HIST.name})")
    print("=" * 70)
    print(f"  min={mn:+.3f}  max={mx:+.3f}  mean={mu:+.3f}  std={sd:.3f}")
    print()
    print(f"  ValenceField activation threshold: |mood_score| >= {_THRESH}")
    print(f"    below -{_THRESH:.1f}:   {below:>4}  ({below/n*100:.1f}%)")
    print(f"    above +{_THRESH:.1f}:   {above:>4}  ({above/n*100:.1f}%)")
    print(f"    dead zone:    {dead:>4}  ({dead/n*100:.1f}%)")
    print()
    print("  Label distribution:")
    for lbl, count in Counter(labels).most_common():
        print(f"    {lbl:<12} {count:>4}  ({count/n*100:.1f}%)")
    print()
    print("  Component means:")
    for k, vals in components_acc.items():
        if vals:
            print(f"    {k:<16} mean={statistics.mean(vals):+.3f}  std={statistics.stdev(vals) if len(vals)>1 else 0.0:.3f}")
    print()

    # Coupling-inactive hint: workspace_bias stuck at 0.0 across all samples
    wb_vals = components_acc.get("workspace_bias") or []
    if wb_vals and all(abs(v) < 1e-6 for v in wb_vals):
        print("  HINT: workspace_bias is flat at 0.0 across all samples.")
        print("        Expected in easy/no-retry regimes -- MoodWorkspaceCoupling")
        print("        only accumulates bias when workspace winner events are")
        print("        propagated through on_workspace_result(). Run a stress/")
        print("        frustration benchmark (D2) before concluding the coupling")
        print("        is inactive.")
        print()

    # Decision hint
    print("=" * 70)
    print("DECISION HINT (D1 calibration vs D2 frustration benchmark)")
    print("=" * 70)
    pct_dead = dead / n * 100
    if pct_dead >= 80:
        print(f"  >= 80% in dead zone ({pct_dead:.1f}%): natural regime rarely activates")
        print(f"  ValenceField. D1 calibration (lower threshold) MAY be justified,")
        print(f"  but first check if mood is just stuck (component variance low).")
    elif below / n * 100 >= 25:
        print(f"  {below/n*100:.1f}% below -{_THRESH}: natural runs already cross negative")
        print(f"  threshold. D1 NOT needed yet -- go straight to D2 frustration")
        print(f"  benchmark to test causal effect under stress.")
    else:
        print(f"  Mixed regime: dead={pct_dead:.1f}%  below={below/n*100:.1f}%  above={above/n*100:.1f}%.")
        print(f"  Collect more data (longer night session) before deciding.")


if __name__ == "__main__":
    main()
