"""d3_0c_benchmark.py -- D3.0C strategy update path diagnostic.

Diagnostic-only wrapper around the D3.0B longitudinal harness. It adds
structured strategy-update diagnostics without changing SHARD behavior or
touching core runtime files.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import d3_0b_benchmark as base

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d3_0c_runs"
PLANNING_COMMIT = "79836d6"
UNAVAILABLE = "UNAVAILABLE"


def _restore_memory_atomic(snapshot_dir: Path, run_root: Path, label: str) -> None:
    """Restore shard_memory without deleting it first.

    Windows can keep SQLite files locked. A rename either succeeds as a unit or
    fails before removing the live directory, which avoids partial deletion.
    """
    live = base.SHARD_MEMORY
    previous = run_root / f"_previous_memory_{label}_{datetime.now().strftime('%H%M%S')}"
    if live.exists():
        live.rename(previous)
    shutil.copytree(snapshot_dir, live)
    if previous.exists():
        try:
            base._remove_tree(previous)
        except Exception:
            # Runtime artifact only. Keeping it is safer than risking data loss.
            pass


def _storage_matches(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = (
        "experiments_count",
        "memories_count",
        "memory_links_count",
        "semantic_embedding_count",
        "strategy_embedding_count",
        "session_snapshots_count",
    )
    return all(a.get(k) == b.get(k) for k in keys)


def _success_signal_available(manifest: dict[str, Any]) -> bool:
    b = manifest.get("behavior_metrics", {})
    return b.get("certification_verdict") != base.MISSING and b.get("final_score") != base.MISSING


def _failure_attribution_available(manifest: dict[str, Any]) -> bool:
    mem = manifest.get("memory_metrics", {})
    strat = manifest.get("strategy_metrics", {})
    return bool(mem.get("prior_failure_referenced")) or bool(strat.get("strategy_failure_attribution_count", 0))


def _diagnostics(manifest: dict[str, Any], previous_manifest: dict[str, Any] | None) -> dict[str, Any]:
    strat = manifest.get("strategy_metrics", {})
    storage = manifest.get("storage_instrumentation", {})
    deltas = storage.get("storage_deltas", {})
    strategy_update_success_count = int(strat.get("strategy_update_count") or 0)
    strategy_update_attempt_count = strategy_update_success_count
    strategy_delta = deltas.get("strategy_embedding_count_delta")
    write_path_hit = strategy_update_success_count > 0 or (isinstance(strategy_delta, int) and strategy_delta > 0)
    read_path_hit = int(strat.get("strategy_read_count") or 0) > 0

    if strategy_update_success_count > 0:
        skip_reason = None
        source = "strategy_chroma_delta_or_store_marker"
    elif read_path_hit:
        skip_reason = "UPDATE_PATH_NOT_REACHED_BY_OBSERVABLE_MARKERS"
        source = "no_strategy_store_marker_or_strategy_chroma_delta"
    else:
        skip_reason = "STRATEGY_READ_PATH_NOT_REACHED"
        source = "no_strategy_read_marker"

    persistence_after_session_check: bool | str
    if previous_manifest is None:
        persistence_after_session_check = UNAVAILABLE
    else:
        prev_after = previous_manifest.get("storage_instrumentation", {}).get("storage_after", {})
        current_before = storage.get("storage_before", {})
        persistence_after_session_check = _storage_matches(prev_after, current_before)

    return {
        "strategy_update_attempt_count": strategy_update_attempt_count,
        "strategy_update_success_count": strategy_update_success_count,
        "strategy_update_skip_reason": skip_reason,
        "strategy_update_source": source,
        "strategy_memory_write_path_hit": write_path_hit,
        "strategy_memory_read_path_hit": read_path_hit,
        "update_gate_success_signal_available": _success_signal_available(manifest),
        "update_gate_failure_attribution_available": _failure_attribution_available(manifest),
        "update_gate_certification_available": manifest.get("behavior_metrics", {}).get("certification_verdict") != base.MISSING,
        "update_gate_final_score_available": manifest.get("behavior_metrics", {}).get("final_score") != base.MISSING,
        "persistence_after_session_check": persistence_after_session_check,
        "diagnostic_scope": "benchmark_side_storage_delta_and_log_marker_diagnostic",
    }


def _rewrite_manifest(manifest: dict[str, Any], previous_manifest: dict[str, Any] | None) -> dict[str, Any]:
    manifest["d3_version"] = "D3.0C"
    manifest["planning_commit"] = PLANNING_COMMIT
    manifest["strategy_update_diagnostics"] = _diagnostics(manifest, previous_manifest)
    run_dir = RUNS_ROOT / manifest["relative_run_dir"]
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abort-on-contam", action="store_true")
    args = parser.parse_args()

    base.RUNS_ROOT = RUNS_ROOT
    base.PLANNING_COMMIT = PLANNING_COMMIT
    cache_meta = base._preflight_cache()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    baseline_snapshot = run_root / "_memory_baseline_before_d3_0c"
    original_snapshot = run_root / "_memory_original_restore_point"
    original_snapshot_info = base._snapshot_memory(original_snapshot)
    base._copy_tree(original_snapshot, baseline_snapshot)

    expected_sessions = len(base.ARMS) * len(base.SESSION_TOPICS)
    manifests: list[dict[str, Any]] = []
    previous_by_arm: dict[str, dict[str, Any]] = {}
    aborted = False
    started_at = datetime.now().isoformat()
    print("=" * 70)
    print("D3.0C STRATEGY UPDATE PATH DIAGNOSTIC")
    print("=" * 70)
    print(f"Run root:        {run_root}")
    print(f"Planning commit: {PLANNING_COMMIT}")
    print(f"Expected runs:   {expected_sessions}")
    print("Live providers:  forbidden during benchmark")
    print("=" * 70)
    try:
        for arm in base.ARMS:
            print(f"\n[D3.0C] Restoring baseline memory before {arm['name']}...")
            _restore_memory_atomic(baseline_snapshot, run_root, arm["name"].lower())
            previous_by_arm.pop(arm["name"], None)
            for session_index, topic in enumerate(base.SESSION_TOPICS, start=1):
                manifest = base._run_session(arm, session_index, topic, run_root, cache_meta)
                manifest = _rewrite_manifest(manifest, previous_by_arm.get(arm["name"]))
                previous_by_arm[arm["name"]] = manifest
                manifests.append(manifest)
                diag = manifest["strategy_update_diagnostics"]
                print(
                    f"[{manifest['run_id']}] diag attempts={diag['strategy_update_attempt_count']} "
                    f"success={diag['strategy_update_success_count']} skip={diag['strategy_update_skip_reason']} "
                    f"persist={diag['persistence_after_session_check']}"
                )
                if args.abort_on_contam and (manifest["contaminated"] or manifest["abort_reason"]):
                    aborted = True
                    break
            if aborted:
                break
    finally:
        print("\n[D3.0C] Restoring original shard_memory state...")
        _restore_memory_atomic(original_snapshot, run_root, "original")

    finished_at = datetime.now().isoformat()
    summary = {
        "d3_version": "D3.0C",
        "planning_commit": PLANNING_COMMIT,
        "started_at": started_at,
        "finished_at": finished_at,
        "topic_family": base.TOPIC_FAMILY,
        "session_topics": base.SESSION_TOPICS,
        "arms": [a["name"] for a in base.ARMS],
        "expected_sessions": expected_sessions,
        "actual_sessions": len(manifests),
        "cache_meta": cache_meta,
        "memory_isolation": {
            "method": "shard_memory_snapshot_restore_between_arms",
            "persistence_within_arm": True,
            "baseline_snapshot": base._safe_relative(baseline_snapshot),
            "original_restore_point": base._safe_relative(original_snapshot),
            "original_snapshot_info": original_snapshot_info,
            "core_namespace_support": False,
        },
        "instrumented_files": [
            "backend/d3_0c_benchmark.py",
            "backend/d3_0c_analyze.py",
        ],
        "core_behavior_changes": False,
        "aborted": aborted,
        "manifests": manifests,
    }
    summary_path = run_root / "d3_0c_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    print()
    print("=" * 70)
    print(f"Total sessions: {len(manifests)} / {expected_sessions}")
    print(f"Contaminated:   {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Abort reasons:  {[m['abort_reason'] for m in manifests if m['abort_reason']]}")
    print(f"Summary:        {summary_path}")
    print(f"Next: python backend/d3_0c_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
