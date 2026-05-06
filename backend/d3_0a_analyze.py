"""d3_0a_analyze.py -- analyzer for D3.0A learning curve probe."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d3_0a_runs"
DOC_REPORT = _ROOT / "docs" / "experiments" / "d3_0a_learning_curve_probe.md"

MISSING = "MISSING"
UNAVAILABLE = "UNAVAILABLE"


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    candidates = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def _load_summary(run_root: Path) -> dict[str, Any]:
    path = run_root / "d3_0a_summary.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _mean(values: list[Any]) -> float | str:
    nums = [_num(v) for v in values]
    nums = [v for v in nums if v is not None]
    return round(statistics.mean(nums), 4) if nums else UNAVAILABLE


def _slope(values: list[Any]) -> float | str:
    nums = [_num(v) for v in values]
    nums = [v for v in nums if v is not None]
    if len(nums) < 2:
        return UNAVAILABLE
    xs = list(range(1, len(nums) + 1))
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(nums)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return UNAVAILABLE
    value = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, nums)) / denom
    return round(value, 4)


def _rate(values: list[Any]) -> float | str:
    bools = [v for v in values if isinstance(v, bool)]
    if not bools:
        return UNAVAILABLE
    return round(sum(1 for v in bools if v) / len(bools), 4)


def _group_by_arm(manifests: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for manifest in sorted(manifests, key=lambda m: (m["arm"], int(m["session_index"]))):
        grouped.setdefault(manifest["arm"], []).append(manifest)
    return grouped


def _metric(manifest: dict[str, Any], namespace: str, key: str) -> Any:
    return manifest.get(namespace, {}).get(key, MISSING)


def _arm_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    final_scores = [_metric(m, "behavior_metrics", "final_score") for m in rows]
    cert_ranks = [_metric(m, "behavior_metrics", "certification_rank") for m in rows]
    recovery = [_metric(m, "behavior_metrics", "recovery_success") for m in rows]
    retries = [_metric(m, "behavior_metrics", "retries_count") for m in rows]
    loop_risk = [_metric(m, "behavior_metrics", "loop_risk_proxy") for m in rows]
    repeated = [_metric(m, "behavior_metrics", "repeated_strategy_count") for m in rows]
    mood_min = [_metric(m, "mood_metrics", "mood_min") for m in rows]
    memory_recall = [_metric(m, "memory_strategy_metrics", "memory_recall_count") for m in rows]
    strategy_update = [_metric(m, "memory_strategy_metrics", "strategy_update_count") for m in rows]
    strategy_reuse = [_metric(m, "memory_strategy_metrics", "strategy_reuse_count") for m in rows]
    failure_attr = [_metric(m, "memory_strategy_metrics", "failure_attribution_present") for m in rows]

    return {
        "session_count": len(rows),
        "final_score_values": final_scores,
        "final_score_mean": _mean(final_scores),
        "final_score_slope": _slope(final_scores),
        "certification_rank_values": cert_ranks,
        "certification_rank_mean": _mean(cert_ranks),
        "certification_rank_slope": _slope(cert_ranks),
        "recovery_success_rate": _rate(recovery),
        "recovery_success_slope": _slope(recovery),
        "retries_count_values": retries,
        "retries_count_mean": _mean(retries),
        "retries_count_slope": _slope(retries),
        "loop_risk_proxy_values": loop_risk,
        "loop_risk_proxy_mean": _mean(loop_risk),
        "loop_risk_proxy_slope": _slope(loop_risk),
        "repeated_strategy_count_values": repeated,
        "repeated_strategy_count_mean": _mean(repeated),
        "repeated_strategy_count_slope": _slope(repeated),
        "mood_min_values": mood_min,
        "mood_min_mean": _mean(mood_min),
        "mood_min_slope": _slope(mood_min),
        "memory_recall_count_values": memory_recall,
        "memory_recall_count_mean": _mean(memory_recall),
        "memory_recall_count_slope": _slope(memory_recall),
        "strategy_update_count_values": strategy_update,
        "strategy_update_count_mean": _mean(strategy_update),
        "strategy_update_count_slope": _slope(strategy_update),
        "strategy_reuse_count_values": strategy_reuse,
        "strategy_reuse_count_mean": _mean(strategy_reuse),
        "strategy_reuse_count_slope": _slope(strategy_reuse),
        "failure_attribution_rate": _rate(failure_attr),
        "workspace_bias_present_rate": _rate([
            _metric(m, "mood_metrics", "workspace_bias_present") for m in rows
        ]),
        "benchmark_score_status": sorted(set(
            str(_metric(m, "behavior_metrics", "benchmark_score_status")) for m in rows
        )),
        "memory_metric_source": sorted(set(
            str(_metric(m, "memory_strategy_metrics", "memory_recall_source")) for m in rows
        )),
    }


def _slope_diff(on: Any, off: Any) -> float | None:
    if isinstance(on, (int, float)) and isinstance(off, (int, float)):
        return round(float(on) - float(off), 4)
    return None


def _compare(aggregates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    off = aggregates.get("ARM_OFF", {})
    on = aggregates.get("ARM_ON", {})
    return {
        "final_score_slope_delta": _slope_diff(on.get("final_score_slope"), off.get("final_score_slope")),
        "certification_rank_slope_delta": _slope_diff(on.get("certification_rank_slope"), off.get("certification_rank_slope")),
        "recovery_success_slope_delta": _slope_diff(on.get("recovery_success_slope"), off.get("recovery_success_slope")),
        "retries_count_slope_delta_lower_is_better": _slope_diff(off.get("retries_count_slope"), on.get("retries_count_slope")),
        "loop_risk_proxy_slope_delta_lower_is_better": _slope_diff(off.get("loop_risk_proxy_slope"), on.get("loop_risk_proxy_slope")),
        "repeated_strategy_slope_delta_lower_is_better": _slope_diff(off.get("repeated_strategy_count_slope"), on.get("repeated_strategy_count_slope")),
        "mood_min_slope_delta": _slope_diff(on.get("mood_min_slope"), off.get("mood_min_slope")),
        "memory_recall_slope_delta": _slope_diff(on.get("memory_recall_count_slope"), off.get("memory_recall_count_slope")),
        "strategy_update_slope_delta": _slope_diff(on.get("strategy_update_count_slope"), off.get("strategy_update_count_slope")),
        "strategy_reuse_slope_delta": _slope_diff(on.get("strategy_reuse_count_slope"), off.get("strategy_reuse_count_slope")),
    }


def _positive(value: Any, threshold: float = 0.001) -> bool:
    return isinstance(value, (int, float)) and float(value) > threshold


def _negative(value: Any, threshold: float = -0.25) -> bool:
    return isinstance(value, (int, float)) and float(value) < threshold


def _verdict(summary: dict[str, Any], aggregates: dict[str, dict[str, Any]], comparison: dict[str, Any]) -> tuple[str, list[str]]:
    manifests = summary["manifests"]
    if any(m.get("contaminated") for m in manifests):
        return "CONTAMINATED", ["live provider or contamination marker observed"]
    if any(m.get("abort_reason") for m in manifests):
        return "CONTAMINATED", ["one or more sessions failed harness sanity"]
    if summary.get("actual_sessions") != summary.get("expected_sessions"):
        return "CONTAMINATED", ["expected session count not completed"]

    off = aggregates.get("ARM_OFF", {})
    on = aggregates.get("ARM_ON", {})
    if off.get("session_count") != 5 or on.get("session_count") != 5:
        return "INCONCLUSIVE", ["session boundaries incomplete"]

    primary_wins = []
    for key in (
        "final_score_slope_delta",
        "certification_rank_slope_delta",
        "recovery_success_slope_delta",
        "retries_count_slope_delta_lower_is_better",
        "loop_risk_proxy_slope_delta_lower_is_better",
        "repeated_strategy_slope_delta_lower_is_better",
        "memory_recall_slope_delta",
        "strategy_update_slope_delta",
    ):
        if _positive(comparison.get(key)):
            primary_wins.append(key)

    secondary_wins = []
    for key in ("mood_min_slope_delta", "strategy_reuse_slope_delta"):
        if _positive(comparison.get(key)):
            secondary_wins.append(key)

    severe_regression = (
        _negative(comparison.get("final_score_slope_delta"), threshold=-0.1)
        or _negative(comparison.get("certification_rank_slope_delta"), threshold=-0.1)
    )
    memory_strategy_support = (
        _positive(comparison.get("memory_recall_slope_delta"))
        or _positive(comparison.get("strategy_update_slope_delta"))
        or _positive(comparison.get("strategy_reuse_slope_delta"))
    )

    if len(primary_wins) >= 2 and not severe_regression and memory_strategy_support:
        return "PASS_STRONG", primary_wins
    if primary_wins or secondary_wins:
        reasons = primary_wins + secondary_wins
        if severe_regression:
            reasons.append("hard outcome slope regression prevents PASS_STRONG")
        if not memory_strategy_support:
            reasons.append("memory/strategy evidence does not support PASS_STRONG")
        return "PASS_WEAK", reasons
    return "FAIL", ["no ARM_ON learning-curve slope advantage detected"]


def _session_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Arm | Session | Topic | Final score | Cert | Recovery | Retries | Loop risk | Memory recall | Strategy updates | Mood min | Workspace bias |",
        "| --- | ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for m in sorted(rows, key=lambda x: (x["arm"], int(x["session_index"]))):
        b = m["behavior_metrics"]
        mem = m["memory_strategy_metrics"]
        mood = m["mood_metrics"]
        lines.append(
            f"| {m['arm']} | {m['session_index']} | {m['topic']} | "
            f"{b.get('final_score')} | {b.get('certification_verdict')} | "
            f"{b.get('recovery_success')} | {b.get('retries_count')} | "
            f"{b.get('loop_risk_proxy')} | {mem.get('memory_recall_count')} | "
            f"{mem.get('strategy_update_count')} | {mood.get('mood_min')} | "
            f"{mood.get('workspace_bias_present')} |"
        )
    return "\n".join(lines)


def _aggregate_table(aggregates: dict[str, dict[str, Any]]) -> str:
    keys = [
        "final_score_slope",
        "certification_rank_slope",
        "recovery_success_slope",
        "retries_count_slope",
        "loop_risk_proxy_slope",
        "repeated_strategy_count_slope",
        "mood_min_slope",
        "memory_recall_count_slope",
        "strategy_update_count_slope",
        "strategy_reuse_count_slope",
    ]
    lines = ["| Metric | ARM_OFF | ARM_ON |", "| --- | ---: | ---: |"]
    for key in keys:
        lines.append(f"| {key} | {aggregates.get('ARM_OFF', {}).get(key)} | {aggregates.get('ARM_ON', {}).get(key)} |")
    return "\n".join(lines)


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _write_report(run_root: Path, summary: dict[str, Any], aggregates: dict[str, dict[str, Any]], comparison: dict[str, Any], verdict: str, reasons: list[str]) -> None:
    DOC_REPORT.parent.mkdir(parents=True, exist_ok=True)
    manifests = summary["manifests"]
    missing = ["benchmark_score", "memory_recall_relevance"]
    text = f"""# D3.0A Learning Curve Probe

## Status

Run analyzed.

Planning commit: `{summary['planning_commit']}`

Cache prefetch note: `{summary.get('prefetch_report')}`

Run directory: `{run_root.relative_to(_ROOT).as_posix()}`

## Experimental Question

Does calibrated GWT/Mood coupling improve SHARD's learning curve across repeated sessions, rather than immediate single-run performance?

## Protocol

- Topic family: {summary['topic_family']}
- Arms: ARM_OFF vs ARM_ON
- Sessions per arm: 5
- Memory/strategy persistence: enabled within each arm
- Arm isolation: `{summary['memory_isolation']['method']}`
- Source mode: cached sources only

## Harness Sanity

- Expected sessions: {summary['expected_sessions']}
- Actual sessions: {summary['actual_sessions']}
- Contaminated sessions: {sum(1 for m in manifests if m.get('contaminated'))}
- Abort reasons: {[m.get('abort_reason') for m in manifests if m.get('abort_reason')]}
- Live DDGS/Brave/Playwright during benchmark: {sum(m.get('ddgs_call_count', 0) + m.get('brave_call_count', 0) + m.get('playwright_call_count', 0) for m in manifests)}
- Arm leakage control: baseline `shard_memory` snapshot restored before each arm; original memory restored after the run.

## Session Metrics

{_session_table(manifests)}

## Aggregate Slopes

{_aggregate_table(aggregates)}

## Slope Comparison

```json
{json.dumps(comparison, indent=2)}
```

## Memory / Strategy Evidence

- Memory metrics source: log-derived proxy unless structured fields become available.
- ARM_OFF memory_recall_count slope: {aggregates.get('ARM_OFF', {}).get('memory_recall_count_slope')}
- ARM_ON memory_recall_count slope: {aggregates.get('ARM_ON', {}).get('memory_recall_count_slope')}
- ARM_OFF strategy_update_count slope: {aggregates.get('ARM_OFF', {}).get('strategy_update_count_slope')}
- ARM_ON strategy_update_count slope: {aggregates.get('ARM_ON', {}).get('strategy_update_count_slope')}

## Missing / Unavailable Metrics

{_bullet_list(missing)}

## Verdict

{verdict}

Reasons:

{_bullet_list(reasons)}

## Interpretation

D3.0A tests longitudinal learning behavior, not a single-run performance claim. Any positive result should be interpreted as learning-curve evidence under this controlled probe, not as a general claim that GWT improves SHARD performance.

## Limitations

- D3.0A is more realistic than D2 micro protocols but less causally isolated.
- Memory/strategy metrics are still partly log-derived.
- Filesystem snapshot/restore reduces arm leakage risk but is not a native memory namespace.
- `benchmark_score` remains unavailable unless emitted by the core pipeline.

## Forbidden Claim

GWT improves SHARD performance.

## Next Step

If D3.0A is promising, harden memory/strategy instrumentation before a larger D3 learning-curve validation.
"""
    DOC_REPORT.write_text(text, encoding="utf-8")


def main() -> None:
    run_root = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_run_root()
    if run_root is None:
        raise SystemExit("No D3.0A run directory found.")
    run_root = run_root.resolve()
    summary = _load_summary(run_root)
    grouped = _group_by_arm(summary["manifests"])
    aggregates = {arm: _arm_metrics(rows) for arm, rows in grouped.items()}
    comparison = _compare(aggregates)
    verdict, reasons = _verdict(summary, aggregates, comparison)
    result = {
        "run_root": str(run_root),
        "verdict": verdict,
        "reasons": reasons,
        "aggregates": aggregates,
        "comparison": comparison,
    }
    result_path = run_root / "d3_0a_analysis.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    _write_report(run_root, summary, aggregates, comparison, verdict, reasons)

    print("=" * 70)
    print(f"D3.0A VERDICT: {verdict}")
    print(f"Reasons: {reasons}")
    print(f"Analysis: {result_path}")
    print(f"Report:   {DOC_REPORT}")
    print("=" * 70)


if __name__ == "__main__":
    main()
