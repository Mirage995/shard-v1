"""d3_0d_benchmark.py -- D3.0D minimal post-failure strategy update.

Runs the D3 longitudinal micro-protocol with an env-gated append-only
failure-learning StrategyMemory write enabled in the study subprocess.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import d3_0b_benchmark as base
from d3_0c_benchmark import _restore_memory_atomic

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d3_0d_runs"
AUDIT_COMMIT = "4e720172a5ba2f114b87f0dd0599cb138317dfb4"
UNAVAILABLE = "UNAVAILABLE"

_ORIG_SUBPROCESS_RUN = base.subprocess.run


def _run_with_d3_0d_env(*args: Any, **kwargs: Any) -> Any:
    env = dict(kwargs.get("env") or os.environ.copy())
    env["D3_POST_FAILURE_STRATEGY_UPDATE"] = "1"
    env["D3_TOPIC_FAMILY"] = base.TOPIC_FAMILY
    env.setdefault("D3_SESSION_ID", "d3_0d_subprocess_session")
    kwargs["env"] = env
    return _ORIG_SUBPROCESS_RUN(*args, **kwargs)


def _kv_value(line: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}=([^ ]+)", line)
    return match.group(1) if match else None


def _post_failure_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    run_dir = RUNS_ROOT / manifest["relative_run_dir"]
    stdout_path = run_dir / "stdout.log"
    text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
    lines = [line for line in text.splitlines() if "[D3_0D_POST_FAILURE_STRATEGY]" in line]
    attempted = 0
    success = 0
    skip_reasons: list[str] = []
    attribution_available = False
    for line in lines:
        attempted += int(_kv_value(line, "attempted") or 0)
        success += int(_kv_value(line, "success") or 0)
        skip = _kv_value(line, "skip_reason")
        if skip:
            skip_reasons.append(skip)
        attribution_available = attribution_available or (_kv_value(line, "attribution") == "1")
    if not lines:
        skip_reasons.append("MARKER_MISSING")
    return {
        "post_failure_strategy_update_attempted": attempted,
        "post_failure_strategy_update_success": success,
        "post_failure_strategy_update_skip_reason": skip_reasons[-1] if skip_reasons else None,
        "post_failure_strategy_update_skip_reasons": skip_reasons,
        "post_failure_strategy_update_source": "post_failure_diagnostic",
        "failure_attribution_available": attribution_available,
        "strategy_record_outcome": "failure_learning" if success > 0 else UNAVAILABLE,
        "strategy_entries_written": success,
        "strategy_entries_recalled_later": UNAVAILABLE,
        "marker_count": len(lines),
    }


def _rewrite_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["d3_version"] = "D3.0D"
    manifest["audit_commit"] = AUDIT_COMMIT
    post_failure = _post_failure_metrics(manifest)
    manifest["post_failure_strategy_update"] = post_failure
    manifest["strategy_update_diagnostics"] = {
        "strategy_update_attempt_count": post_failure["post_failure_strategy_update_attempted"],
        "strategy_update_success_count": post_failure["post_failure_strategy_update_success"],
        "strategy_update_skip_reason": post_failure["post_failure_strategy_update_skip_reason"],
        "strategy_memory_write_path_hit": post_failure["post_failure_strategy_update_success"] > 0,
        "strategy_memory_read_path_hit": int(manifest.get("strategy_metrics", {}).get("strategy_read_count") or 0) > 0,
        "failure_attribution_available": post_failure["failure_attribution_available"],
        "source": "d3_0d_post_failure_append_only_record",
    }
    run_dir = RUNS_ROOT / manifest["relative_run_dir"]
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abort-on-contam", action="store_true")
    args = parser.parse_args()

    base.RUNS_ROOT = RUNS_ROOT
    base.PLANNING_COMMIT = AUDIT_COMMIT
    base.subprocess.run = _run_with_d3_0d_env

    cache_meta = base._preflight_cache()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    baseline_snapshot = run_root / "_memory_baseline_before_d3_0d"
    original_snapshot = run_root / "_memory_original_restore_point"
    original_snapshot_info = base._snapshot_memory(original_snapshot)
    base._copy_tree(original_snapshot, baseline_snapshot)

    expected_sessions = len(base.ARMS) * len(base.SESSION_TOPICS)
    manifests: list[dict[str, Any]] = []
    aborted = False
    started_at = datetime.now().isoformat()
    print("=" * 70)
    print("D3.0D MINIMAL POST-FAILURE STRATEGY UPDATE")
    print("=" * 70)
    print(f"Run root:      {run_root}")
    print(f"Audit commit:  {AUDIT_COMMIT}")
    print(f"Expected runs: {expected_sessions}")
    print("Live providers: forbidden during benchmark")
    print("=" * 70)
    try:
        for arm in base.ARMS:
            print(f"\n[D3.0D] Restoring baseline memory before {arm['name']}...")
            _restore_memory_atomic(baseline_snapshot, run_root, arm["name"].lower())
            for session_index, topic in enumerate(base.SESSION_TOPICS, start=1):
                manifest = base._run_session(arm, session_index, topic, run_root, cache_meta)
                manifest = _rewrite_manifest(manifest)
                manifests.append(manifest)
                pf = manifest["post_failure_strategy_update"]
                print(
                    f"[{manifest['run_id']}] post_failure attempts={pf['post_failure_strategy_update_attempted']} "
                    f"success={pf['post_failure_strategy_update_success']} "
                    f"skip={pf['post_failure_strategy_update_skip_reason']} "
                    f"entries={pf['strategy_entries_written']}"
                )
                if args.abort_on_contam and (manifest["contaminated"] or manifest["abort_reason"]):
                    aborted = True
                    break
            if aborted:
                break
    finally:
        base.subprocess.run = _ORIG_SUBPROCESS_RUN
        print("\n[D3.0D] Restoring original shard_memory state...")
        _restore_memory_atomic(original_snapshot, run_root, "original")

    summary = {
        "d3_version": "D3.0D",
        "audit_commit": AUDIT_COMMIT,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(),
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
        },
        "behavior_change_guard": {
            "env_gated": "D3_POST_FAILURE_STRATEGY_UPDATE=1",
            "append_only": True,
            "retry_policy_changed": False,
            "scoring_changed": False,
            "certification_threshold_changed": False,
            "topic_handling_changed": False,
        },
        "aborted": aborted,
        "manifests": manifests,
    }
    summary_path = run_root / "d3_0d_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    print()
    print("=" * 70)
    print(f"Total sessions: {len(manifests)} / {expected_sessions}")
    print(f"Contaminated:   {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Abort reasons:  {[m['abort_reason'] for m in manifests if m['abort_reason']]}")
    print(f"Summary:        {summary_path}")
    print(f"Next: python backend/d3_0d_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
