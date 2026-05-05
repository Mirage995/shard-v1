"""d2_1d_analyze.py -- verdict for D2.1D tensions-bias calibration.

D2.1D tests one pre-registered calibration patch:

    _WINNER_BIAS["tensions"] = (-0.05, +0.15)

It does not test operational improvement. It tests whether the previously
silent stress-dominant winner can propagate into next-cycle MoodEngine
workspace_bias under the same sequential protocol used by D2.1C.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_1d_runs"
WORKSPACE_BIAS_NEAR_ZERO = 0.01

SUBCODE_ARM_OFF_FALLBACK_EXCLUDED = "ARM_OFF_FALLBACK_BIAS_EXCLUDED_FROM_GWT_SIGNAL"
SUBCODE_ARM_ON_TENSIONS_SIGNAL = "ARM_ON_TENSIONS_WINNER_NONZERO_BIAS"
SUBCODE_ARM_ON_PROVENANCE_INCOMPLETE = "ARM_ON_NONZERO_BIAS_PROVENANCE_INCOMPLETE"
SUBCODE_ARM_ON_ZERO_WITH_PATCH = "ARM_ON_ZERO_BIAS_DESPITE_TENSIONS_PATCH"


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    candidates = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def load_summary(run_root: Path) -> dict:
    path = run_root / "d2_1d_summary.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_mood_samples(run_dir: Path) -> list[dict]:
    path = run_dir / "mood_samples.jsonl"
    if not path.exists():
        return []
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return samples


def load_log_text(run_dir: Path) -> str:
    parts = []
    for name in ("stdout.log", "stderr.log"):
        path = run_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def mood_stats(samples: list[dict]) -> dict:
    if not samples:
        return {
            "available": False,
            "n": 0,
            "mood_traj": [],
            "wb_traj": [],
            "cycle2_wb_traj": [],
            "cycle2_wb_nonzero_count": 0,
        }
    scores = [float(s["mood_score"]) for s in samples]
    wb = [float(s.get("components", {}).get("workspace_bias", 0.0)) for s in samples]
    split = max(1, len(wb) // 2)
    cycle2_wb = wb[split:]
    return {
        "available": True,
        "n": len(scores),
        "mood_min": round(min(scores), 3),
        "mood_max": round(max(scores), 3),
        "mood_mean": round(statistics.mean(scores), 3),
        "mood_traj": scores,
        "wb_traj": wb,
        "wb_nonzero_count": sum(1 for x in wb if abs(x) > WORKSPACE_BIAS_NEAR_ZERO),
        "wb_max_abs": round(max(abs(x) for x in wb) if wb else 0.0, 4),
        "cycle2_wb_traj": cycle2_wb,
        "cycle2_wb_nonzero_count": sum(1 for x in cycle2_wb if abs(x) > WORKSPACE_BIAS_NEAR_ZERO),
        "cycle2_wb_max_abs": round(max(abs(x) for x in cycle2_wb) if cycle2_wb else 0.0, 4),
    }


def log_stats(text: str) -> dict:
    tensions = re.findall(
        r"\[GWT_BID_TRACE\]\s+tensions\s+block=behavior_directive.*?-> bid=([0-9.]+)",
        text,
    )
    return {
        "gwt_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\]", text)),
        "tensions_bid_trace_count": len(tensions),
        "tensions_bid_values": [float(x) for x in tensions],
        "workspace_winner_broadcast_count": len(re.findall(r"workspace_winner", text)),
        "ignition_failed_mentions": len(re.findall(r"ignition_failed", text)),
    }


def render(run_root: Path, summary: dict) -> tuple[str, str, dict]:
    manifests = summary.get("manifests", [])
    arms_data = {}
    for manifest in manifests:
        run_dir = run_root / manifest["arm"].lower()
        arms_data[manifest["arm"]] = {
            "manifest": manifest,
            "mood": mood_stats(load_mood_samples(run_dir)),
            "log": log_stats(load_log_text(run_dir)),
        }

    all_exit_zero = all(m.get("subprocess_exit_code") == 0 for m in manifests)
    no_live = all(
        m.get("ddgs_call_count", 0) == 0
        and m.get("brave_call_count", 0) == 0
        and m.get("playwright_call_count", 0) == 0
        for m in manifests
    )
    cache_hits_ok = all(m.get("cache_hit_map", 0) >= 2 and m.get("cache_hit_aggregate", 0) >= 2 for m in manifests)
    no_contam_flag = all(not m.get("contaminated", False) for m in manifests)
    stress_observed_all = all(m.get("stress_injection_observed", False) for m in manifests)
    seq_observed_all = all(m.get("force_topic_seq_observed", False) for m in manifests)

    on_data = arms_data.get("ARM_ON")
    off_data = arms_data.get("ARM_OFF")
    subcodes: list[str] = []

    if not all_exit_zero or not stress_observed_all or not seq_observed_all:
        verdict = "CONTAMINATED"
        reason = "Subprocess failure, missing stress injection, or missing topic sequence."
    elif (not no_live) or (not cache_hits_ok) or (not no_contam_flag):
        verdict = "CONTAMINATED"
        reason = "Harness contamination detected: live calls, missing cache hits, or contaminated manifest."
    elif not on_data or not off_data:
        verdict = "INCONCLUSIVE"
        reason = "Missing ARM_ON or ARM_OFF run."
    else:
        on_cycle2_nonzero = on_data["mood"]["cycle2_wb_nonzero_count"] > 0
        off_cycle2_nonzero = off_data["mood"]["cycle2_wb_nonzero_count"] > 0
        arm_on_tensions = on_data["log"]["tensions_bid_trace_count"] > 0
        off_fallback_artifact = off_cycle2_nonzero and off_data["manifest"].get("arm_no_l3") is True

        if off_fallback_artifact:
            subcodes.append(SUBCODE_ARM_OFF_FALLBACK_EXCLUDED)

        if on_cycle2_nonzero and arm_on_tensions:
            verdict = "PASS_STRONG"
            subcodes.append(SUBCODE_ARM_ON_TENSIONS_SIGNAL)
            reason = (
                "ARM_ON shows non-zero cycle-2 workspace_bias and log evidence that "
                "`tensions` was active in GWT bid traces. ARM_OFF non-zero bias, if present, "
                "is classified separately as fallback artifact and excluded from the GWT signal."
            )
        elif on_cycle2_nonzero:
            verdict = "PASS_WEAK"
            subcodes.append(SUBCODE_ARM_ON_PROVENANCE_INCOMPLETE)
            reason = (
                "ARM_ON shows non-zero cycle-2 workspace_bias, but structured provenance is "
                "incomplete or `tensions` dominance was not visible in parsed bid traces."
            )
        else:
            verdict = "FAIL"
            subcodes.append(SUBCODE_ARM_ON_ZERO_WITH_PATCH)
            reason = (
                "ARM_ON cycle-2 workspace_bias stayed near zero despite the non-zero "
                "`tensions` coupling patch."
            )

    lines = []
    lines.append("# D2.1D Tensions-Bias Calibration Report\n")
    lines.append(f"Run root: `{run_root.relative_to(_ROOT).as_posix()}`")
    lines.append(f"Aborted: `{summary.get('aborted', False)}`\n")
    lines.append(f"**Final verdict: `{verdict}`**\n")
    lines.append(f"> {reason}\n")
    if subcodes:
        lines.append("Diagnostic subcodes:")
        for code in subcodes:
            lines.append(f"- `{code}`")
        lines.append("")

    lines.append("## Harness sanity\n")
    rows = [
        ("All subprocess exit_code == 0", all_exit_zero),
        ("Zero live DDGS/Brave/Playwright", no_live),
        ("Cached MAP/AGG hooks fired >= 2x per arm", cache_hits_ok),
        ("No contamination flag", no_contam_flag),
        ("Stress injection observed", stress_observed_all),
        ("Force-topic-sequence observed >= 2x", seq_observed_all),
    ]
    lines.append("| Check | Result |")
    lines.append("|---|---|")
    for label, ok in rows:
        lines.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    lines.append("")

    lines.append("## Per-arm signal\n")
    lines.append("| arm | mood_n | mood traj | wb traj | cycle2 wb traj | cycle2 nonzero | tensions bid traces |")
    lines.append("|---|---:|---|---|---|---:|---:|")
    for arm_name in ("ARM_OFF", "ARM_ON"):
        data = arms_data.get(arm_name)
        if not data:
            lines.append(f"| {arm_name} | - | - | - | - | - | - |")
            continue
        mood = data["mood"]
        log = data["log"]
        lines.append(
            f"| {arm_name} | {mood.get('n', 0)} | {mood.get('mood_traj', [])} "
            f"| {mood.get('wb_traj', [])} | {mood.get('cycle2_wb_traj', [])} "
            f"| {mood.get('cycle2_wb_nonzero_count', 0)} "
            f"| {log.get('tensions_bid_trace_count', 0)} |"
        )
    lines.append("")

    lines.append("## Provenance classification\n")
    lines.append("- ARM_OFF `workspace_bias` is not counted as GWT signal when it occurs with `no_l3=True`; it is classified as synthetic ignition-failure fallback artifact.")
    lines.append("- ARM_ON `workspace_bias` is counted as compatible with real workspace-winner bias only when non-zero cycle-2 samples coincide with parsed `tensions` GWT bid traces.")
    lines.append("- This analyzer still uses log-derived provenance; a future harness should write structured `winner_module`, `ignition_failed`, `valence_delta`, and `arousal_delta` fields.")
    lines.append("")

    lines.append("## Notes\n")
    lines.append(f"- Workspace_bias near-zero bound: |bias| <= {WORKSPACE_BIAS_NEAR_ZERO}")
    lines.append("- D2.1D tests propagation of a calibrated internal signal, not behavior-level performance.")
    lines.append("- Allowed claim: the previously silent stress-dominant winner can propagate into next-cycle MoodEngine computation if the verdict is PASS.")
    lines.append("- Not allowed: an outcome-level performance claim from GWT activation.")

    details = {
        "arms_data": arms_data,
        "subcodes": subcodes,
        "harness": {
            "all_exit_zero": all_exit_zero,
            "no_live": no_live,
            "cache_hits_ok": cache_hits_ok,
            "no_contam_flag": no_contam_flag,
            "stress_observed_all": stress_observed_all,
            "seq_observed_all": seq_observed_all,
        },
    }
    return "\n".join(lines), verdict, details


def main() -> None:
    if len(sys.argv) > 1:
        run_root = Path(sys.argv[1]).resolve()
    else:
        run_root = _latest_run_root()
        if run_root is None:
            print(f"[d2_1d_analyze] no runs found under {RUNS_ROOT}")
            sys.exit(2)
    if not run_root.exists():
        print(f"[d2_1d_analyze] run root not found: {run_root}")
        sys.exit(2)

    summary = load_summary(run_root)
    markdown, verdict, _details = render(run_root, summary)
    out_path = run_root / "d2_1d_report.md"
    out_path.write_text(markdown, encoding="utf-8")
    print(markdown)
    print()
    print(f"[d2_1d_analyze] Report -> {out_path}")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
