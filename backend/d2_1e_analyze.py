"""d2_1e_analyze.py -- behavioral effect probe analyzer.

D2.1E asks whether calibrated GWT/Mood signal propagation is associated
with observable behavior in the observer cycle. Metrics are conservative:
missing or weakly structured fields are reported as MISSING/UNAVAILABLE
instead of being inferred.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_1e_runs"
WORKSPACE_BIAS_NEAR_ZERO = 0.01

MISSING = "MISSING"
UNAVAILABLE = "UNAVAILABLE"

CERT_RANK = {
    "FAILED": 0,
    "NEAR_MISS": 1,
    "CERTIFIED": 2,
}


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    candidates = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def load_summary(run_root: Path) -> dict:
    path = run_root / "d2_1e_summary.json"
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


def observer_section(text: str, observer_topic: str) -> tuple[str, bool]:
    marker = f"Starting study of '{observer_topic}'"
    idx = text.find(marker)
    if idx < 0:
        return "", False
    return text[idx:], True


def _normalize_strategy_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text[:180]


def mood_stats(samples: list[dict]) -> dict:
    if not samples:
        return {
            "available": False,
            "n": 0,
            "mood_traj": [],
            "wb_traj": [],
            "observer_mood_traj": [],
            "observer_wb_traj": [],
            "workspace_bias_present": False,
            "mood_min": MISSING,
            "mood_recovery_delta": MISSING,
        }
    scores = [float(s["mood_score"]) for s in samples]
    wb = [float(s.get("components", {}).get("workspace_bias", 0.0)) for s in samples]
    split = max(1, len(scores) // 2)
    observer_scores = scores[split:]
    observer_wb = wb[split:]
    if observer_scores:
        mood_min: float | str = round(min(observer_scores), 3)
        mood_recovery_delta: float | str = round(observer_scores[-1] - min(observer_scores), 3)
    else:
        mood_min = MISSING
        mood_recovery_delta = MISSING
    return {
        "available": True,
        "n": len(scores),
        "mood_traj": scores,
        "wb_traj": wb,
        "observer_mood_traj": observer_scores,
        "observer_wb_traj": observer_wb,
        "workspace_bias_present": any(abs(x) > WORKSPACE_BIAS_NEAR_ZERO for x in observer_wb),
        "observer_wb_nonzero_count": sum(1 for x in observer_wb if abs(x) > WORKSPACE_BIAS_NEAR_ZERO),
        "mood_min": mood_min,
        "mood_recovery_delta": mood_recovery_delta,
    }


def log_signal_stats(text: str) -> dict:
    tensions = re.findall(
        r"\[GWT_BID_TRACE\]\s+tensions\s+block=behavior_directive.*?-> bid=([0-9.]+)",
        text,
    )
    return {
        "gwt_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\]", text)),
        "tensions_bid_trace_count": len(tensions),
        "tensions_bid_values": [float(x) for x in tensions],
        "workspace_winner_broadcast_count": len(re.findall(r"workspace_winner", text)),
    }


def behavior_metrics(section: str, observer_found: bool) -> dict:
    if not observer_found:
        return {
            "observer_section_found": False,
            "recovery_success": MISSING,
            "retries_count": MISSING,
            "strategy_shift_detected": MISSING,
            "certification_verdict": MISSING,
            "final_score": MISSING,
            "benchmark_score": MISSING,
            "repeated_strategy_count": MISSING,
            "loop_risk_proxy": MISSING,
            "metrics_available": False,
        }

    retry_matches = re.findall(r"Regenerating code \(attempt \d+/\d+", section, flags=re.I)
    retries_count = len(retry_matches)

    strategy_shift_patterns = [
        r"\[CRITIC-LLM\] Injecting meta-critique",
        r"\[SWARM\] Activating",
        r"\[VETTORE 1\+2\]",
        r"STRUCTURAL PIVOT",
        r"\[STUDY\] Using past strategy",
    ]
    strategy_shift_detected = any(re.search(p, section, flags=re.I) for p in strategy_shift_patterns)

    cert_matches = re.findall(
        r"\[CERTIFY\].*?(CERTIFIED|FAILED).*?score\s+([0-9]+(?:\.[0-9]+)?)",
        section,
        flags=re.I,
    )
    if cert_matches:
        certification_verdict = cert_matches[-1][0].upper()
        final_score: float | str = round(float(cert_matches[-1][1]), 3)
    else:
        certification_verdict = MISSING
        final_score = MISSING

    bench_matches = re.findall(
        r"\[BENCHMARK_RUN\].*?:\s+(\d+)/(\d+)\s+passed.*?pass_rate=([0-9]+)%",
        section,
        flags=re.I,
    )
    benchmark_score: float | str
    if bench_matches:
        passed, total, pass_rate = bench_matches[-1]
        benchmark_score = UNAVAILABLE if int(total) == 0 else round(float(pass_rate) / 100.0, 3)
    else:
        benchmark_score = MISSING

    strategy_texts = []
    for match in re.findall(r"Focus:\s*(.+)", section, flags=re.I):
        strategy_texts.append(_normalize_strategy_text(match))
    for match in re.findall(r"gaps:\s*(\[[^\]]+\])", section, flags=re.I):
        strategy_texts.append(_normalize_strategy_text(match))
    repeated_strategy_count = max(0, len(strategy_texts) - len(set(strategy_texts)))

    if certification_verdict == MISSING and final_score == MISSING:
        recovery_success: bool | str = MISSING
    else:
        recovery_success = (
            certification_verdict == "CERTIFIED"
            or (isinstance(final_score, float) and final_score >= 7.5)
        )

    if recovery_success == MISSING:
        loop_risk_proxy: int | str = UNAVAILABLE
    else:
        loop_risk_proxy = retries_count + repeated_strategy_count + (0 if recovery_success else 1)

    return {
        "observer_section_found": True,
        "recovery_success": recovery_success,
        "retries_count": retries_count,
        "strategy_shift_detected": strategy_shift_detected,
        "certification_verdict": certification_verdict,
        "final_score": final_score,
        "benchmark_score": benchmark_score,
        "repeated_strategy_count": repeated_strategy_count,
        "loop_risk_proxy": loop_risk_proxy,
        "metrics_available": True,
    }


def _compare_numeric(on_value: Any, off_value: Any, lower_is_better: bool) -> str:
    if not isinstance(on_value, (int, float)) or not isinstance(off_value, (int, float)):
        return "missing"
    if on_value == off_value:
        return "equal"
    if lower_is_better:
        return "on_better" if on_value < off_value else "on_worse"
    return "on_better" if on_value > off_value else "on_worse"


def compare_behavior(on_behavior: dict, off_behavior: dict, on_mood: dict, off_mood: dict) -> tuple[list[str], list[str], list[str]]:
    advantages = []
    regressions = []
    missing = []

    comparisons = [
        ("fewer_retries", on_behavior.get("retries_count"), off_behavior.get("retries_count"), True),
        ("lower_loop_risk_proxy", on_behavior.get("loop_risk_proxy"), off_behavior.get("loop_risk_proxy"), True),
        ("less_severe_mood_min", on_mood.get("mood_min"), off_mood.get("mood_min"), False),
        ("better_mood_recovery_delta", on_mood.get("mood_recovery_delta"), off_mood.get("mood_recovery_delta"), False),
        ("higher_final_score", on_behavior.get("final_score"), off_behavior.get("final_score"), False),
    ]
    for label, on_value, off_value, lower_is_better in comparisons:
        result = _compare_numeric(on_value, off_value, lower_is_better)
        if result == "on_better":
            advantages.append(label)
        elif result == "on_worse":
            regressions.append(label)
        elif result == "missing":
            missing.append(label)

    on_cert = on_behavior.get("certification_verdict")
    off_cert = off_behavior.get("certification_verdict")
    if on_cert in CERT_RANK and off_cert in CERT_RANK:
        if CERT_RANK[on_cert] > CERT_RANK[off_cert]:
            advantages.append("better_certification_verdict")
        elif CERT_RANK[on_cert] < CERT_RANK[off_cert]:
            regressions.append("worse_certification_verdict")
    else:
        missing.append("certification_verdict")

    if on_behavior.get("strategy_shift_detected") is True and off_behavior.get("strategy_shift_detected") is False:
        advantages.append("strategy_shift_only_in_arm_on")
    elif on_behavior.get("strategy_shift_detected") is False and off_behavior.get("strategy_shift_detected") is True:
        regressions.append("strategy_shift_only_in_arm_off")
    elif on_behavior.get("strategy_shift_detected") == MISSING or off_behavior.get("strategy_shift_detected") == MISSING:
        missing.append("strategy_shift_detected")

    return advantages, regressions, missing


def render(run_root: Path, summary: dict) -> tuple[str, str, dict]:
    observer_topic = summary.get("observer_topic") or summary.get("topic_sequence", ["", ""])[1]
    manifests = summary.get("manifests", [])
    arms_data = {}
    for manifest in manifests:
        run_dir = run_root / manifest["arm"].lower()
        text = load_log_text(run_dir)
        observer_text, found = observer_section(text, observer_topic)
        arms_data[manifest["arm"]] = {
            "manifest": manifest,
            "mood": mood_stats(load_mood_samples(run_dir)),
            "signal": log_signal_stats(text),
            "behavior": behavior_metrics(observer_text, found),
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
    mood_samples_ok = all((arms_data.get(m.get("arm"), {}).get("mood", {}).get("n", 0) or 0) > 0 for m in manifests)
    fallback_ok = all(m.get("fallback_count", 0) <= 10 for m in manifests)

    on_data = arms_data.get("ARM_ON")
    off_data = arms_data.get("ARM_OFF")

    if not all_exit_zero or not stress_observed_all or not seq_observed_all:
        verdict = "CONTAMINATED"
        reason = "Subprocess failure, missing stress injection, or missing topic sequence."
        advantages: list[str] = []
        regressions: list[str] = []
        missing: list[str] = []
    elif (not no_live) or (not cache_hits_ok) or (not no_contam_flag) or (not mood_samples_ok) or (not fallback_ok):
        verdict = "CONTAMINATED"
        reason = "Harness contamination detected: live calls, cache failure, missing mood samples, or fallback threshold breach."
        advantages = []
        regressions = []
        missing = []
    elif not on_data or not off_data:
        verdict = "INCONCLUSIVE"
        reason = "Missing ARM_ON or ARM_OFF run."
        advantages = []
        regressions = []
        missing = []
    else:
        arm_on_signal = (
            on_data["mood"].get("workspace_bias_present") is True
            and on_data["signal"].get("tensions_bid_trace_count", 0) > 0
        )
        off_fallback_excluded = (
            off_data["mood"].get("workspace_bias_present") is True
            and off_data["manifest"].get("arm_no_l3") is True
        )
        advantages, regressions, missing = compare_behavior(
            on_data["behavior"],
            off_data["behavior"],
            on_data["mood"],
            off_data["mood"],
        )
        metrics_sparse = (
            not on_data["behavior"].get("observer_section_found")
            or not off_data["behavior"].get("observer_section_found")
            or len(missing) >= 4
        )

        if metrics_sparse:
            verdict = "INCONCLUSIVE"
            reason = "Harness clean, but observer-cycle behavioral metrics are too sparse or missing."
        elif not arm_on_signal:
            verdict = "INCONCLUSIVE"
            reason = "Harness clean, but ARM_ON real workspace signal was not present in the observer cycle."
        elif len(advantages) >= 2 and len(regressions) == 0:
            verdict = "PASS_STRONG"
            reason = "ARM_ON has real workspace signal and at least two behavioral advantages without major regression."
        elif len(advantages) >= 1:
            verdict = "PASS_WEAK"
            reason = "ARM_ON has real workspace signal and at least one plausible behavioral advantage."
        else:
            verdict = "FAIL"
            reason = "ARM_ON signal is present, but no behavioral metric improves versus ARM_OFF."
        if off_fallback_excluded:
            reason += " ARM_OFF fallback bias is classified separately and excluded from the GWT signal."

    lines = []
    lines.append("# D2.1E Behavioral Effect Probe Report\n")
    lines.append(f"Run root: `{run_root.relative_to(_ROOT).as_posix()}`")
    lines.append(f"Observer topic: `{observer_topic}`")
    lines.append(f"Aborted: `{summary.get('aborted', False)}`\n")
    lines.append(f"**Final verdict: `{verdict}`**\n")
    lines.append(f"> {reason}\n")

    lines.append("## Harness sanity\n")
    rows = [
        ("All subprocess exit_code == 0", all_exit_zero),
        ("Zero live DDGS/Brave/Playwright", no_live),
        ("Cached MAP/AGG hooks fired >= 2x per arm", cache_hits_ok),
        ("No contamination flag", no_contam_flag),
        ("Stress injection observed", stress_observed_all),
        ("Force-topic-sequence observed >= 2x", seq_observed_all),
        ("Mood samples present", mood_samples_ok),
        ("Fallback threshold not breached", fallback_ok),
    ]
    lines.append("| Check | Result |")
    lines.append("|---|---|")
    for label, ok in rows:
        lines.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    lines.append("")

    lines.append("## Raw mood / signal traces\n")
    lines.append("| arm | mood traj | wb traj | observer mood | observer wb | wb present | tensions traces |")
    lines.append("|---|---|---|---|---|---|---:|")
    for arm_name in ("ARM_OFF", "ARM_ON"):
        data = arms_data.get(arm_name)
        if not data:
            lines.append(f"| {arm_name} | - | - | - | - | - | - |")
            continue
        mood = data["mood"]
        signal = data["signal"]
        lines.append(
            f"| {arm_name} | {mood.get('mood_traj', [])} | {mood.get('wb_traj', [])} "
            f"| {mood.get('observer_mood_traj', [])} | {mood.get('observer_wb_traj', [])} "
            f"| {mood.get('workspace_bias_present')} | {signal.get('tensions_bid_trace_count', 0)} |"
        )
    lines.append("")

    lines.append("## Behavioral metrics\n")
    metric_names = [
        "recovery_success",
        "retries_count",
        "strategy_shift_detected",
        "certification_verdict",
        "final_score",
        "benchmark_score",
        "repeated_strategy_count",
        "loop_risk_proxy",
    ]
    lines.append("| metric | ARM_OFF | ARM_ON |")
    lines.append("|---|---|---|")
    for metric in metric_names:
        off_value = off_data["behavior"].get(metric, MISSING) if off_data else MISSING
        on_value = on_data["behavior"].get(metric, MISSING) if on_data else MISSING
        lines.append(f"| `{metric}` | `{off_value}` | `{on_value}` |")
    lines.append(f"| `mood_min` | `{off_data['mood'].get('mood_min', MISSING) if off_data else MISSING}` | `{on_data['mood'].get('mood_min', MISSING) if on_data else MISSING}` |")
    lines.append(f"| `mood_recovery_delta` | `{off_data['mood'].get('mood_recovery_delta', MISSING) if off_data else MISSING}` | `{on_data['mood'].get('mood_recovery_delta', MISSING) if on_data else MISSING}` |")
    lines.append(f"| `workspace_bias_present` | `{off_data['mood'].get('workspace_bias_present', MISSING) if off_data else MISSING}` | `{on_data['mood'].get('workspace_bias_present', MISSING) if on_data else MISSING}` |")
    lines.append("")

    lines.append("## Behavioral comparison\n")
    lines.append(f"- Advantages: {advantages if advantages else []}")
    lines.append(f"- Regressions: {regressions if regressions else []}")
    lines.append(f"- Missing/limited comparisons: {missing if missing else []}")
    lines.append("- ARM_OFF fallback bias, when present with `no_l3=True`, is excluded from the GWT signal.")
    lines.append("")

    lines.append("## Interpretation\n")
    lines.append("D2.1E separates internal signal propagation from behavioral effect. Non-zero workspace_bias is a signal metric; behavioral value requires improvements in observer-cycle metrics.")
    lines.append("")
    lines.append("Allowed positive claim if supported:")
    lines.append("")
    lines.append("```text")
    lines.append("Under this controlled sequential protocol, calibrated GWT/Mood coupling is associated with measurable behavioral differences in the observer cycle.")
    lines.append("```")
    lines.append("")
    lines.append("Not allowed:")
    lines.append("")
    lines.append("```text")
    lines.append("GWT improves SHARD performance.")
    lines.append("```")

    details = {
        "arms_data": arms_data,
        "advantages": advantages,
        "regressions": regressions,
        "missing": missing,
        "harness": {
            "all_exit_zero": all_exit_zero,
            "no_live": no_live,
            "cache_hits_ok": cache_hits_ok,
            "no_contam_flag": no_contam_flag,
            "stress_observed_all": stress_observed_all,
            "seq_observed_all": seq_observed_all,
            "mood_samples_ok": mood_samples_ok,
            "fallback_ok": fallback_ok,
        },
    }
    return "\n".join(lines), verdict, details


def main() -> None:
    if len(sys.argv) > 1:
        run_root = Path(sys.argv[1]).resolve()
    else:
        run_root = _latest_run_root()
        if run_root is None:
            print(f"[d2_1e_analyze] no runs found under {RUNS_ROOT}")
            sys.exit(2)
    if not run_root.exists():
        print(f"[d2_1e_analyze] run root not found: {run_root}")
        sys.exit(2)

    summary = load_summary(run_root)
    markdown, verdict, _details = render(run_root, summary)
    out_path = run_root / "d2_1e_report.md"
    out_path.write_text(markdown, encoding="utf-8")
    print(markdown)
    print()
    print(f"[d2_1e_analyze] Report -> {out_path}")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
