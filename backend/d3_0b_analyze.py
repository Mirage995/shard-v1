"""d3_0b_analyze.py -- analyzer for D3.0B memory/strategy diagnostic."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d3_0b_runs"
DOC_REPORT = _ROOT / "docs" / "experiments" / "d3_0b_memory_strategy_instrumentation.md"
MISSING = "MISSING"
UNAVAILABLE = "UNAVAILABLE"


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    candidates = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def _load_summary(run_root: Path) -> dict[str, Any]:
    path = run_root / "d3_0b_summary.json"
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


def _rate(values: list[Any]) -> float | str:
    bools = [v for v in values if isinstance(v, bool)]
    return round(sum(1 for v in bools if v) / len(bools), 4) if bools else UNAVAILABLE


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
    return round(sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, nums)) / denom, 4)


def _metric(manifest: dict[str, Any], namespace: str, key: str) -> Any:
    return manifest.get(namespace, {}).get(key, MISSING)


def _group_by_arm(manifests: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for manifest in sorted(manifests, key=lambda m: (m["arm"], int(m["session_index"]))):
        grouped.setdefault(manifest["arm"], []).append(manifest)
    return grouped


def _arm_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    final_scores = [_metric(m, "behavior_metrics", "final_score") for m in rows]
    cert_ranks = [_metric(m, "behavior_metrics", "certification_rank") for m in rows]
    recovery = [_metric(m, "behavior_metrics", "recovery_success") for m in rows]
    retries = [_metric(m, "behavior_metrics", "retries_count") for m in rows]
    loop_risk = [_metric(m, "behavior_metrics", "loop_risk_proxy") for m in rows]
    repeated = [_metric(m, "behavior_metrics", "repeated_strategy_count") for m in rows]
    memory_write = [_metric(m, "memory_metrics", "memory_write_count") for m in rows]
    memory_recall = [_metric(m, "memory_metrics", "memory_recall_count") for m in rows]
    failure_reused = [_metric(m, "memory_metrics", "failure_memory_reused") for m in rows]
    prior_failure = [_metric(m, "memory_metrics", "prior_failure_referenced") for m in rows]
    strategy_update = [_metric(m, "strategy_metrics", "strategy_update_count") for m in rows]
    strategy_reuse = [_metric(m, "strategy_metrics", "strategy_reuse_count") for m in rows]
    strategy_read = [_metric(m, "strategy_metrics", "strategy_read_count") for m in rows]
    learning_events = [_metric(m, "strategy_metrics", "session_to_session_learning_event") for m in rows]
    mood_min = [_metric(m, "mood_metrics", "mood_min") for m in rows]
    wb_present = [_metric(m, "mood_metrics", "workspace_bias_present") for m in rows]
    return {
        "session_count": len(rows),
        "final_score_values": final_scores,
        "final_score_mean": _mean(final_scores),
        "final_score_slope": _slope(final_scores),
        "certification_rank_mean": _mean(cert_ranks),
        "certification_rank_slope": _slope(cert_ranks),
        "recovery_success_rate": _rate(recovery),
        "recovery_success_slope": _slope(recovery),
        "retries_count_mean": _mean(retries),
        "retries_count_slope": _slope(retries),
        "loop_risk_proxy_values": loop_risk,
        "loop_risk_proxy_mean": _mean(loop_risk),
        "loop_risk_proxy_slope": _slope(loop_risk),
        "repeated_strategy_count_values": repeated,
        "repeated_strategy_count_mean": _mean(repeated),
        "repeated_strategy_count_slope": _slope(repeated),
        "memory_write_count_values": memory_write,
        "memory_write_count_mean": _mean(memory_write),
        "memory_write_count_slope": _slope(memory_write),
        "memory_recall_count_values": memory_recall,
        "memory_recall_count_mean": _mean(memory_recall),
        "memory_recall_count_slope": _slope(memory_recall),
        "failure_memory_reuse_rate": _rate(failure_reused),
        "prior_failure_reference_rate": _rate(prior_failure),
        "strategy_read_count_values": strategy_read,
        "strategy_read_count_mean": _mean(strategy_read),
        "strategy_update_count_values": strategy_update,
        "strategy_update_count_mean": _mean(strategy_update),
        "strategy_update_count_slope": _slope(strategy_update),
        "strategy_reuse_count_values": strategy_reuse,
        "strategy_reuse_count_mean": _mean(strategy_reuse),
        "strategy_reuse_count_slope": _slope(strategy_reuse),
        "session_to_session_learning_event_rate": _rate(learning_events),
        "mood_min_mean": _mean(mood_min),
        "mood_min_slope": _slope(mood_min),
        "workspace_bias_present_rate": _rate(wb_present),
    }


def _delta(on: Any, off: Any) -> float | None:
    if isinstance(on, (int, float)) and isinstance(off, (int, float)):
        return round(float(on) - float(off), 4)
    return None


def _compare(aggregates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    off = aggregates.get("ARM_OFF", {})
    on = aggregates.get("ARM_ON", {})
    return {
        "final_score_slope_delta": _delta(on.get("final_score_slope"), off.get("final_score_slope")),
        "certification_rank_slope_delta": _delta(on.get("certification_rank_slope"), off.get("certification_rank_slope")),
        "memory_write_slope_delta": _delta(on.get("memory_write_count_slope"), off.get("memory_write_count_slope")),
        "memory_recall_slope_delta": _delta(on.get("memory_recall_count_slope"), off.get("memory_recall_count_slope")),
        "strategy_update_slope_delta": _delta(on.get("strategy_update_count_slope"), off.get("strategy_update_count_slope")),
        "strategy_reuse_slope_delta": _delta(on.get("strategy_reuse_count_slope"), off.get("strategy_reuse_count_slope")),
        "loop_risk_slope_delta_lower_is_better": _delta(off.get("loop_risk_proxy_slope"), on.get("loop_risk_proxy_slope")),
        "repeated_strategy_slope_delta_lower_is_better": _delta(off.get("repeated_strategy_count_slope"), on.get("repeated_strategy_count_slope")),
    }


def _positive(value: Any, threshold: float = 0.001) -> bool:
    return isinstance(value, (int, float)) and float(value) > threshold


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

    structured_events_visible = (
        _positive(off.get("memory_write_count_mean"), 0)
        or _positive(on.get("memory_write_count_mean"), 0)
        or _positive(off.get("strategy_read_count_mean"), 0)
        or _positive(on.get("strategy_read_count_mean"), 0)
        or _positive(off.get("strategy_update_count_mean"), 0)
        or _positive(on.get("strategy_update_count_mean"), 0)
    )
    arm_on_adaptation = (
        _positive(comparison.get("memory_recall_slope_delta"))
        or _positive(comparison.get("strategy_update_slope_delta"))
        or _positive(comparison.get("strategy_reuse_slope_delta"))
        or _positive(comparison.get("loop_risk_slope_delta_lower_is_better"))
        or _positive(comparison.get("repeated_strategy_slope_delta_lower_is_better"))
    )
    hard_not_worse = (
        comparison.get("final_score_slope_delta") is None
        or comparison.get("final_score_slope_delta") >= 0
        or comparison.get("certification_rank_slope_delta") == 0
    )
    if structured_events_visible and arm_on_adaptation and hard_not_worse:
        return "PASS_STRONG", ["structured events visible", "ARM_ON adaptation proxy present", "hard slope not worse by criterion"]
    if structured_events_visible:
        return "PASS_WEAK", ["structured memory/strategy events visible", "outcome slopes remain mixed or adaptation not ARM_ON-specific"]
    return "FAIL", ["no memory/strategy events observed despite persistence enabled"]


def _session_table(manifests: list[dict[str, Any]]) -> str:
    lines = [
        "| Arm | Session | Topic | Score | Cert | Recovery | Memory writes | Memory recall | Strategy reads | Strategy updates | Strategy reuse | Learning event |",
        "| --- | ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for m in sorted(manifests, key=lambda item: (item["arm"], int(item["session_index"]))):
        b = m["behavior_metrics"]
        mem = m["memory_metrics"]
        strat = m["strategy_metrics"]
        lines.append(
            f"| {m['arm']} | {m['session_index']} | {m['topic']} | {b.get('final_score')} | "
            f"{b.get('certification_verdict')} | {b.get('recovery_success')} | "
            f"{mem.get('memory_write_count')} | {mem.get('memory_recall_count')} | "
            f"{strat.get('strategy_read_count')} | {strat.get('strategy_update_count')} | "
            f"{strat.get('strategy_reuse_count')} | {strat.get('session_to_session_learning_event')} |"
        )
    return "\n".join(lines)


def _aggregate_table(aggregates: dict[str, dict[str, Any]]) -> str:
    keys = [
        "final_score_slope",
        "memory_write_count_slope",
        "memory_recall_count_slope",
        "strategy_update_count_slope",
        "strategy_reuse_count_slope",
        "loop_risk_proxy_slope",
        "repeated_strategy_count_slope",
        "session_to_session_learning_event_rate",
    ]
    lines = ["| Metric | ARM_OFF | ARM_ON |", "| --- | ---: | ---: |"]
    for key in keys:
        lines.append(f"| {key} | {aggregates.get('ARM_OFF', {}).get(key)} | {aggregates.get('ARM_ON', {}).get(key)} |")
    return "\n".join(lines)


def _instrumentation_map(summary: dict[str, Any]) -> str:
    lines = [
        "| Event type | File/function | Currently observable? | Structured field available? | Instrumentation added |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in summary.get("instrumentation_map", []):
        lines.append(
            f"| {row.get('event_type')} | `{row.get('file_function')}` | "
            f"{row.get('currently_observable')} | {row.get('structured_field_available')} | "
            f"{row.get('instrumentation_added')} |"
        )
    return "\n".join(lines)


def _write_report(run_root: Path, summary: dict[str, Any], aggregates: dict[str, dict[str, Any]], comparison: dict[str, Any], verdict: str, reasons: list[str]) -> None:
    DOC_REPORT.parent.mkdir(parents=True, exist_ok=True)
    manifests = summary["manifests"]
    text = f"""# D3.0B Memory/Strategy Instrumentation Diagnostic

## Status

Run analyzed.

Planning commit: `{summary['planning_commit']}`

Run directory: `{run_root.relative_to(_ROOT).as_posix()}`

## Protocol

- Arms: ARM_OFF vs ARM_ON
- Sessions per arm: 5
- Topic family: {summary['topic_family']}
- Source mode: cached sources only
- Memory/strategy persistence: enabled within each arm
- Arm isolation: `{summary['memory_isolation']['method']}`

## Harness Sanity

- Expected sessions: {summary['expected_sessions']}
- Actual sessions: {summary['actual_sessions']}
- Contaminated sessions: {sum(1 for m in manifests if m.get('contaminated'))}
- Abort reasons: {[m.get('abort_reason') for m in manifests if m.get('abort_reason')]}
- Live DDGS/Brave/Playwright during benchmark: {sum(m.get('ddgs_call_count', 0) + m.get('brave_call_count', 0) + m.get('playwright_call_count', 0) for m in manifests)}

## Memory/Strategy Instrumentation Map

{_instrumentation_map(summary)}

## Session Table

{_session_table(manifests)}

## Aggregate Slopes

{_aggregate_table(aggregates)}

## ARM_ON vs ARM_OFF Comparison

```json
{json.dumps(comparison, indent=2)}
```

## Missing / Unavailable Metrics

- `memory_recall_relevance`
- `avoided_previous_failure`
- semantic relevance of retrieved memories

## Verdict

{verdict}

Reasons:

{chr(10).join(f"- {reason}" for reason in reasons)}

## Interpretation

D3.0B improves observability of SHARD's memory/strategy learning signals under a longitudinal protocol. It does not make a performance claim.

## Limitations

- Memory reads remain partially log-derived unless core memory retrieval emits structured events.
- Storage deltas show writes, not semantic usefulness.
- Filesystem snapshot/restore reduces arm leakage risk but is not a native memory namespace.

## Forbidden Claim

GWT improves SHARD performance.

## Next Step

If memory/strategy writes are visible but retrieval relevance remains unavailable, add structured retrieval events before scaling D3.
"""
    DOC_REPORT.write_text(text, encoding="utf-8")


def main() -> None:
    run_root = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_run_root()
    if run_root is None:
        raise SystemExit("No D3.0B run directory found.")
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
    result_path = run_root / "d3_0b_analysis.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    _write_report(run_root, summary, aggregates, comparison, verdict, reasons)
    print("=" * 70)
    print(f"D3.0B VERDICT: {verdict}")
    print(f"Reasons: {reasons}")
    print(f"Analysis: {result_path}")
    print(f"Report:   {DOC_REPORT}")
    print("=" * 70)


if __name__ == "__main__":
    main()
