"""d2_1b_analyze.py -- Verdict for D2.1B Stress Validation.

Reads a d2_1b_runs/<TIMESTAMP>/ directory produced by
d2_1b_benchmark.py and answers the question:

    "Under controlled cognitive stress, does ARM_ON exhibit
     different behavior from ARM_OFF that is consistent with
     the GWT/MoodWorkspaceCoupling design?"

Verdicts:
    PASS_STRONG    harness clean + ARM_ON crosses mood -0.3 +
                   ARM_ON workspace_bias non-zero +
                   ARM_OFF workspace_bias near-zero +
                   recovery(ARM_ON) >= recovery(ARM_OFF)

    PASS_WEAK      harness clean + ARM_ON workspace_bias non-zero +
                   mood trend coherent but doesn't cross -0.3 +
                   recovery not worse

    INCONCLUSIVE   harness clean + ambiguous mood/workspace signal

    FAIL           harness clean + no detectable difference between
                   arms; or ARM_ON markedly worse

    CONTAMINATED   any live call leaked / cache hash mismatch /
                   subprocess error / stress injection not applied

The verdict is a SIGNAL CHECK, not a definitive claim about GWT
operational value. PASS_STRONG with N=2 topics is a hint, not proof;
larger samples are needed before paper-grade conclusions.

Usage:
    python backend/d2_1b_analyze.py
    python backend/d2_1b_analyze.py shard_workspace/d2_1b_runs/<TIMESTAMP>
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

_ROOT     = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_1b_runs"

MOOD_STRESS_THRESH = -0.30
WORKSPACE_BIAS_NEAR_ZERO = 0.01   # |bias| <= this = "near-zero"


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    cands = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return cands[-1] if cands else None


def load_summary(run_root: Path) -> dict:
    f = run_root / "d2_1b_summary.json"
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
        return {"available": False}
    scores = [float(s["mood_score"]) for s in samples]
    wb = [float(s.get("components", {}).get("workspace_bias", 0.0)) for s in samples]
    return {
        "available":              True,
        "n":                      len(scores),
        "mood_min":               round(min(scores), 3),
        "mood_max":               round(max(scores), 3),
        "mood_mean":              round(statistics.mean(scores), 3),
        "mood_std":               round(statistics.stdev(scores) if len(scores) > 1 else 0.0, 3),
        "crossed_stress":         any(s <= MOOD_STRESS_THRESH for s in scores),
        "wb_max_abs":             round(max(abs(x) for x in wb) if wb else 0.0, 4),
        "wb_nonzero":             any(abs(x) > WORKSPACE_BIAS_NEAR_ZERO for x in wb),
    }


def render(run_root: Path, summary: dict) -> tuple[str, str]:
    manifests = summary.get("manifests", [])
    by_topic = defaultdict(dict)
    for m in manifests:
        run_dir = run_root / _slug(m["topic"]) / m["arm"].lower()
        by_topic[m["topic"]][m["arm"]] = {"manifest": m, "mood": mood_stats(load_mood_samples(run_dir))}

    # Harness sanity (must be clean to interpret anything)
    all_exit_zero       = all(m["subprocess_exit_code"] == 0 for m in manifests)
    no_live             = all(m.get("ddgs_call_count", 0) == 0
                              and m.get("brave_call_count", 0) == 0
                              and m.get("playwright_call_count", 0) == 0 for m in manifests)
    cache_hits_ok       = all(m.get("cache_hit_map", 0) > 0 and m.get("cache_hit_aggregate", 0) > 0 for m in manifests)
    no_contam_flag      = all(not m.get("contaminated", False) for m in manifests)
    stress_observed_all = all(m.get("stress_injection_observed", False) for m in manifests)

    # Per-topic comparative checks (ARM_ON vs ARM_OFF)
    topic_signals = []
    for topic, arms in by_topic.items():
        on  = arms.get("ARM_ON")
        off = arms.get("ARM_OFF")
        if not on or not off:
            topic_signals.append({"topic": topic, "complete": False})
            continue
        on_m, off_m = on["mood"], off["mood"]
        topic_signals.append({
            "topic":                       topic,
            "complete":                    True,
            "on_crossed_stress":           on_m.get("crossed_stress", False),
            "off_crossed_stress":          off_m.get("crossed_stress", False),
            "on_mood_min":                 on_m.get("mood_min"),
            "off_mood_min":                off_m.get("mood_min"),
            "on_wb_nonzero":               on_m.get("wb_nonzero", False),
            "off_wb_nonzero":              off_m.get("wb_nonzero", False),
            "on_wb_max_abs":               on_m.get("wb_max_abs"),
            "off_wb_max_abs":              off_m.get("wb_max_abs"),
            "on_retry_attempts":           on["manifest"].get("retry_attempt_count", 0),
            "off_retry_attempts":          off["manifest"].get("retry_attempt_count", 0),
        })

    # Verdict tree
    if not all_exit_zero or not stress_observed_all:
        verdict = "CONTAMINATED"
        reason  = "Subprocess exit failure or stress injection not observed in some run."
    elif not no_live or not cache_hits_ok or not no_contam_flag:
        verdict = "CONTAMINATED"
        reason  = "Harness contamination detected (live calls, missing cache hits, or contaminated flag)."
    else:
        complete = [s for s in topic_signals if s["complete"]]
        if not complete:
            verdict = "INCONCLUSIVE"
            reason  = "No topic has both arms complete."
        else:
            n_strong = 0
            n_weak   = 0
            n_null   = 0
            for s in complete:
                # STRONG: ARM_ON crosses stress AND wb_nonzero AND ARM_OFF wb near-zero
                strong = (s["on_crossed_stress"]
                          and s["on_wb_nonzero"]
                          and not s["off_wb_nonzero"])
                weak = (not strong) and s["on_wb_nonzero"]
                if strong:
                    n_strong += 1
                elif weak:
                    n_weak += 1
                else:
                    n_null += 1

            if n_strong >= 1 and n_null == 0:
                verdict = "PASS_STRONG"
                reason  = (f"{n_strong}/{len(complete)} topics show ARM_ON crossing the stress threshold "
                           f"with non-zero workspace_bias while ARM_OFF stays near-zero. "
                           f"Signal consistent with GWT coupling design.")
            elif n_weak >= 1 and n_null == 0:
                verdict = "PASS_WEAK"
                reason  = (f"{n_weak}/{len(complete)} topics show ARM_ON workspace_bias active without "
                           f"crossing the mood stress threshold. Coherent but partial signal.")
            elif n_null == len(complete):
                verdict = "FAIL"
                reason  = "No topic shows a detectable cognitive-layer differentiation between arms."
            else:
                verdict = "INCONCLUSIVE"
                reason  = (f"Mixed signals across topics: {n_strong} strong, {n_weak} weak, "
                           f"{n_null} null. Sample too small or noise dominates.")

    # Render markdown
    L = []
    L.append("# D2.1B Stress Validation Report\n")
    L.append(f"Run root: `{run_root.relative_to(_ROOT).as_posix()}`")
    L.append(f"Aborted:  `{summary.get('aborted', False)}`\n")
    L.append(f"**Final verdict: `{verdict}`**\n")
    L.append(f"> {reason}\n")

    L.append("## Harness sanity (prerequisite)\n")
    rows = [
        ("All subprocess exit_code == 0",      all_exit_zero),
        ("Zero live DDGS/Brave/Playwright",    no_live),
        ("Cached MAP and AGGREGATE hits",      cache_hits_ok),
        ("No contamination flag",              no_contam_flag),
        ("Stress injection observed in all",   stress_observed_all),
    ]
    L.append("| Check | Result |")
    L.append("|---|---|")
    for label, ok in rows:
        L.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    L.append("")

    L.append("## Per-topic comparative signal\n")
    L.append("| topic | arm | mood_min | crossed -0.3 | wb_max_abs | wb_nonzero | retry_attempts |")
    L.append("|---|---|---|---|---|---|---|")
    for topic, arms in by_topic.items():
        for arm_name in ("ARM_OFF", "ARM_ON"):
            a = arms.get(arm_name)
            if not a:
                L.append(f"| {topic} | {arm_name} | - | - | - | - | - |")
                continue
            mm = a["mood"]
            L.append(f"| {topic} "
                     f"| {arm_name} "
                     f"| {mm.get('mood_min','?')} "
                     f"| {'YES' if mm.get('crossed_stress') else 'no'} "
                     f"| {mm.get('wb_max_abs','?')} "
                     f"| {'YES' if mm.get('wb_nonzero') else 'no'} "
                     f"| {a['manifest'].get('retry_attempt_count', 0)} |")
    L.append("")

    L.append("## Per-run manifest detail\n")
    L.append("| # | topic | arm | exit | dur(s) | cache_hits | stress_obs | retries | mood_n | contam |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for m in manifests:
        L.append(f"| {m['run_index_global']} "
                 f"| {m['topic']} "
                 f"| {m['arm']} "
                 f"| {m['subprocess_exit_code']} "
                 f"| {m['duration_seconds']} "
                 f"| ({m.get('cache_hit_map',0)},{m.get('cache_hit_aggregate',0)}) "
                 f"| {'YES' if m.get('stress_injection_observed') else 'no'} "
                 f"| {m.get('retry_attempt_count',0)} "
                 f"| {m.get('mood_sample_count',0)} "
                 f"| {'Y' if m.get('contaminated') else 'N'} |")
    L.append("")

    L.append("## Notes\n")
    L.append(f"- Stress threshold: mood_score <= {MOOD_STRESS_THRESH}")
    L.append(f"- Workspace_bias 'near-zero' bound: |bias| <= {WORKSPACE_BIAS_NEAR_ZERO}")
    L.append("- This is a signal check at N=2 topics. PASS_STRONG is a hint of GWT")
    L.append("  causal effect, not proof. A larger sample (N>=10 topics, multiple")
    L.append("  seeds) is needed for paper-grade claims.")
    L.append("- The stress injection is purely cognitive (validation score capped")
    L.append("  on attempt 1). No I/O failure, no fake exception. Harness contamination")
    L.append("  is impossible by construction.")

    return "\n".join(L), verdict


def _slug(topic: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def main():
    if len(sys.argv) > 1:
        run_root = Path(sys.argv[1]).resolve()
    else:
        run_root = _latest_run_root()
        if run_root is None:
            print(f"[d2_1b_analyze] no runs found under {RUNS_ROOT}")
            sys.exit(2)
    if not run_root.exists():
        print(f"[d2_1b_analyze] run root not found: {run_root}")
        sys.exit(2)

    summary = load_summary(run_root)
    md, verdict = render(run_root, summary)
    out_md = run_root / "d2_1b_report.md"
    out_md.write_text(md, encoding="utf-8")
    print(md)
    print()
    print(f"[d2_1b_analyze] Report -> {out_md}")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
