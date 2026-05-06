"""d2_2d_analyze.py -- analyzer for D2.2D micro decision coupling.

D2.2D tests a single pre-registered reflection-directive micro-coupling.
The analyzer is intentionally conservative: unreliable metrics are reported
as MISSING/UNAVAILABLE and workspace_bias is treated as signal/provenance,
not performance.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_2d_runs"
DOC_REPORT = _ROOT / "docs" / "experiments" / "d2_2d_micro_decision_coupling.md"
WORKSPACE_BIAS_NEAR_ZERO = 0.01

MISSING = "MISSING"
UNAVAILABLE = "UNAVAILABLE"

CERT_RANK = {
    "FAILED": 0,
    "NEAR_MISS": 1,
    "CERTIFIED": 2,
}

PRIMARY_METRICS = [
    "recovery_success",
    "certification_verdict",
    "final_score",
    "benchmark_score",
    "retries_count",
    "loop_risk_proxy",
    "repeated_strategy_count",
]

SECONDARY_METRICS = [
    "mood_min",
    "mood_recovery_delta",
    "workspace_bias_present",
    "strategy_shift_detected",
    "fallback_provenance",
    "tensions_trace_count",
    "reflection_trigger_count",
    "reflection_directive_present",
    "micro_coupling_applied",
]


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    candidates = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def load_summary(run_root: Path) -> dict:
    path = run_root / "d2_2d_summary.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_dir_for_manifest(run_root: Path, manifest: dict) -> Path:
    return (
        run_root
        / manifest["sequence_id"]
        / f"rep_{int(manifest['rep']):02d}"
        / manifest["arm"].lower()
    )


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


def _mean(values: list[Any]) -> float | str:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return round(statistics.mean(nums), 4) if nums else UNAVAILABLE


def _rate(values: list[Any]) -> float | str:
    bools = [v for v in values if isinstance(v, bool)]
    return round(sum(1 for v in bools if v) / len(bools), 4) if bools else UNAVAILABLE


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
            "observer_wb_nonzero_count": 0,
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
        "tensions_trace_count": len(tensions),
        "tensions_bid_values": [float(x) for x in tensions],
        "workspace_winner_broadcast_count": len(re.findall(r"workspace_winner", text)),
        "ignition_failed_mentions": len(re.findall(r"ignition_failed", text)),
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
    if bench_matches:
        passed, total, pass_rate = bench_matches[-1]
        benchmark_score: float | str = UNAVAILABLE if int(total) == 0 else round(float(pass_rate) / 100.0, 3)
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


def structured_behavior_metrics(manifest: dict, section: str, observer_found: bool) -> dict:
    structured = manifest.get("behavior_metrics")
    if not isinstance(structured, dict):
        fallback = behavior_metrics(section, observer_found)
        fallback["metrics_source"] = "log_fallback"
        return fallback

    benchmark_score = structured.get("benchmark_score")
    benchmark_score_status = structured.get("benchmark_score_status", MISSING)
    if benchmark_score is None:
        benchmark_score = UNAVAILABLE if benchmark_score_status == UNAVAILABLE else MISSING

    return {
        "observer_section_found": structured.get("observer_section_found", False),
        "recovery_success": structured.get("recovery_success", MISSING),
        "retries_count": structured.get("retries_count", MISSING),
        "strategy_shift_detected": structured.get("strategy_shift_detected", MISSING),
        "certification_verdict": structured.get("certification_verdict", MISSING),
        "certification_rank": structured.get("certification_rank", MISSING),
        "final_score": structured.get("final_score", MISSING),
        "benchmark_score": benchmark_score,
        "benchmark_score_status": benchmark_score_status,
        "repeated_strategy_count": structured.get("repeated_strategy_count", MISSING),
        "loop_risk_proxy": structured.get("loop_risk_proxy", MISSING),
        "metrics_available": structured.get("metrics_available", False),
        "metrics_source": "structured_manifest",
    }


def structured_mood_stats(manifest: dict, fallback: dict) -> dict:
    structured = manifest.get("mood_metrics")
    if not isinstance(structured, dict):
        fallback["metrics_source"] = "mood_history_fallback"
        return fallback

    return {
        "available": structured.get("available", False),
        "n": structured.get("n", 0),
        "mood_traj": structured.get("mood_traj", []),
        "wb_traj": structured.get("workspace_bias_traj", []),
        "observer_mood_traj": structured.get("observer_mood_traj", []),
        "observer_wb_traj": structured.get("observer_workspace_bias_traj", []),
        "workspace_bias_present": structured.get("workspace_bias_present", False),
        "observer_wb_nonzero_count": structured.get("observer_workspace_bias_nonzero_count", 0),
        "mood_min": structured.get("mood_min", MISSING),
        "mood_recovery_delta": structured.get("mood_recovery_delta", MISSING),
        "metrics_source": "structured_manifest",
    }


def structured_signal_stats(manifest: dict, fallback: dict) -> dict:
    structured = manifest.get("signal_metrics")
    if not isinstance(structured, dict):
        fallback["metrics_source"] = "log_fallback"
        return fallback
    return {
        "gwt_bid_trace_count": structured.get("gwt_bid_trace_count", 0),
        "tensions_trace_count": structured.get("tensions_trace_count", 0),
        "tensions_bid_values": structured.get("tensions_bid_values", []),
        "workspace_winner_broadcast_count": structured.get("workspace_winner_broadcast_count", 0),
        "ignition_failed_mentions": structured.get("ignition_failed_mentions", 0),
        "metrics_source": "structured_manifest",
    }


def structured_bias_provenance(manifest: dict, mood: dict, signal: dict) -> dict:
    structured = manifest.get("bias_provenance")
    if isinstance(structured, dict):
        return {
            "workspace_bias_present": structured.get("workspace_bias_present", False),
            "real_workspace_signal": structured.get("real_workspace_signal", False),
            "fallback_bias_excluded": structured.get("fallback_bias_excluded", False),
            "workspace_bias_source": structured.get("workspace_bias_source", "not_observed"),
            "dominant_winner": structured.get("dominant_winner"),
            "winner_module": structured.get("winner_module"),
            "ignition_failed": structured.get("ignition_failed", False),
            "fallback_source": structured.get("fallback_source"),
            "tensions_trace_count": structured.get("tensions_trace_count", 0),
            "metrics_source": "structured_manifest",
        }

    fallback_bias = (
        manifest.get("arm_no_l3") is True and mood.get("workspace_bias_present") is True
    )
    real_signal = (
        manifest.get("arm") == "ARM_ON"
        and mood.get("workspace_bias_present") is True
        and signal.get("tensions_trace_count", 0) > 0
    )
    return {
        "workspace_bias_present": mood.get("workspace_bias_present") is True,
        "real_workspace_signal": real_signal,
        "fallback_bias_excluded": fallback_bias,
        "workspace_bias_source": (
            "real_workspace_winner"
            if real_signal
            else "synthetic_ignition_failure_fallback"
            if fallback_bias
            else "not_observed"
        ),
        "dominant_winner": "tensions" if signal.get("tensions_trace_count", 0) > 0 else None,
        "winner_module": "tensions" if signal.get("tensions_trace_count", 0) > 0 else None,
        "ignition_failed": fallback_bias,
        "fallback_source": "ignition_failure_fallback" if fallback_bias else None,
        "tensions_trace_count": signal.get("tensions_trace_count", 0),
        "metrics_source": "log_fallback",
    }


def log_decision_coupling_stats(text: str) -> dict:
    lines = re.findall(r"\[D2_2D_DECISION_COUPLING\][^\n\r]*", text)
    applied = [line for line in lines if re.search(r"\bapplied=1\b", line)]
    directive = [line for line in lines if re.search(r"\bdirective=1\b", line)]
    strategy_directive = [line for line in lines if re.search(r"\bstrategy_shift_directive=1\b", line)]
    repeated_failure = [line for line in lines if re.search(r"\brepeated_failure=1\b", line)]
    winners = []
    reasons = []
    for line in lines:
        winner_match = re.search(r"\bwinner=([A-Za-z_][A-Za-z0-9_]*|None)", line)
        reason_match = re.search(r"\breason=([A-Za-z_][A-Za-z0-9_]*)", line)
        if winner_match:
            winners.append(None if winner_match.group(1) == "None" else winner_match.group(1))
        if reason_match:
            reasons.append(reason_match.group(1))
    dominant_winner = "tensions" if "tensions" in winners else next((w for w in winners if w), None)
    return {
        "reflection_trigger_count": len(lines),
        "micro_coupling_applied": bool(applied),
        "micro_coupling_applied_count": len(applied),
        "micro_coupling_reason": reasons[-1] if reasons else None,
        "micro_coupling_reasons": reasons,
        "reflection_directive_present": bool(directive),
        "reflection_directive_count": len(directive),
        "strategy_shift_directive_present": bool(strategy_directive),
        "strategy_shift_directive_count": len(strategy_directive),
        "repeated_failure_detected": bool(repeated_failure),
        "repeated_failure_detected_count": len(repeated_failure),
        "dominant_winner": dominant_winner,
        "winner_trace": winners,
        "tensions_signal_provenance": "decision_coupling_marker" if "tensions" in winners else "not_observed",
        "metrics_source": "log_fallback",
    }


def structured_decision_coupling_stats(manifest: dict, fallback: dict) -> dict:
    structured = manifest.get("decision_coupling_metrics")
    if not isinstance(structured, dict):
        return fallback
    return {
        "reflection_trigger_count": structured.get("reflection_trigger_count", 0),
        "micro_coupling_applied": structured.get("micro_coupling_applied", False),
        "micro_coupling_applied_count": structured.get("micro_coupling_applied_count", 0),
        "micro_coupling_reason": structured.get("micro_coupling_reason"),
        "micro_coupling_reasons": structured.get("micro_coupling_reasons", []),
        "reflection_directive_present": structured.get("reflection_directive_present", False),
        "reflection_directive_count": structured.get("reflection_directive_count", 0),
        "strategy_shift_directive_present": structured.get("strategy_shift_directive_present", False),
        "strategy_shift_directive_count": structured.get("strategy_shift_directive_count", 0),
        "repeated_failure_detected": structured.get("repeated_failure_detected", False),
        "repeated_failure_detected_count": structured.get("repeated_failure_detected_count", 0),
        "dominant_winner": structured.get("dominant_winner"),
        "winner_trace": structured.get("winner_trace", []),
        "tensions_signal_provenance": structured.get("tensions_signal_provenance", "not_observed"),
        "metrics_source": "structured_manifest",
    }


def build_records(run_root: Path, summary: dict) -> list[dict]:
    records = []
    for manifest in summary.get("manifests", []):
        run_dir = run_dir_for_manifest(run_root, manifest)
        text = load_log_text(run_dir)
        observer_window = manifest.get("observer_window")
        if isinstance(observer_window, dict) and observer_window.get("found") is True:
            observer_text, found = observer_section(text, manifest["observer_topic"])
            found = True
        else:
            observer_text, found = observer_section(text, manifest["observer_topic"])
        mood = structured_mood_stats(manifest, mood_stats(load_mood_samples(run_dir)))
        signal = structured_signal_stats(manifest, log_signal_stats(text))
        behavior = structured_behavior_metrics(manifest, observer_text, found)
        bias = structured_bias_provenance(manifest, mood, signal)
        decision = structured_decision_coupling_stats(manifest, log_decision_coupling_stats(text))
        fallback_provenance = (
            "synthetic_ignition_failure_fallback"
            if bias.get("fallback_bias_excluded") is True
            else "not_observed"
        )
        records.append(
            {
                "manifest": manifest,
                "run_dir": run_dir,
                "mood": mood,
                "signal": signal,
                "behavior": behavior,
                "bias_provenance": bias,
                "decision_coupling": decision,
                "fallback_provenance": fallback_provenance,
                "arm_on_real_signal": bias.get("real_workspace_signal") is True,
            }
        )
    return records


def aggregate_records(records: list[dict]) -> dict:
    by_arm: dict[str, list[dict]] = {"ARM_OFF": [], "ARM_ON": []}
    by_sequence: dict[str, dict[str, list[dict]]] = {}
    for record in records:
        manifest = record["manifest"]
        arm = manifest["arm"]
        sequence_id = manifest["sequence_id"]
        by_arm.setdefault(arm, []).append(record)
        by_sequence.setdefault(sequence_id, {}).setdefault(arm, []).append(record)

    return {
        "by_arm": {arm: aggregate_bucket(bucket) for arm, bucket in by_arm.items()},
        "by_sequence": {
            seq: {arm: aggregate_bucket(bucket) for arm, bucket in arms.items()}
            for seq, arms in by_sequence.items()
        },
    }


def aggregate_bucket(bucket: list[dict]) -> dict:
    behaviors = [r["behavior"] for r in bucket]
    moods = [r["mood"] for r in bucket]
    signals = [r["signal"] for r in bucket]
    decisions = [r["decision_coupling"] for r in bucket]
    cert_ranks = []
    for behavior in behaviors:
        if isinstance(behavior.get("certification_rank"), (int, float)):
            cert_ranks.append(behavior["certification_rank"])
        elif behavior.get("certification_verdict") in CERT_RANK:
            cert_ranks.append(CERT_RANK[behavior["certification_verdict"]])
    bench_values = [
        b.get("benchmark_score")
        for b in behaviors
        if isinstance(b.get("benchmark_score"), (int, float))
    ]
    return {
        "n": len(bucket),
        "recovery_success_rate": _rate([b.get("recovery_success") for b in behaviors]),
        "certification_rank_mean": round(statistics.mean(cert_ranks), 4) if cert_ranks else UNAVAILABLE,
        "certification_verdict_counts": {
            value: sum(1 for b in behaviors if b.get("certification_verdict") == value)
            for value in sorted({b.get("certification_verdict") for b in behaviors})
            if value not in (None, MISSING)
        },
        "final_score_mean": _mean([b.get("final_score") for b in behaviors]),
        "benchmark_score_mean": round(statistics.mean(bench_values), 4) if bench_values else UNAVAILABLE,
        "retries_count_mean": _mean([b.get("retries_count") for b in behaviors]),
        "loop_risk_proxy_mean": _mean([b.get("loop_risk_proxy") for b in behaviors]),
        "repeated_strategy_count_mean": _mean([b.get("repeated_strategy_count") for b in behaviors]),
        "strategy_shift_rate": _rate([b.get("strategy_shift_detected") for b in behaviors]),
        "mood_min_mean": _mean([m.get("mood_min") for m in moods]),
        "mood_recovery_delta_mean": _mean([m.get("mood_recovery_delta") for m in moods]),
        "workspace_bias_present_rate": _rate([m.get("workspace_bias_present") for m in moods]),
        "tensions_trace_count_total": sum(int(s.get("tensions_trace_count", 0)) for s in signals),
        "reflection_trigger_count_total": sum(int(d.get("reflection_trigger_count", 0)) for d in decisions),
        "reflection_directive_present_rate": _rate([d.get("reflection_directive_present") for d in decisions]),
        "reflection_directive_count_total": sum(int(d.get("reflection_directive_count", 0)) for d in decisions),
        "strategy_shift_directive_present_rate": _rate([d.get("strategy_shift_directive_present") for d in decisions]),
        "strategy_shift_directive_count_total": sum(int(d.get("strategy_shift_directive_count", 0)) for d in decisions),
        "micro_coupling_applied_rate": _rate([d.get("micro_coupling_applied") for d in decisions]),
        "micro_coupling_applied_count_total": sum(int(d.get("micro_coupling_applied_count", 0)) for d in decisions),
        "repeated_failure_detected_rate": _rate([d.get("repeated_failure_detected") for d in decisions]),
        "repeated_failure_detected_count_total": sum(int(d.get("repeated_failure_detected_count", 0)) for d in decisions),
        "fallback_count": sum(1 for r in bucket if r["fallback_provenance"] != "not_observed"),
        "real_signal_count": sum(1 for r in bucket if r["arm_on_real_signal"]),
    }


def _compare_aggregate(on_value: Any, off_value: Any, lower_is_better: bool) -> str:
    if not isinstance(on_value, (int, float)) or not isinstance(off_value, (int, float)):
        return "missing"
    if on_value == off_value:
        return "equal"
    if lower_is_better:
        return "on_better" if on_value < off_value else "on_worse"
    return "on_better" if on_value > off_value else "on_worse"


def compare_aggregates(aggregates: dict) -> dict:
    off = aggregates["by_arm"].get("ARM_OFF", {})
    on = aggregates["by_arm"].get("ARM_ON", {})
    primary_advantages = []
    primary_regressions = []
    secondary_advantages = []
    secondary_regressions = []
    missing = []

    primary_comparisons = [
        ("higher_recovery_success_rate", on.get("recovery_success_rate"), off.get("recovery_success_rate"), False),
        ("better_certification_verdict", on.get("certification_rank_mean"), off.get("certification_rank_mean"), False),
        ("higher_final_score", on.get("final_score_mean"), off.get("final_score_mean"), False),
        ("higher_benchmark_score", on.get("benchmark_score_mean"), off.get("benchmark_score_mean"), False),
        ("fewer_retries", on.get("retries_count_mean"), off.get("retries_count_mean"), True),
        ("lower_loop_risk_proxy", on.get("loop_risk_proxy_mean"), off.get("loop_risk_proxy_mean"), True),
        ("lower_repeated_strategy_count", on.get("repeated_strategy_count_mean"), off.get("repeated_strategy_count_mean"), True),
    ]
    for label, on_value, off_value, lower_is_better in primary_comparisons:
        result = _compare_aggregate(on_value, off_value, lower_is_better)
        if result == "on_better":
            primary_advantages.append(label)
        elif result == "on_worse":
            primary_regressions.append(label)
        elif result == "missing":
            missing.append(label)

    secondary_comparisons = [
        ("less_severe_mood_min", on.get("mood_min_mean"), off.get("mood_min_mean"), False),
        ("better_mood_recovery_delta", on.get("mood_recovery_delta_mean"), off.get("mood_recovery_delta_mean"), False),
        ("higher_strategy_shift_rate", on.get("strategy_shift_rate"), off.get("strategy_shift_rate"), False),
        ("higher_reflection_directive_rate", on.get("reflection_directive_present_rate"), off.get("reflection_directive_present_rate"), False),
        ("higher_micro_coupling_applied_rate", on.get("micro_coupling_applied_rate"), off.get("micro_coupling_applied_rate"), False),
    ]
    for label, on_value, off_value, lower_is_better in secondary_comparisons:
        result = _compare_aggregate(on_value, off_value, lower_is_better)
        if result == "on_better":
            secondary_advantages.append(label)
        elif result == "on_worse":
            secondary_regressions.append(label)
        elif result == "missing":
            missing.append(label)

    sequence_primary_positive = 0
    sequence_secondary_positive = 0
    for seq, arms in aggregates["by_sequence"].items():
        seq_off = arms.get("ARM_OFF", {})
        seq_on = arms.get("ARM_ON", {})
        seq_primary = 0
        seq_secondary = 0
        for label, on_key, off_key, lower in [
            ("final", "final_score_mean", "final_score_mean", False),
            ("retry", "retries_count_mean", "retries_count_mean", True),
            ("loop", "loop_risk_proxy_mean", "loop_risk_proxy_mean", True),
            ("repeat", "repeated_strategy_count_mean", "repeated_strategy_count_mean", True),
            ("cert", "certification_rank_mean", "certification_rank_mean", False),
        ]:
            del label
            if _compare_aggregate(seq_on.get(on_key), seq_off.get(off_key), lower) == "on_better":
                seq_primary += 1
        for label, on_key, off_key, lower in [
            ("mood_min", "mood_min_mean", "mood_min_mean", False),
            ("mood_recovery", "mood_recovery_delta_mean", "mood_recovery_delta_mean", False),
        ]:
            del label
            if _compare_aggregate(seq_on.get(on_key), seq_off.get(off_key), lower) == "on_better":
                seq_secondary += 1
        if seq_primary > 0:
            sequence_primary_positive += 1
        if seq_secondary > 0:
            sequence_secondary_positive += 1

    return {
        "primary_advantages": primary_advantages,
        "primary_regressions": primary_regressions,
        "secondary_advantages": secondary_advantages,
        "secondary_regressions": secondary_regressions,
        "missing": sorted(set(missing)),
        "sequence_primary_positive_count": sequence_primary_positive,
        "sequence_secondary_positive_count": sequence_secondary_positive,
    }


def harness_sanity(summary: dict, records: list[dict]) -> dict:
    manifests = summary.get("manifests", [])
    expected = int(summary.get("expected_subprocesses", 0))
    cache_by_topic: dict[str, set[str]] = {}
    for manifest in manifests:
        for topic, cache_hash in manifest.get("cache_hashes", {}).items():
            cache_by_topic.setdefault(topic, set()).add(cache_hash)
    cache_hash_stable = all(len(values) == 1 for values in cache_by_topic.values())

    return {
        "expected_subprocess_count": len(manifests) == expected,
        "all_exit_zero": all(m.get("subprocess_exit_code") == 0 for m in manifests),
        "zero_live_calls": all(
            m.get("ddgs_call_count", 0) == 0
            and m.get("brave_call_count", 0) == 0
            and m.get("playwright_call_count", 0) == 0
            for m in manifests
        ),
        "cache_hits_ok": all(m.get("cache_hit_map", 0) >= 2 and m.get("cache_hit_aggregate", 0) >= 2 for m in manifests),
        "cache_hash_stable": cache_hash_stable,
        "no_contamination_flag": all(not m.get("contaminated", False) for m in manifests),
        "stress_observed_all": all(m.get("stress_injection_observed", False) for m in manifests),
        "sequence_observed_all": all(m.get("force_topic_seq_observed", False) for m in manifests),
        "mood_samples_present": all(r["mood"].get("n", 0) > 0 for r in records),
        "fallback_threshold_ok": all(m.get("fallback_count", 0) <= 10 for m in manifests),
        "abort_reason_absent": all(not m.get("abort_reason") for m in manifests),
    }


def classify_verdict(records: list[dict], aggregates: dict, comparison: dict, sanity: dict) -> tuple[str, str]:
    if not all(sanity.values()):
        return "CONTAMINATED", "Harness sanity failed before behavioral interpretation."

    arm_on = [r for r in records if r["manifest"].get("arm") == "ARM_ON"]
    arm_off = [r for r in records if r["manifest"].get("arm") == "ARM_OFF"]
    if not arm_on or not arm_off:
        return "INCONCLUSIVE", "Missing ARM_ON or ARM_OFF records."

    off_unclassified_bias = [
        r for r in arm_off
        if r["mood"].get("workspace_bias_present") is True and r["fallback_provenance"] == "not_observed"
    ]
    if off_unclassified_bias:
        return "CONTAMINATED", "ARM_OFF workspace bias could not be classified as fallback provenance."

    arm_on_signal_count = sum(1 for r in arm_on if r["arm_on_real_signal"])
    arm_on_signal_present = arm_on_signal_count > 0
    signal_provenance_clear = arm_on_signal_count == len(arm_on)
    arm_on_micro_count = sum(1 for r in arm_on if r["decision_coupling"].get("micro_coupling_applied") is True)
    arm_on_micro_present = arm_on_micro_count > 0

    missing_pressure = len(comparison["missing"]) >= 4
    observer_missing = any(not r["behavior"].get("observer_section_found") for r in records)
    if observer_missing or missing_pressure:
        return "INCONCLUSIVE", "Metrics are too sparse or observer-cycle extraction is fragile."

    if not arm_on_signal_present:
        return "INCONCLUSIVE", "Harness clean, but ARM_ON real workspace signal was not observed."
    if not arm_on_micro_present:
        return "FAIL", "ARM_ON signal is present, but the D2.2D reflection micro-coupling was not applied."

    primary_adv = comparison["primary_advantages"]
    primary_reg = comparison["primary_regressions"]
    secondary_adv = comparison["secondary_advantages"]
    sequence_primary_positive = comparison["sequence_primary_positive_count"]
    sequence_secondary_positive = comparison["sequence_secondary_positive_count"]

    if (
        len(primary_adv) >= 2
        and len(primary_reg) == 0
        and sequence_primary_positive >= 2
        and signal_provenance_clear
    ):
        return (
            "PASS_STRONG",
            "ARM_ON improves at least two aggregate primary metrics, has clear signal provenance, and applies the reflection micro-coupling.",
        )
    decision_metric_moved = (
        "higher_reflection_directive_rate" in secondary_adv
        or "higher_micro_coupling_applied_rate" in secondary_adv
        or "higher_strategy_shift_rate" in secondary_adv
        or "lower_repeated_strategy_count" in primary_adv
    )
    if len(primary_adv) >= 1 or decision_metric_moved:
        return (
            "PASS_WEAK",
            "ARM_ON applies the reflection micro-coupling and shows decision-adjacent metric movement, but not enough outcome-level improvement for a strong claim.",
        )
    return (
        "FAIL",
        "ARM_ON signal and micro-coupling are present, but no decision or aggregate behavioral metric improves versus ARM_OFF.",
    )


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def render(run_root: Path, summary: dict) -> tuple[str, str, dict]:
    records = build_records(run_root, summary)
    aggregates = aggregate_records(records)
    comparison = compare_aggregates(aggregates)
    sanity = harness_sanity(summary, records)
    verdict, reason = classify_verdict(records, aggregates, comparison, sanity)

    lines = []
    lines.append("# D2.2D Micro Decision Coupling Report\n")
    lines.append(f"Planning commit: `{summary.get('planning_commit')}`")
    lines.append(f"Run root: `{run_root.relative_to(_ROOT).as_posix()}`")
    lines.append(f"Expected subprocesses: `{summary.get('expected_subprocesses')}`")
    lines.append(f"Actual subprocesses: `{summary.get('actual_subprocesses')}`")
    lines.append(f"Aborted: `{summary.get('aborted', False)}`\n")

    lines.append("## Experimental Question\n")
    lines.append("If calibrated GWT/Mood signal is connected as a minimal reflection directive, does ARM_ON show measurable differences in strategy shift, repeated strategy, retry quality, recovery, or loop-risk?\n")

    lines.append("## Micro-Fix Applied\n")
    lines.append("- Target gate: `reflection_trigger` / retry reflection prompt path.")
    lines.append("- Modified path: `backend/study_phases.py::_retry_gap_fill`.")
    lines.append("- Mechanism: when L3 is active, the dominant workspace winner is `tensions`, mood is stressed, and repeated failure is detected, inject a reflection/strategy-shift directive into the next retry prompt.")
    lines.append("- The directive is a modifier, not an override.\n")

    lines.append("Behavior/scoring guardrails:")
    lines.append("- `MAX_RETRY` unchanged.")
    lines.append("- Certification threshold unchanged.")
    lines.append("- Scoring logic unchanged.")
    lines.append("- `_WINNER_BIAS` unchanged in D2.2D.")
    lines.append("- `ValenceField` unchanged.")
    lines.append("- Stress injection unchanged.")
    lines.append("- Topic sequence and topic handling unchanged.\n")

    lines.append("## Protocol\n")
    lines.append("- Same cached-source harness lineage as D2.1A/D2.1E.")
    lines.append("- Zero live DDGS/Brave/Playwright calls expected during benchmark subprocesses.")
    lines.append("- Subprocess isolation.")
    lines.append("- ARM_OFF vs ARM_ON.")
    lines.append("- Controlled stress injection.")
    lines.append("- 2 topic sequences x 2 replicas x 2 arms = 8 subprocesses.")
    lines.append("- D2.2D micro decision coupling only, not D2.2 full.\n")

    lines.append("Topic sequences:")
    for seq in summary.get("topic_sequences", []):
        lines.append(f"- `{seq['id']}`: `{seq['stress_topic']}` -> `{seq['observer_topic']}`")
    lines.append("")

    lines.append(f"**Final verdict: `{verdict}`**\n")
    lines.append(f"> {reason}\n")

    lines.append("## Harness Sanity\n")
    lines.append("| Check | Result |")
    lines.append("|---|---|")
    for key, ok in sanity.items():
        lines.append(f"| `{key}` | {'PASS' if ok else 'FAIL'} |")
    lines.append("")

    lines.append("## Raw Traces Aggregate\n")
    lines.append("| sequence | rep | arm | mood_traj | wb_traj | observer_mood | observer_wb | tensions_trace_count | fallback_provenance |")
    lines.append("|---|---:|---|---|---|---|---|---:|---|")
    for record in records:
        manifest = record["manifest"]
        mood = record["mood"]
        signal = record["signal"]
        lines.append(
            f"| `{manifest['sequence_id']}` | {manifest['rep']} | `{manifest['arm']}` "
            f"| `{mood.get('mood_traj', [])}` | `{mood.get('wb_traj', [])}` "
            f"| `{mood.get('observer_mood_traj', [])}` | `{mood.get('observer_wb_traj', [])}` "
            f"| {signal.get('tensions_trace_count', 0)} | `{record['fallback_provenance']}` |"
        )
    lines.append("")

    lines.append("## Per Run Behavioral Metrics\n")
    lines.append("| sequence | rep | arm | recovery_success | retries_count | strategy_shift_detected | certification_verdict | final_score | benchmark_score | repeated_strategy_count | loop_risk_proxy | mood_min | mood_recovery_delta | workspace_bias_present | micro_coupling_applied | reflection_directive_present |")
    lines.append("|---|---:|---|---|---:|---|---|---:|---|---:|---|---:|---:|---|---|---|")
    for record in records:
        manifest = record["manifest"]
        behavior = record["behavior"]
        mood = record["mood"]
        decision = record["decision_coupling"]
        lines.append(
            f"| `{manifest['sequence_id']}` | {manifest['rep']} | `{manifest['arm']}` "
            f"| `{behavior.get('recovery_success', MISSING)}` "
            f"| `{behavior.get('retries_count', MISSING)}` "
            f"| `{behavior.get('strategy_shift_detected', MISSING)}` "
            f"| `{behavior.get('certification_verdict', MISSING)}` "
            f"| `{behavior.get('final_score', MISSING)}` "
            f"| `{behavior.get('benchmark_score', MISSING)}` "
            f"| `{behavior.get('repeated_strategy_count', MISSING)}` "
            f"| `{behavior.get('loop_risk_proxy', MISSING)}` "
            f"| `{mood.get('mood_min', MISSING)}` "
            f"| `{mood.get('mood_recovery_delta', MISSING)}` "
            f"| `{mood.get('workspace_bias_present', MISSING)}` "
            f"| `{decision.get('micro_coupling_applied', MISSING)}` "
            f"| `{decision.get('reflection_directive_present', MISSING)}` |"
        )
    lines.append("")

    lines.append("## Aggregate ARM_OFF vs ARM_ON\n")
    aggregate_keys = [
        "n",
        "recovery_success_rate",
        "certification_rank_mean",
        "final_score_mean",
        "benchmark_score_mean",
        "retries_count_mean",
        "loop_risk_proxy_mean",
        "repeated_strategy_count_mean",
        "strategy_shift_rate",
        "mood_min_mean",
        "mood_recovery_delta_mean",
        "workspace_bias_present_rate",
        "tensions_trace_count_total",
        "reflection_trigger_count_total",
        "reflection_directive_present_rate",
        "reflection_directive_count_total",
        "strategy_shift_directive_present_rate",
        "micro_coupling_applied_rate",
        "micro_coupling_applied_count_total",
        "repeated_failure_detected_rate",
        "fallback_count",
        "real_signal_count",
    ]
    lines.append("| metric | ARM_OFF | ARM_ON |")
    lines.append("|---|---:|---:|")
    for key in aggregate_keys:
        off_value = aggregates["by_arm"].get("ARM_OFF", {}).get(key, MISSING)
        on_value = aggregates["by_arm"].get("ARM_ON", {}).get(key, MISSING)
        lines.append(f"| `{key}` | `{_format_value(off_value)}` | `{_format_value(on_value)}` |")
    lines.append("")

    lines.append("## Aggregate By Sequence\n")
    lines.append("| sequence | arm | final_score_mean | retries_count_mean | loop_risk_proxy_mean | mood_min_mean | mood_recovery_delta_mean | real_signal_count |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for seq, arms in aggregates["by_sequence"].items():
        for arm in ("ARM_OFF", "ARM_ON"):
            bucket = arms.get(arm, {})
            lines.append(
                f"| `{seq}` | `{arm}` | `{_format_value(bucket.get('final_score_mean', MISSING))}` "
                f"| `{_format_value(bucket.get('retries_count_mean', MISSING))}` "
                f"| `{_format_value(bucket.get('loop_risk_proxy_mean', MISSING))}` "
                f"| `{_format_value(bucket.get('mood_min_mean', MISSING))}` "
                f"| `{_format_value(bucket.get('mood_recovery_delta_mean', MISSING))}` "
                f"| `{_format_value(bucket.get('real_signal_count', MISSING))}` |"
            )
    lines.append("")

    lines.append("## Missing / Unavailable Metrics\n")
    lines.append(f"- Primary metrics: {PRIMARY_METRICS}")
    lines.append(f"- Secondary metrics: {SECONDARY_METRICS}")
    lines.append(f"- Missing/limited comparisons: `{comparison['missing']}`")
    if aggregates["by_arm"].get("ARM_ON", {}).get("benchmark_score_mean") == UNAVAILABLE:
        lines.append("- `benchmark_score` is `UNAVAILABLE` in aggregate because no reliable benchmark score was parsed.")
    lines.append("")

    lines.append("## Behavioral Comparison\n")
    lines.append(f"- Primary advantages: `{comparison['primary_advantages']}`")
    lines.append(f"- Primary regressions: `{comparison['primary_regressions']}`")
    lines.append(f"- Secondary advantages: `{comparison['secondary_advantages']}`")
    lines.append(f"- Secondary regressions: `{comparison['secondary_regressions']}`")
    lines.append(f"- Sequence primary-positive count: `{comparison['sequence_primary_positive_count']}`")
    lines.append(f"- Sequence secondary-positive count: `{comparison['sequence_secondary_positive_count']}`")
    lines.append("- ARM_OFF fallback bias is excluded from GWT signal when classified as synthetic ignition-failure fallback.")
    lines.append("- ARM_ON workspace_bias is interpreted as signal/provenance, not as performance.\n")

    lines.append("## Risk / Limitation\n")
    lines.append("- N is still small: 2 sequences x 2 reps.")
    lines.append("- LLM stochasticity can dominate small aggregate differences.")
    lines.append("- Several metrics remain log-derived proxies.")
    lines.append("- Stress injection is controlled but artificial.")
    lines.append("- Certification/final score may be too coarse for subtle strategy changes.")
    lines.append("- D2.2D is not D2.2 full and cannot support a general performance claim.\n")

    lines.append("## Disciplined Claim Boundary\n")
    lines.append("Allowed if supported:")
    lines.append("")
    lines.append("```text")
    lines.append("Under a controlled micro-coupling protocol, calibrated GWT/Mood signal influences a specific decision-adjacent behavior such as reflection or strategy-shift prompting.")
    lines.append("```")
    lines.append("")
    lines.append("Forbidden:")
    lines.append("")
    lines.append("```text")
    lines.append("GWT improves SHARD performance.")
    lines.append("```")

    details = {
        "records": records,
        "aggregates": aggregates,
        "comparison": comparison,
        "sanity": sanity,
    }
    return "\n".join(lines), verdict, details


def main() -> None:
    if len(sys.argv) > 1:
        run_root = Path(sys.argv[1]).resolve()
    else:
        run_root = _latest_run_root()
        if run_root is None:
            print(f"[d2_2d_analyze] no runs found under {RUNS_ROOT}")
            sys.exit(2)
    if not run_root.exists():
        print(f"[d2_2d_analyze] run root not found: {run_root}")
        sys.exit(2)

    summary = load_summary(run_root)
    markdown, verdict, _details = render(run_root, summary)
    run_report = run_root / "d2_2d_report.md"
    run_report.write_text(markdown, encoding="utf-8")
    DOC_REPORT.write_text(markdown, encoding="utf-8")
    print(markdown)
    print()
    print(f"[d2_2d_analyze] Run report -> {run_report}")
    print(f"[d2_2d_analyze] Docs report -> {DOC_REPORT}")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
