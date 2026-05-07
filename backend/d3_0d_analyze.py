"""d3_0d_analyze.py -- analyzer for D3.0D post-failure strategy updates."""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d3_0d_runs"
DOC_REPORT = _ROOT / "docs" / "experiments" / "d3_0d_minimal_post_failure_strategy_update.md"
UNAVAILABLE = "UNAVAILABLE"


def _latest_run_root() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    candidates = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


def _load_summary(run_root: Path) -> dict[str, Any]:
    path = run_root / "d3_0d_summary.json"
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
    if any(v is None for v in nums) or len(nums) < 2:
        return UNAVAILABLE
    xs = list(range(1, len(nums) + 1))
    xbar = statistics.mean(xs)
    ybar = statistics.mean(nums)
    denom = sum((x - xbar) ** 2 for x in xs)
    return round(sum((x - xbar) * (y - ybar) for x, y in zip(xs, nums)) / denom, 4)


def _metric(manifest: dict[str, Any], namespace: str, key: str) -> Any:
    return manifest.get(namespace, {}).get(key, UNAVAILABLE)


def _pf(manifest: dict[str, Any], key: str) -> Any:
    return manifest.get("post_failure_strategy_update", {}).get(key, UNAVAILABLE)


def _group_by_arm(manifests: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for manifest in sorted(manifests, key=lambda m: (m["arm"], int(m["session_index"]))):
        grouped.setdefault(manifest["arm"], []).append(manifest)
    return grouped


def _arm_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "session_count": len(rows),
        "update_attempt_count_total": sum(int(_pf(m, "post_failure_strategy_update_attempted") or 0) for m in rows),
        "update_success_count_total": sum(int(_pf(m, "post_failure_strategy_update_success") or 0) for m in rows),
        "strategy_entries_written_total": sum(int(_pf(m, "strategy_entries_written") or 0) for m in rows),
        "strategy_entries_recalled_later_count": sum(
            int(_pf(m, "strategy_entries_recalled_later") or 0)
            for m in rows
            if isinstance(_pf(m, "strategy_entries_recalled_later"), int)
        ),
        "strategy_read_count_mean": _mean([_metric(m, "strategy_metrics", "strategy_read_count") for m in rows]),
        "strategy_read_count_slope": _slope([_metric(m, "strategy_metrics", "strategy_read_count") for m in rows]),
        "strategy_update_count_slope": _slope([_pf(m, "post_failure_strategy_update_success") for m in rows]),
        "final_score_mean": _mean([_metric(m, "behavior_metrics", "final_score") for m in rows]),
        "final_score_slope": _slope([_metric(m, "behavior_metrics", "final_score") for m in rows]),
        "loop_risk_slope": _slope([_metric(m, "behavior_metrics", "loop_risk_proxy") for m in rows]),
        "repeated_strategy_slope": _slope([_metric(m, "behavior_metrics", "repeated_strategy_count") for m in rows]),
    }


def _skip_counts(manifests: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for manifest in manifests:
        counts[str(_pf(manifest, "post_failure_strategy_update_skip_reason"))] += 1
    return dict(counts)


def _compare(aggregates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    off = aggregates.get("ARM_OFF", {})
    on = aggregates.get("ARM_ON", {})
    keys = (
        "update_attempt_count_total",
        "update_success_count_total",
        "strategy_entries_written_total",
        "final_score_mean",
        "final_score_slope",
        "loop_risk_slope",
        "repeated_strategy_slope",
    )
    out: dict[str, Any] = {}
    for key in keys:
        if isinstance(on.get(key), (int, float)) and isinstance(off.get(key), (int, float)):
            out[f"{key}_arm_on_minus_off"] = round(float(on[key]) - float(off[key]), 4)
        else:
            out[f"{key}_arm_on_minus_off"] = UNAVAILABLE
    return out


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

    attempts = sum(a.get("update_attempt_count_total", 0) for a in aggregates.values())
    successes = sum(a.get("update_success_count_total", 0) for a in aggregates.values())
    entries = sum(a.get("strategy_entries_written_total", 0) for a in aggregates.values())
    recalled = sum(a.get("strategy_entries_recalled_later_count", 0) for a in aggregates.values())

    if attempts > 0 and successes > 0 and entries > 0 and recalled > 0:
        return "PASS_STRONG", [
            "post-failure update attempts and successes visible",
            "append-only strategy entries written",
            "later recall observed",
        ]
    if attempts > 0 and successes > 0 and entries > 0:
        return "PASS_WEAK", [
            "post-failure update attempts and successes visible",
            "append-only strategy entries written",
            "later recall weak or not observable",
        ]
    if attempts == 0 and not skip_counts:
        return "FAIL", ["trigger still does not reach update path"]
    return "INCONCLUSIVE", ["updates ambiguous or attribution missing"]


def _session_table(manifests: list[dict[str, Any]]) -> str:
    lines = [
        "| Arm | Session | Topic | Score | Attempts | Success | Skip reason | Entries written | Recalled later |",
        "| --- | ---: | --- | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for m in sorted(manifests, key=lambda item: (item["arm"], int(item["session_index"]))):
        b = m.get("behavior_metrics", {})
        lines.append(
            f"| {m['arm']} | {m['session_index']} | {m['topic']} | {b.get('final_score')} | "
            f"{_pf(m, 'post_failure_strategy_update_attempted')} | "
            f"{_pf(m, 'post_failure_strategy_update_success')} | "
            f"{_pf(m, 'post_failure_strategy_update_skip_reason')} | "
            f"{_pf(m, 'strategy_entries_written')} | "
            f"{_pf(m, 'strategy_entries_recalled_later')} |"
        )
    return "\n".join(lines)


def _aggregate_table(aggregates: dict[str, dict[str, Any]]) -> str:
    keys = (
        "update_attempt_count_total",
        "update_success_count_total",
        "strategy_entries_written_total",
        "strategy_entries_recalled_later_count",
        "strategy_read_count_mean",
        "strategy_read_count_slope",
        "strategy_update_count_slope",
        "final_score_mean",
        "final_score_slope",
        "loop_risk_slope",
        "repeated_strategy_slope",
    )
    lines = ["| Metric | ARM_OFF | ARM_ON |", "| --- | ---: | ---: |"]
    for key in keys:
        lines.append(f"| {key} | {aggregates.get('ARM_OFF', {}).get(key)} | {aggregates.get('ARM_ON', {}).get(key)} |")
    return "\n".join(lines)


def _write_report(run_root: Path, summary: dict[str, Any], aggregates: dict[str, dict[str, Any]], comparison: dict[str, Any], skip_counts: dict[str, int], verdict: str, reasons: list[str]) -> None:
    DOC_REPORT.parent.mkdir(parents=True, exist_ok=True)
    manifests = summary["manifests"]
    text = f"""# D3.0D Minimal Post-Failure Strategy Update

## Status

Run analyzed.

Audit commit: `{summary['audit_commit']}`

Run directory: `{run_root.relative_to(_ROOT).as_posix()}`

## Micro-Fix Applied

D3.0D enables an env-gated append-only post-failure StrategyMemory record after uncertified study completion. The record uses `StrategyMemory.store_strategy(...)` with `outcome="failure_learning"` and a strategy text containing failure mode, score, suggested alternative, and avoid-next-time fields.

## Files / Functions Modified

- `backend/study_phases.py::CertifyRetryGroup._post_failure_strategy_update`
- `backend/d3_0d_benchmark.py`
- `backend/d3_0d_analyze.py`

## Behavior Guard

- Scoring unchanged
- Retry policy unchanged
- `MAX_RETRY` unchanged
- Certification threshold unchanged
- `_WINNER_BIAS` unchanged
- ValenceField unchanged
- Stress injection unchanged
- Topic handling unchanged
- Strategy writes are append-only; no existing strategies are deleted or overwritten

## Harness Sanity

- Expected sessions: {summary['expected_sessions']}
- Actual sessions: {summary['actual_sessions']}
- Contaminated sessions: {sum(1 for m in manifests if m.get('contaminated'))}
- Abort reasons: {[m.get('abort_reason') for m in manifests if m.get('abort_reason')]}
- Live DDGS/Brave/Playwright during benchmark: {sum(m.get('ddgs_call_count', 0) + m.get('brave_call_count', 0) + m.get('playwright_call_count', 0) for m in manifests)}

## Update Attempt / Success Table

{_session_table(manifests)}

## Skip Reasons

```json
{json.dumps(skip_counts, indent=2)}
```

## Aggregate Metrics

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

D3.0D tests whether minimal post-failure append-only strategy records make strategy updates observable under the longitudinal protocol. The experiment does not test performance improvement.

## Limitations

- Later recall of `failure_learning` entries is not reliably observable from current logs.
- Strategy text is attribution-derived and conservative; it is not a semantic proof of strategy quality.
- This run does not prove autonomous learning or operational value.

## Next Step

If D3.0D reaches PASS_WEAK, the next step should harden recall provenance for `failure_learning` entries before scaling D3.

## Forbidden Claims

- GWT improves SHARD performance.
- SHARD learns autonomously.
- D3.0D proves learning.
"""
    DOC_REPORT.write_text(text, encoding="utf-8")


def main() -> None:
    run_root = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_run_root()
    if run_root is None:
        raise SystemExit("No D3.0D run directory found.")
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
    result_path = run_root / "d3_0d_analysis.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    _write_report(run_root, summary, aggregates, comparison, skip_counts, verdict, reasons)
    print("=" * 70)
    print(f"D3.0D VERDICT: {verdict}")
    print(f"Reasons: {reasons}")
    print(f"Analysis: {result_path}")
    print(f"Report:   {DOC_REPORT}")
    print("=" * 70)


if __name__ == "__main__":
    main()
