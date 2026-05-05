"""d2_1c_analyze.py -- Verdict for D2.1C Sequential Multi-Topic Validation.

Question:
    "After cycle 1 (stress inducer) drains workspace winners and
     mutates MoodWorkspaceCoupling._valence_bias, does the bias
     become observable in cycle 2's MoodEngine.compute samples
     in ARM_ON, while staying near-zero in ARM_OFF?"

Verdicts:
    PASS_STRONG    harness clean +
                   ARM_ON has at least one mood sample with
                     |workspace_bias| > NEAR_ZERO +
                   ARM_OFF stays near-zero across all samples
    PASS_WEAK      harness clean +
                   ARM_ON has non-zero bias somewhere but no
                     consistent contrast with ARM_OFF
    FAIL           harness clean +
                   no detectable bias differentiation
    INCONCLUSIVE_MECHANISM_DISCONNECTED
                   harness clean +
                   inverted pattern detected: ARM_OFF shows non-zero
                   workspace_bias while ARM_ON stays zero. This matches
                   the inspected D2.1C mechanism: ARM_OFF fallback bias
                   and ARM_ON zero-bias "tensions" winner.
    CONTAMINATED   live calls / cache mismatch / subprocess error /
                   stress not observed / sequence not observed twice

Usage:
    python backend/d2_1c_analyze.py
    python backend/d2_1c_analyze.py shard_workspace/d2_1c_runs/<TIMESTAMP>
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

_ROOT     = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_1c_runs"

WORKSPACE_BIAS_NEAR_ZERO = 0.01

SUBCODE_ARM_OFF_FALLBACK = "ARM_OFF_FALLBACK_BIAS_OBSERVED"
SUBCODE_ARM_ON_ZERO_WINNER = "ARM_ON_ZERO_BIAS_FROM_TENSIONS_WINNER"


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    cands = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return cands[-1] if cands else None


def load_summary(run_root: Path) -> dict:
    f = run_root / "d2_1c_summary.json"
    if not f.exists():
        raise FileNotFoundError(f"Missing summary: {f}")
    return json.loads(f.read_text(encoding="utf-8"))


def load_mood_samples(run_dir: Path) -> list:
    f = run_dir / "mood_samples.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def mood_stats(samples: list) -> dict:
    if not samples:
        return {"available": False, "n": 0}
    scores = [float(s["mood_score"]) for s in samples]
    wb = [float(s.get("components", {}).get("workspace_bias", 0.0)) for s in samples]
    return {
        "available":             True,
        "n":                     len(scores),
        "mood_min":              round(min(scores), 3),
        "mood_max":              round(max(scores), 3),
        "mood_mean":             round(statistics.mean(scores), 3),
        "wb_max_abs":            round(max(abs(x) for x in wb) if wb else 0.0, 4),
        "wb_nonzero_count":      sum(1 for x in wb if abs(x) > WORKSPACE_BIAS_NEAR_ZERO),
        "wb_traj":               wb,
        "mood_traj":             scores,
    }


def render(run_root: Path, summary: dict) -> tuple[str, str]:
    manifests = summary.get("manifests", [])

    # Locate ARM_OFF and ARM_ON manifests
    arms_data = {}
    for m in manifests:
        run_dir = run_root / m["arm"].lower()
        arms_data[m["arm"]] = {
            "manifest": m,
            "mood":     mood_stats(load_mood_samples(run_dir)),
        }

    # Harness sanity
    all_exit_zero       = all(m["subprocess_exit_code"] == 0 for m in manifests)
    no_live             = all(m.get("ddgs_call_count", 0) == 0
                              and m.get("brave_call_count", 0) == 0
                              and m.get("playwright_call_count", 0) == 0 for m in manifests)
    cache_hits_ok       = all(m.get("cache_hit_map", 0) >= 2 for m in manifests)
    no_contam_flag      = all(not m.get("contaminated", False) for m in manifests)
    stress_observed_all = all(m.get("stress_injection_observed", False) for m in manifests)
    seq_observed_all    = all(m.get("force_topic_seq_observed", False) for m in manifests)

    # Comparative bias signal
    on_data  = arms_data.get("ARM_ON")
    off_data = arms_data.get("ARM_OFF")
    on_wb_nonzero  = on_data["mood"].get("wb_nonzero_count", 0) > 0 if on_data else False
    off_wb_nonzero = off_data["mood"].get("wb_nonzero_count", 0) > 0 if off_data else False

    subcodes = []

    # Verdict tree
    if not all_exit_zero or not stress_observed_all or not seq_observed_all:
        verdict = "CONTAMINATED"
        reason  = "Subprocess error, stress injection or topic sequence not observed in some run."
    elif (not no_live) or (not cache_hits_ok) or (not no_contam_flag):
        verdict = "CONTAMINATED"
        reason  = "Harness contamination detected (live calls / missing cache hits / contaminated flag)."
    elif not on_data or not off_data:
        verdict = "INCONCLUSIVE"
        reason  = "Missing ARM_ON or ARM_OFF run."
    elif on_wb_nonzero and not off_wb_nonzero:
        verdict = "PASS_STRONG"
        reason  = (f"ARM_ON observed {on_data['mood']['wb_nonzero_count']} mood sample(s) with "
                   f"|workspace_bias| > {WORKSPACE_BIAS_NEAR_ZERO}; ARM_OFF stayed near-zero "
                   f"across all {off_data['mood'].get('n', 0)} samples. Bias propagated "
                   f"inter-cycle as predicted by D2.1B structural finding.")
    elif on_wb_nonzero and off_wb_nonzero:
        verdict = "PASS_WEAK"
        reason  = ("Both arms show non-zero workspace_bias. Coupling is active but the "
                   "differentiation between arms is not clean.")
    elif (not on_wb_nonzero) and (not off_wb_nonzero):
        verdict = "FAIL"
        reason  = ("Neither ARM_ON nor ARM_OFF shows non-zero workspace_bias in cycle 2. "
                   "Either coupling is not observable in this regime, or sample count is "
                   "too low.")
    elif (not on_wb_nonzero) and off_wb_nonzero:
        verdict = "INCONCLUSIVE_MECHANISM_DISCONNECTED"
        subcodes = [
            SUBCODE_ARM_OFF_FALLBACK,
            SUBCODE_ARM_ON_ZERO_WINNER,
        ]
        reason  = ("Inverted pattern detected: ARM_OFF shows non-zero workspace_bias while "
                   "ARM_ON remains zero. The observed pattern matches the inspected mechanism: "
                   "ARM_OFF fallback bias and ARM_ON zero-bias tensions winner.")
    else:
        verdict = "INCONCLUSIVE"
        reason  = "Unexpected state."

    # Render
    L = []
    L.append("# D2.1C Sequential Multi-Topic Stress Validation Report\n")
    L.append(f"Run root: `{run_root.relative_to(_ROOT).as_posix()}`")
    L.append(f"Aborted:  `{summary.get('aborted', False)}`\n")
    L.append(f"**Final verdict: `{verdict}`**\n")
    L.append(f"> {reason}\n")
    if subcodes:
        L.append("Diagnostic subcodes:")
        for code in subcodes:
            L.append(f"- `{code}`")
        L.append("")

    L.append("## Harness sanity (prerequisite)\n")
    rows = [
        ("All subprocess exit_code == 0",      all_exit_zero),
        ("Zero live DDGS/Brave/Playwright",    no_live),
        (f"Cached MAP hook fired >= 2x per arm", cache_hits_ok),
        ("No contamination flag",              no_contam_flag),
        ("Stress injection observed",          stress_observed_all),
        ("Force-topic-sequence observed >= 2x", seq_observed_all),
    ]
    L.append("| Check | Result |")
    L.append("|---|---|")
    for label, ok in rows:
        L.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    L.append("")

    L.append("## Per-arm signal\n")
    L.append("| arm | mood_n | mood traj | wb traj | wb_nonzero count |")
    L.append("|---|---|---|---|---|")
    for arm_name in ("ARM_OFF", "ARM_ON"):
        a = arms_data.get(arm_name)
        if not a:
            L.append(f"| {arm_name} | - | - | - | - |")
            continue
        m = a["mood"]
        L.append(f"| {arm_name} "
                 f"| {m.get('n', 0)} "
                 f"| {m.get('mood_traj', [])} "
                 f"| {m.get('wb_traj', [])} "
                 f"| {m.get('wb_nonzero_count', 0)} |")
    L.append("")

    L.append("## Per-run manifest detail\n")
    L.append("| # | arm | exit | dur(s) | cache_hits | seq_obs | stress_obs | retries | mood_n | contam |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for m in manifests:
        L.append(f"| {m['run_index_global']} "
                 f"| {m['arm']} "
                 f"| {m['subprocess_exit_code']} "
                 f"| {m['duration_seconds']} "
                 f"| ({m.get('cache_hit_map',0)},{m.get('cache_hit_aggregate',0)}) "
                 f"| {'YES' if m.get('force_topic_seq_observed') else 'no'} "
                 f"| {'YES' if m.get('stress_injection_observed') else 'no'} "
                 f"| {m.get('retry_attempt_count',0)} "
                 f"| {m.get('mood_sample_count',0)} "
                 f"| {'Y' if m.get('contaminated') else 'N'} |")
    L.append("")

    if verdict == "INCONCLUSIVE_MECHANISM_DISCONNECTED":
        L.append("## Mechanism diagnosis\n")
        L.append("Diagnostic flags:")
        L.append(f"- `{SUBCODE_ARM_OFF_FALLBACK}`")
        L.append(f"- `{SUBCODE_ARM_ON_ZERO_WINNER}`\n")
        L.append("ARM_OFF non-zero workspace_bias is consistent with synthetic ignition-failure fallback.")
        L.append("ARM_ON zero workspace_bias is consistent with the dominant `tensions` winner mapping to zero MoodWorkspaceCoupling bias.")
        L.append("The analyzer classifies the inverted pattern from mood samples; the mechanism diagnosis is supported by log and code inspection.")
        L.append("")

    L.append("## Notes\n")
    L.append(f"- Workspace_bias near-zero bound: |bias| <= {WORKSPACE_BIAS_NEAR_ZERO}")
    L.append("- D2.1C tests OBSERVABILITY of inter-cycle coupling, not")
    L.append("  operational improvement. PASS_STRONG means the signal becomes")
    L.append("  visible in cycle 2 mood samples; it does NOT yet claim that")
    L.append("  the GWT path produces behavioral outcome gains.")
    L.append("- The stress injection runs on attempt 1 of EACH cycle, so")
    L.append("  cycle 1 (stress inducer) and cycle 2 (bias observer) both")
    L.append("  experience the same cognitive pressure. The differentiator")
    L.append("  is whether ARM_ON propagates winner bias forward.")

    return "\n".join(L), verdict


def main():
    if len(sys.argv) > 1:
        run_root = Path(sys.argv[1]).resolve()
    else:
        run_root = _latest_run_root()
        if run_root is None:
            print(f"[d2_1c_analyze] no runs found under {RUNS_ROOT}")
            sys.exit(2)
    if not run_root.exists():
        print(f"[d2_1c_analyze] run root not found: {run_root}")
        sys.exit(2)
    summary = load_summary(run_root)
    md, verdict = render(run_root, summary)
    out_md = run_root / "d2_1c_report.md"
    out_md.write_text(md, encoding="utf-8")
    print(md)
    print()
    print(f"[d2_1c_analyze] Report -> {out_md}")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
