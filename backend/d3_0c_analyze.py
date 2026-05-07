"""d3_0c_analyze.py -- analyzer for D3.0C strategy update diagnostic."""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d3_0c_runs"
DOC_REPORT = _ROOT / "docs" / "experiments" / "d3_0c_strategy_update_diagnostic.md"
UNAVAILABLE = "UNAVAILABLE"


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    candidates = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def _load_summary(run_root: Path) -> dict[str, Any]:
    path = run_root / "d3_0c_summary.json"
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


def _diag(manifest: dict[str, Any], key: str) -> Any:
    return manifest.get("strategy_update_diagnostics", {}).get(key, UNAVAILABLE)


def _metric(manifest: dict[str, Any], namespace: str, key: str) -> Any:
    return manifest.get(namespace, {}).get(key, UNAVAILABLE)


def _group_by_arm(manifests: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for manifest in sorted(manifests, key=lambda m: (m["arm"], int(m["session_index"]))):
        grouped.setdefault(manifest["arm"], []).append(manifest)
    return grouped


def _arm_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "session_count": len(rows),
        "update_attempt_count_total": sum(int(_diag(m, "strategy_update_attempt_count") or 0) for m in rows),
        "update_success_count_total": sum(int(_diag(m, "strategy_update_success_count") or 0) for m in rows),
        "read_path_hit_rate": _rate([_diag(m, "strategy_memory_read_path_hit") for m in rows]),
        "write_path_hit_rate": _rate([_diag(m, "strategy_memory_write_path_hit") for m in rows]),
        "success_signal_available_rate": _rate([_diag(m, "update_gate_success_signal_available") for m in rows]),
        "failure_attribution_available_rate": _rate([_diag(m, "update_gate_failure_attribution_available") for m in rows]),
        "persistence_check_pass_rate": _rate([
            v for v in [_diag(m, "persistence_after_session_check") for m in rows]
            if isinstance(v, bool)
        ]),
        "final_score_mean": _mean([_metric(m, "behavior_metrics", "final_score") for m in rows]),
        "strategy_read_count_mean": _mean([_metric(m, "strategy_metrics", "strategy_read_count") for m in rows]),
        "strategy_update_count_mean": _mean([_metric(m, "strategy_metrics", "strategy_update_count") for m in rows]),
    }


def _skip_counts(manifests: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for manifest in manifests:
        reason = _diag(manifest, "strategy_update_skip_reason")
        counts[str(reason)] += 1
    return dict(counts)


def _compare(aggregates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    off = aggregates.get("ARM_OFF", {})
    on = aggregates.get("ARM_ON", {})
    keys = (
        "update_attempt_count_total",
        "update_success_count_total",
        "read_path_hit_rate",
        "write_path_hit_rate",
        "success_signal_available_rate",
        "failure_attribution_available_rate",
        "persistence_check_pass_rate",
        "final_score_mean",
    )
    return {f"{key}_arm_on_minus_off": (
        round(float(on[key]) - float(off[key]), 4)
        if isinstance(on.get(key), (int, float)) and isinstance(off.get(key), (int, float))
        else None
    ) for key in keys}


def _verdict(summary: dict[str, Any], aggregates: dict[str, dict[str, Any]], skip_counts: dict[str, int]) -> tuple[str, list[str]]:
    manifests = summary["manifests"]
    if any(m.get("contaminated") for m in manifests):
        return "CONTAMINATED", ["live provider or contamination marker observed"]
    if any(m.get("abort_reason") for m in manifests):
        return "CONTAMINATED", ["one or more sessions failed harness sanity"]
    if summary.get("actual_sessions") != summary.get("expected_sessions"):
        return "CONTAMINATED", ["expected session count not completed"]
    if any(a.get("session_count") != 5 for a in aggregates.values()):
        return "INCONCLUSIVE", ["session boundaries incomplete"]

    has_skip_reason = any(k not in ("None", "null", "UNAVAILABLE") for k in skip_counts)
    read_visibility = all(a.get("read_path_hit_rate") == 1.0 for a in aggregates.values())
    persistence_visible = all(a.get("persistence_check_pass_rate") == 1.0 for a in aggregates.values())
    update_attempts = sum(a.get("update_attempt_count_total", 0) for a in aggregates.values())

    if has_skip_reason and read_visibility and persistence_visible:
        return "PASS_STRONG", [
            "structured skip reasons explain zero strategy updates",
            "strategy read path visible",
            "within-arm persistence verified",
        ]
    if has_skip_reason or update_attempts > 0:
        return "PASS_WEAK", ["some update attempts or skip reasons visible, but coverage incomplete"]
    return "FAIL", ["instrumentation still cannot locate strategy update path"]


def _session_table(manifests: list[dict[str, Any]]) -> str:
    lines = [
        "| Arm | Session | Topic | Score | Read hit | Write hit | Attempts | Success | Skip reason | Failure attribution | Persistence check |",
        "| --- | ---: | --- | ---: | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for m in sorted(manifests, key=lambda item: (item["arm"], int(item["session_index"]))):
        d = m.get("strategy_update_diagnostics", {})
        b = m.get("behavior_metrics", {})
        lines.append(
            f"| {m['arm']} | {m['session_index']} | {m['topic']} | {b.get('final_score')} | "
            f"{d.get('strategy_memory_read_path_hit')} | {d.get('strategy_memory_write_path_hit')} | "
            f"{d.get('strategy_update_attempt_count')} | {d.get('strategy_update_success_count')} | "
            f"{d.get('strategy_update_skip_reason')} | {d.get('update_gate_failure_attribution_available')} | "
            f"{d.get('persistence_after_session_check')} |"
        )
    return "\n".join(lines)


def _aggregate_table(aggregates: dict[str, dict[str, Any]]) -> str:
    keys = (
        "update_attempt_count_total",
        "update_success_count_total",
        "read_path_hit_rate",
        "write_path_hit_rate",
        "success_signal_available_rate",
        "failure_attribution_available_rate",
        "persistence_check_pass_rate",
        "final_score_mean",
    )
    lines = ["| Metric | ARM_OFF | ARM_ON |", "| --- | ---: | ---: |"]
    for key in keys:
        lines.append(f"| {key} | {aggregates.get('ARM_OFF', {}).get(key)} | {aggregates.get('ARM_ON', {}).get(key)} |")
    return "\n".join(lines)


def _write_report(run_root: Path, summary: dict[str, Any], aggregates: dict[str, dict[str, Any]], comparison: dict[str, Any], skip_counts: dict[str, int], verdict: str, reasons: list[str]) -> None:
    DOC_REPORT.parent.mkdir(parents=True, exist_ok=True)
    manifests = summary["manifests"]
    text = f"""# D3.0C Strategy Update Path Diagnostic

## Status

Run analyzed.

Planning commit: `{summary['planning_commit']}`

Run directory: `{run_root.relative_to(_ROOT).as_posix()}`

## Protocol

- Arms: ARM_OFF vs ARM_ON
- Sessions per arm: 5
- Same D3.0A/B topic sequence
- Cached sources only
- Arm isolation: `{summary['memory_isolation']['method']}`
- Persistence enabled within each arm

## File / Function Instrumentation

- `backend/d3_0c_benchmark.py`: benchmark-side strategy update diagnostics
- `backend/d3_0c_analyze.py`: aggregate diagnostics and report
- Core runtime files were not modified for D3.0C.

## Behavior Change Guard

- No `_WINNER_BIAS` changes
- No ValenceField changes
- No stress injection changes
- No topic handling changes
- No scoring or certification threshold changes
- No forced strategy updates

## Harness Sanity

- Expected sessions: {summary['expected_sessions']}
- Actual sessions: {summary['actual_sessions']}
- Contaminated sessions: {sum(1 for m in manifests if m.get('contaminated'))}
- Abort reasons: {[m.get('abort_reason') for m in manifests if m.get('abort_reason')]}
- Live DDGS/Brave/Playwright during benchmark: {sum(m.get('ddgs_call_count', 0) + m.get('brave_call_count', 0) + m.get('playwright_call_count', 0) for m in manifests)}

## Per-Session Diagnostic Table

{_session_table(manifests)}

## Skip Reason Counts

```json
{json.dumps(skip_counts, indent=2)}
```

## Aggregate Visibility

{_aggregate_table(aggregates)}

## ARM_OFF vs ARM_ON Comparison

```json
{json.dumps(comparison, indent=2)}
```

## Verdict

{verdict}

Reasons:

{chr(10).join(f"- {reason}" for reason in reasons)}

## Interpretation

D3.0C diagnoses whether the strategy update path is reachable and why updates are skipped under D3 longitudinal conditions. The diagnostic is intentionally conservative and does not change learning behavior.

## Missing / Unavailable Metrics

- Exact core-level skip reason from inside `StrategyMemory.store_strategy*`
- Semantic quality of failure attribution
- Whether a stronger attribution object would have produced an update

## Next Step Recommendation

If D3.0C shows the observable update path is not reached, D3.0D should add core-level structured update-attempt markers at the specific write gates before testing any behavior change.

## Forbidden Claim

GWT improves SHARD performance.
"""
    DOC_REPORT.write_text(text, encoding="utf-8")


def main() -> None:
    run_root = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_run_root()
    if run_root is None:
        raise SystemExit("No D3.0C run directory found.")
    run_root = run_root.resolve()
    summary = _load_summary(run_root)
    grouped = _group_by_arm(summary["manifests"])
    aggregates = {arm: _arm_metrics(rows) for arm, rows in grouped.items()}
    skip_counts = _skip_counts(summary["manifests"])
    comparison = _compare(aggregates)
    verdict, reasons = _verdict(summary, aggregates, skip_counts)
    result = {
        "run_root": str(run_root),
        "verdict": verdict,
        "reasons": reasons,
        "skip_reason_counts": skip_counts,
        "aggregates": aggregates,
        "comparison": comparison,
    }
    result_path = run_root / "d3_0c_analysis.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    _write_report(run_root, summary, aggregates, comparison, skip_counts, verdict, reasons)
    print("=" * 70)
    print(f"D3.0C VERDICT: {verdict}")
    print(f"Reasons: {reasons}")
    print(f"Analysis: {result_path}")
    print(f"Report:   {DOC_REPORT}")
    print("=" * 70)


if __name__ == "__main__":
    main()
