"""d2_1a_analyze.py -- Verdict for D2.1A Harness Validation.

Reads a d2_1a_runs/<TIMESTAMP>/ directory produced by d2_1a_benchmark.py
and emits a harness-only verdict. Strictly no GWT / cognitive layer
interpretation: this analyzer answers ONE question.

    "Did the harness produce isolated, reproducible, uncontaminated
     runs?"

Verdict:
    PASS         -> harness suitable for D2.1B stress validation
    FAIL         -> subprocess / harness / storage / mood linkage broken
    CONTAMINATED -> network used while in cached mode, or threshold breached
    INCONCLUSIVE -> runs completed but variance too high or metrics missing

PASS criteria (all must hold):
    - all subprocess exit codes == 0
    - all runs used cached MAP (cache_hit_map > 0)
    - all runs used cached AGGREGATE (cache_hit_aggregate > 0)
    - 0 ddgs/brave/playwright calls across every run
    - cache_hash equal between run_a and run_b for each topic
    - fallback_count <= 10 per arm
    - http_error_count <= 3 per arm
    - no contaminated flag
    - no progressive degradation in run_index 1->N

Usage:
    python backend/d2_1a_analyze.py shard_workspace/d2_1a_runs/<TIMESTAMP>
    python backend/d2_1a_analyze.py            # picks latest run dir
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT     = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_1a_runs"


def _latest_run_root() -> Path:
    if not RUNS_ROOT.exists():
        return None
    candidates = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def load_summary(run_root: Path) -> dict:
    f = run_root / "d2_1a_summary.json"
    if not f.exists():
        raise FileNotFoundError(f"Missing summary: {f}")
    return json.loads(f.read_text(encoding="utf-8"))


def render(run_root: Path, summary: dict) -> str:
    manifests = summary.get("manifests", [])
    n = len(manifests)

    # Aggregations
    by_topic = defaultdict(list)
    for m in manifests:
        by_topic[m["topic"]].append(m)

    # Pre-checks (boolean)
    all_exit_zero        = all(m["subprocess_exit_code"] == 0 for m in manifests)
    all_cache_map_hit    = all(m.get("cache_hit_map", 0) > 0      for m in manifests)
    all_cache_agg_hit    = all(m.get("cache_hit_aggregate", 0) > 0 for m in manifests)
    no_ddgs              = all(m.get("ddgs_call_count", 0) == 0       for m in manifests)
    no_brave             = all(m.get("brave_call_count", 0) == 0      for m in manifests)
    no_playwright        = all(m.get("playwright_call_count", 0) == 0 for m in manifests)
    fallback_within      = all(m.get("fallback_count", 0) <= 10  for m in manifests)
    http_within          = all(m.get("http_error_count", 0) <= 3 for m in manifests)
    no_contam_flag       = all(not m.get("contaminated", False)  for m in manifests)

    # Cache hash equality per topic
    hash_match = {}
    for topic, runs in by_topic.items():
        hashes = {m.get("cache_hash") for m in runs}
        hash_match[topic] = (len(hashes) == 1)
    all_hash_match = all(hash_match.values())

    # Mood linkage check
    mood_present = all(m.get("mood_sample_count", 0) > 0 for m in manifests)

    # Progressive degradation: durations should not strictly increase by >2x
    durations = [m["duration_seconds"] for m in manifests]
    progressive_degrade = False
    if len(durations) >= 3:
        progressive_degrade = all(durations[i] > durations[i-1] for i in range(1, len(durations))) \
            and durations[-1] > durations[0] * 2.0

    # Verdict tree
    if not all_exit_zero or not mood_present:
        verdict = "FAIL"
        reason  = "Subprocess exit code != 0 or mood samples missing -- harness pipeline broken."
    elif (not no_ddgs) or (not no_brave) or (not no_playwright) or (not no_contam_flag):
        verdict = "CONTAMINATED"
        reason  = "Network/scraping calls leaked into cached-mode runs."
    elif (not all_cache_map_hit) or (not all_cache_agg_hit):
        verdict = "CONTAMINATED"
        reason  = "Cached MAP / AGGREGATE hooks did not fire on every run."
    elif (not fallback_within) or (not http_within):
        verdict = "CONTAMINATED"
        reason  = "Fallback or HTTP error threshold exceeded."
    elif not all_hash_match:
        verdict = "FAIL"
        reason  = "cache_hash differs between run_a and run_b for some topic -- replica not identical."
    elif progressive_degrade:
        verdict = "INCONCLUSIVE"
        reason  = "Run durations grew monotonically and exceed 2x baseline -- possible state drift."
    else:
        verdict = "PASS"
        reason  = "Harness produced isolated, reproducible, uncontaminated runs."

    # ── Render markdown ────────────────────────────────────────────────────
    lines = []
    lines.append(f"# D2.1A Harness Validation Report\n")
    lines.append(f"Run root: `{run_root.relative_to(_ROOT).as_posix()}`")
    lines.append(f"Aborted:  `{summary.get('aborted', False)}`")
    lines.append("")
    lines.append(f"**Final verdict: `{verdict}`**")
    lines.append("")
    lines.append(f"> {reason}\n")

    lines.append("## Pre-flight checks\n")
    rows = [
        ("Subprocess isolation valid",      all_exit_zero),
        ("Mood samples linked",             mood_present),
        ("Cached MAP hook fired",           all_cache_map_hit),
        ("Cached AGGREGATE hook fired",     all_cache_agg_hit),
        ("Zero DDGS calls",                 no_ddgs),
        ("Zero Brave calls",                no_brave),
        ("Zero Playwright calls",           no_playwright),
        ("Fallback within threshold (<=10)", fallback_within),
        ("HTTP errors within threshold (<=3)", http_within),
        ("No contamination flag set",       no_contam_flag),
        ("cache_hash matches run_a == run_b", all_hash_match),
        ("No progressive duration degradation", not progressive_degrade),
    ]
    lines.append("| Check | Result |")
    lines.append("|---|---|")
    for label, ok in rows:
        lines.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    lines.append("")

    lines.append("## Per-run detail\n")
    lines.append(f"Total runs: **{n}**\n")
    lines.append("| # | topic | arm | exit | dur(s) | cache_hits (map,agg) | ddgs | brave | playwright | fallback | http_err | mood_n | contam | abort_reason |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m in manifests:
        lines.append(
            f"| {m['run_index_global']} "
            f"| {m['topic']} "
            f"| {m['arm']} "
            f"| {m['subprocess_exit_code']} "
            f"| {m['duration_seconds']} "
            f"| ({m.get('cache_hit_map',0)},{m.get('cache_hit_aggregate',0)}) "
            f"| {m.get('ddgs_call_count',0)} "
            f"| {m.get('brave_call_count',0)} "
            f"| {m.get('playwright_call_count',0)} "
            f"| {m.get('fallback_count',0)} "
            f"| {m.get('http_error_count',0)} "
            f"| {m.get('mood_sample_count',0)} "
            f"| {'Y' if m.get('contaminated') else 'N'} "
            f"| {m.get('abort_reason') or '-'} |"
        )
    lines.append("")

    lines.append("## cache_hash verification\n")
    for topic, runs in by_topic.items():
        hashes = [m.get("cache_hash", "?") for m in runs]
        lines.append(f"- `{topic}`")
        for m in runs:
            lines.append(f"    - {m['arm']}: {m.get('cache_hash', '?')}")
        match = "YES" if len(set(hashes)) == 1 else "NO"
        lines.append(f"    - **match: {match}**")
    lines.append("")

    lines.append("## Notes\n")
    lines.append("- This report is harness-only by design. No statement is made")
    lines.append("  about GWT, MoodEngine, agent performance, or emergent behavior.")
    lines.append("- D2.1A PASS unlocks D2.1B stress validation; FAIL or CONTAMINATED")
    lines.append("  requires fixing the harness before any cognitive interpretation.")

    return "\n".join(lines), verdict


def main():
    if len(sys.argv) > 1:
        run_root = Path(sys.argv[1]).resolve()
    else:
        run_root = _latest_run_root()
        if run_root is None:
            print(f"[d2_1a_analyze] no runs found under {RUNS_ROOT}")
            sys.exit(2)
    if not run_root.exists():
        print(f"[d2_1a_analyze] run root not found: {run_root}")
        sys.exit(2)

    summary = load_summary(run_root)
    md, verdict = render(run_root, summary)

    out_md   = run_root / "d2_1a_report.md"
    out_md.write_text(md, encoding="utf-8")
    print(md)
    print()
    print(f"[d2_1a_analyze] Report saved -> {out_md}")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
