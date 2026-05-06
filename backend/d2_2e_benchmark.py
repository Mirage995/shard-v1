"""d2_2e_benchmark.py -- D2.2E retry strategy divergence measurement.

D2.2E reuses the D2.2D protocol without changing the D2.2D reflection
directive. It adds log-derived retry strategy hash instrumentation so the
analyzer can test whether retry plans materially diverge under ARM_ON:

    2 topic sequences x 2 reps x 2 arms = 8 subprocesses

This is not D2.2 full and not a general performance claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

CACHE_DIR = _ROOT / "shard_workspace" / "d2_cached_sources"
RUNS_ROOT = _ROOT / "shard_workspace" / "d2_2e_runs"
MOOD_HISTORY = _ROOT / "shard_memory" / "mood_history.jsonl"

PLANNING_COMMIT = "b5e87815136c9452e26278e3a51c1c899776c73a"

TOPIC_SEQUENCES = [
    {
        "id": "seq_01_oop_to_asyncio",
        "stress_topic": "python OOP design patterns",
        "observer_topic": "asyncio advanced patterns",
    },
    {
        "id": "seq_02_sql_to_error_handling",
        "stress_topic": "sql injection prevention python",
        "observer_topic": "python error handling patterns",
    },
]

REPLICAS = [1, 2]

ARMS = [
    {"name": "ARM_OFF", "no_l3": True},
    {"name": "ARM_ON", "no_l3": False},
]

SUBPROCESS_TIMEOUT = 2400
METRIC_HARDENING_PLANNING_COMMIT = "02dc5e34574cdf1fa25683262cf8eb83468f0291"
MISSING = "MISSING"
UNAVAILABLE = "UNAVAILABLE"

CERT_RANK = {
    "FAILED": 0,
    "NEAR_MISS": 1,
    "CERTIFIED": 2,
}


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def _topic_sequence(sequence: dict) -> list[str]:
    return [sequence["stress_topic"], sequence["observer_topic"]]


def _cache_path(topic: str) -> Path:
    return CACHE_DIR / f"{_slug(topic)}.json"


def _count_markers(text: str) -> dict:
    http_error_pattern = (
        r"HTTP/(?:1\.1|2)\s+(?:429|500|502|503)\b"
        r"|\b(?:429|500|502|503)\s+"
        r"(?:Too Many Requests|Internal Server Error|Bad Gateway|Service Unavailable)\b"
    )
    return {
        "ddgs_call_count": len(re.findall(r"ddgs\.text|\[MAP\] Smart queries", text)),
        "brave_call_count": len(re.findall(r"search\.brave\.com", text)),
        "playwright_call_count": len(re.findall(r"\[AGGREGATE\] Scraping|page\.goto", text)),
        "fallback_count": len(re.findall(r"\bfallback\b(?!\s+su\s+simulazione)", text, re.I)),
        "http_error_count": len(re.findall(http_error_pattern, text, flags=re.I)),
        "cache_hit_map": len(re.findall(r"\[D2_CACHE_HIT_MAP\]", text)),
        "cache_hit_aggregate": len(re.findall(r"\[D2_CACHE_HIT_AGGREGATE\]", text)),
        "stress_injection_count": len(re.findall(r"\[D2_STRESS\]", text)),
        "force_topic_seq_count": len(re.findall(r"\[FORCE-TOPIC-SEQUENCE\]", text)),
        "retry_attempt_count": len(re.findall(r"attempt \d+/\d+", text, re.I)),
        "gwt_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\]", text)),
        "tensions_bid_trace_count": len(re.findall(r"\[GWT_BID_TRACE\].*tensions", text)),
        "reflection_trigger_count": len(re.findall(r"\[D2_2D_DECISION_COUPLING\]", text)),
        "micro_coupling_applied_count": len(re.findall(r"\[D2_2D_DECISION_COUPLING\].*applied=1", text)),
        "reflection_directive_count": len(re.findall(r"\[D2_2D_DECISION_COUPLING\].*directive=1", text)),
        "strategy_shift_directive_count": len(re.findall(r"\[D2_2D_DECISION_COUPLING\].*strategy_shift_directive=1", text)),
        "repeated_failure_detected_count": len(re.findall(r"\[D2_2D_DECISION_COUPLING\].*repeated_failure=1", text)),
    }


def _load_mood_samples(path: Path) -> list[dict]:
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
            continue
    return samples


def _observer_window(text: str, observer_topic: str) -> tuple[dict, str]:
    marker = f"Starting study of '{observer_topic}'"
    start = text.find(marker)
    if start < 0:
        return {
            "topic": observer_topic,
            "start_marker": marker,
            "found": False,
            "start_index": None,
            "source": "stdout_stderr_marker",
        }, ""
    return {
        "topic": observer_topic,
        "start_marker": marker,
        "found": True,
        "start_index": start,
        "source": "stdout_stderr_marker",
    }, text[start:]


def _normalize_strategy_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text[:180]


def _normalize_retry_strategy_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\b20\d{6}_\d{6}\b", " ", text)
    text = re.sub(r"\bd2_2[a-z]_[a-z0-9_]+", " ", text)
    text = re.sub(r"[a-f0-9]{32,64}", " ", text)
    text = re.sub(r"\battempt\s+\d+\s*/\s*\d+\b", " ", text)
    text = re.sub(r"\brep[_ -]?\d+\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strategy_hash(text: str) -> str:
    normalized = _normalize_retry_strategy_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _mood_stats(samples: list[dict]) -> dict:
    if not samples:
        return {
            "available": False,
            "n": 0,
            "mood_traj": [],
            "workspace_bias_traj": [],
            "observer_mood_traj": [],
            "observer_workspace_bias_traj": [],
            "workspace_bias_present": False,
            "observer_workspace_bias_nonzero_count": 0,
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
        "workspace_bias_traj": wb,
        "observer_mood_traj": observer_scores,
        "observer_workspace_bias_traj": observer_wb,
        "workspace_bias_present": any(abs(x) > 0.01 for x in observer_wb),
        "observer_workspace_bias_nonzero_count": sum(1 for x in observer_wb if abs(x) > 0.01),
        "mood_min": mood_min,
        "mood_recovery_delta": mood_recovery_delta,
    }


def _signal_metrics(text: str) -> dict:
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


def _decision_coupling_metrics(text: str) -> dict:
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
        "schema_version": "d2_2d_micro_decision_coupling_v1",
        "source": "structured_manifest",
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
    }


def _retry_strategy_hash_metrics(observer_text: str, observer_found: bool) -> dict:
    if not observer_found:
        return {
            "schema_version": "d2_2e_retry_strategy_hash_v1",
            "source": "structured_manifest_log_derived",
            "retry_hash_available": False,
            "retry_hash_method": "log_focus_gap_proxy_sha256_12",
            "retry_hash_limitations": [
                "observer_section_missing",
                "hashes are derived from retry Focus/gaps log lines, not full semantic retry plans",
            ],
            "retry_plans": [],
            "retry_strategy_hashes": [],
            "retry_strategy_hash_changed": UNAVAILABLE,
            "prior_strategy_named": UNAVAILABLE,
            "material_strategy_shift": UNAVAILABLE,
            "repeated_strategy_count_by_hash": UNAVAILABLE,
        }

    plans = []
    last_focus = ""
    retry_pattern = re.compile(
        r"Regenerating code \(attempt\s+(\d+)/(\d+),\s+gaps:\s*(.*?)\)\.\.\.",
        flags=re.I,
    )
    focus_pattern = re.compile(r"Score\s+[0-9]+(?:\.[0-9]+)?/10\s+--\s+Retrying\.\s+Focus:\s*(.+)", flags=re.I)
    for raw_line in observer_text.splitlines():
        line = raw_line.strip()
        focus_match = focus_pattern.search(line)
        if focus_match:
            last_focus = focus_match.group(1).strip()
            continue
        retry_match = retry_pattern.search(line)
        if not retry_match:
            continue
        attempt_number = int(retry_match.group(1))
        gaps_text = retry_match.group(3).strip()
        proxy_text = f"focus={last_focus} gaps={gaps_text}"
        normalized = _normalize_retry_strategy_text(proxy_text)
        retry_hash = _strategy_hash(proxy_text)
        prior_hash = plans[-1]["retry_strategy_hash"] if plans else None
        plans.append(
            {
                "retry_plan_id": f"retry_{len(plans) + 1:02d}",
                "attempt_number": attempt_number,
                "focus_text": last_focus,
                "gaps_text": gaps_text,
                "normalized_strategy_text": normalized,
                "retry_strategy_hash": retry_hash,
                "prior_strategy_hash": prior_hash,
                "retry_strategy_hash_changed": (retry_hash != prior_hash) if prior_hash else UNAVAILABLE,
            }
        )

    hashes = [p["retry_strategy_hash"] for p in plans]
    changed_values = [p["retry_strategy_hash_changed"] for p in plans if isinstance(p["retry_strategy_hash_changed"], bool)]
    if not plans:
        changed: bool | str = UNAVAILABLE
        material_shift: bool | str = UNAVAILABLE
        repeated_count: int | str = UNAVAILABLE
    else:
        changed = any(changed_values) if changed_values else UNAVAILABLE
        material_shift = changed
        repeated_count = max(0, len(hashes) - len(set(hashes)))

    return {
        "schema_version": "d2_2e_retry_strategy_hash_v1",
        "source": "structured_manifest_log_derived",
        "retry_hash_available": bool(plans),
        "retry_hash_method": "log_focus_gap_proxy_sha256_12",
        "retry_hash_limitations": [
            "hashes are derived from retry Focus/gaps log lines, not full semantic retry plans",
            "hash changes indicate proxy text changes, not guaranteed semantic strategy shifts",
            "prior_strategy_named is unavailable because full retry prompt text is not logged",
        ],
        "retry_plans": plans,
        "retry_strategy_hashes": hashes,
        "retry_strategy_hash_changed": changed,
        "prior_strategy_named": UNAVAILABLE,
        "material_strategy_shift": material_shift,
        "repeated_strategy_count_by_hash": repeated_count,
    }


def _behavior_metrics(observer_text: str, observer_found: bool) -> dict:
    if not observer_found:
        return {
            "schema_version": "d2_2b_metric_hardening_v1",
            "source": "structured_manifest",
            "observer_section_found": False,
            "retries_count": MISSING,
            "recovery_success": MISSING,
            "strategy_shift_detected": MISSING,
            "repeated_strategy_count": MISSING,
            "certification_verdict": MISSING,
            "certification_rank": MISSING,
            "final_score": MISSING,
            "benchmark_score": None,
            "benchmark_score_status": MISSING,
            "loop_risk_proxy": MISSING,
            "metrics_available": False,
        }

    retry_matches = re.findall(r"Regenerating code \(attempt \d+/\d+", observer_text, flags=re.I)
    retries_count = len(retry_matches)

    strategy_shift_patterns = [
        r"\[CRITIC-LLM\] Injecting meta-critique",
        r"\[SWARM\] Activating",
        r"\[VETTORE 1\+2\]",
        r"STRUCTURAL PIVOT",
        r"\[STUDY\] Using past strategy",
    ]
    strategy_shift_detected = any(re.search(p, observer_text, flags=re.I) for p in strategy_shift_patterns)

    cert_matches = re.findall(
        r"\[CERTIFY\].*?(CERTIFIED|FAILED).*?score\s+([0-9]+(?:\.[0-9]+)?)",
        observer_text,
        flags=re.I,
    )
    if cert_matches:
        certification_verdict = cert_matches[-1][0].upper()
        certification_rank: int | str = CERT_RANK.get(certification_verdict, MISSING)
        final_score: float | str = round(float(cert_matches[-1][1]), 3)
    else:
        certification_verdict = MISSING
        certification_rank = MISSING
        final_score = MISSING

    bench_matches = re.findall(
        r"\[BENCHMARK_RUN\].*?:\s+(\d+)/(\d+)\s+passed.*?pass_rate=([0-9]+)%",
        observer_text,
        flags=re.I,
    )
    if bench_matches:
        passed, total, pass_rate = bench_matches[-1]
        if int(total) == 0:
            benchmark_score = None
            benchmark_score_status = UNAVAILABLE
        else:
            benchmark_score = round(float(pass_rate) / 100.0, 3)
            benchmark_score_status = "AVAILABLE"
    else:
        benchmark_score = None
        benchmark_score_status = UNAVAILABLE

    strategy_texts = []
    for match in re.findall(r"Focus:\s*(.+)", observer_text, flags=re.I):
        strategy_texts.append(_normalize_strategy_text(match))
    for match in re.findall(r"gaps:\s*(\[[^\]]+\])", observer_text, flags=re.I):
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
        "schema_version": "d2_2b_metric_hardening_v1",
        "source": "structured_manifest",
        "observer_section_found": True,
        "retries_count": retries_count,
        "recovery_success": recovery_success,
        "strategy_shift_detected": strategy_shift_detected,
        "repeated_strategy_count": repeated_strategy_count,
        "certification_verdict": certification_verdict,
        "certification_rank": certification_rank,
        "final_score": final_score,
        "benchmark_score": benchmark_score,
        "benchmark_score_status": benchmark_score_status,
        "loop_risk_proxy": loop_risk_proxy,
        "metrics_available": True,
    }


def _bias_provenance(arm: dict, mood: dict, signal: dict) -> dict:
    workspace_bias_present = mood.get("workspace_bias_present") is True
    tensions_count = int(signal.get("tensions_trace_count", 0))
    real_workspace_signal = arm["name"] == "ARM_ON" and workspace_bias_present and tensions_count > 0
    fallback_bias_excluded = arm["no_l3"] is True and workspace_bias_present
    if real_workspace_signal:
        workspace_bias_source = "real_workspace_winner"
    elif fallback_bias_excluded:
        workspace_bias_source = "synthetic_ignition_failure_fallback"
    else:
        workspace_bias_source = "not_observed"

    return {
        "schema_version": "d2_2b_metric_hardening_v1",
        "source": "structured_manifest",
        "workspace_bias_present": workspace_bias_present,
        "real_workspace_signal": real_workspace_signal,
        "fallback_bias_excluded": fallback_bias_excluded,
        "workspace_bias_source": workspace_bias_source,
        "dominant_winner": "tensions" if tensions_count > 0 else None,
        "winner_module": "tensions" if tensions_count > 0 else None,
        "ignition_failed": bool(fallback_bias_excluded),
        "fallback_source": "ignition_failure_fallback" if fallback_bias_excluded else None,
        "tensions_trace_count": tensions_count,
        "gwt_bid_trace_count": int(signal.get("gwt_bid_trace_count", 0)),
        "observer_workspace_bias_traj": mood.get("observer_workspace_bias_traj", []),
    }


def _archive_mood_history(target: Path, run_id: str) -> int:
    if not MOOD_HISTORY.exists():
        target.write_text("", encoding="utf-8")
        return 0

    samples = []
    for line in MOOD_HISTORY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        obj["run_id"] = run_id
        samples.append(obj)

    target.write_text(
        "\n".join(json.dumps(s, ensure_ascii=True) for s in samples) + ("\n" if samples else ""),
        encoding="utf-8",
    )
    return len(samples)


def _reset_mood_history() -> None:
    if MOOD_HISTORY.exists():
        MOOD_HISTORY.unlink()


def _cache_hashes_for_sequence(sequence: dict) -> dict:
    hashes = {}
    for topic in _topic_sequence(sequence):
        path = _cache_path(topic)
        if not path.exists():
            raise FileNotFoundError(f"missing cache for {topic!r}: {path}")
        hashes[topic] = json.loads(path.read_text(encoding="utf-8")).get("hash", "?")
    return hashes


def _preflight_cache_hashes() -> dict:
    hashes = {}
    missing = []
    for sequence in TOPIC_SEQUENCES:
        for topic in _topic_sequence(sequence):
            path = _cache_path(topic)
            if not path.exists():
                missing.append((topic, path))
                continue
            hashes[topic] = json.loads(path.read_text(encoding="utf-8")).get("hash", "?")

    if missing:
        lines = ["[D2.2E] missing cached source files; benchmark will not start."]
        for topic, path in missing:
            lines.append(f"  - {topic!r}: {path}")
        lines.append("")
        lines.append("Prefetch missing cache in a separate tracked step, for example:")
        for topic, _path in missing:
            lines.append(f"  python backend/d2_1a_cache_sources.py --topic \"{topic}\"")
        raise SystemExit("\n".join(lines))
    return hashes


def _run_one(sequence: dict, rep: int, arm: dict, run_dir: Path, run_id: str, run_index_global: int) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    manifest_path = run_dir / "manifest.json"
    mood_path = run_dir / "mood_samples.jsonl"
    topic_sequence = _topic_sequence(sequence)

    _reset_mood_history()
    started = time.time()
    started_iso = datetime.now().isoformat()
    print(
        f"\n[{run_id}] starting D2.2E subprocess "
        f"(sequence={sequence['id']}, rep={rep}, arm={arm['name']}, no_l3={arm['no_l3']})..."
    )

    env = os.environ.copy()
    env["D2_CACHED_SOURCES_DIR"] = str(CACHE_DIR)
    env["D2_STRESS_MODE"] = "1"
    env["D2_STRESS_PROFILE"] = "controlled_validation_failure"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("D2_CACHED_SOURCES_PATH", None)

    cmd = [
        sys.executable,
        str(_ROOT / "backend" / "night_runner.py"),
        "--cycles",
        "2",
        "--timeout",
        "60",
        "--pause",
        "0",
        "--api-limit",
        "400",
        "--topic-budget",
        "30",
        "--force-topic-sequence",
        "|".join(topic_sequence),
    ]
    if arm["no_l3"]:
        cmd.append("--no-l3")

    try:
        cp = subprocess.run(
            cmd,
            env=env,
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SUBPROCESS_TIMEOUT,
        )
        exit_code = cp.returncode
        out, err = cp.stdout, cp.stderr
        timeout_hit = False
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        out = exc.stdout or ""
        err = (exc.stderr or "") + f"\n[D2.2E] subprocess TIMEOUT after {SUBPROCESS_TIMEOUT}s"
        timeout_hit = True

    finished = time.time()
    finished_iso = datetime.now().isoformat()

    stdout_log.write_text(out, encoding="utf-8")
    stderr_log.write_text(err, encoding="utf-8")
    combined_text = out + "\n" + err
    markers = _count_markers(combined_text)
    mood_count = _archive_mood_history(mood_path, run_id)
    mood_metrics = _mood_stats(_load_mood_samples(mood_path))
    observer_window, observer_text = _observer_window(combined_text, sequence["observer_topic"])
    behavior_metrics = _behavior_metrics(observer_text, observer_window["found"])
    signal_metrics = _signal_metrics(combined_text)
    bias_provenance = _bias_provenance(arm, mood_metrics, signal_metrics)

    contaminated = (
        markers["ddgs_call_count"] > 0
        or markers["brave_call_count"] > 0
        or markers["playwright_call_count"] > 0
    )
    abort_reason = None
    if contaminated:
        abort_reason = "LIVE_SEARCH_IN_CACHED_MODE"
    elif timeout_hit:
        abort_reason = "SUBPROCESS_TIMEOUT"
    elif exit_code != 0:
        abort_reason = f"NONZERO_EXIT_{exit_code}"
    elif markers["fallback_count"] > 10:
        abort_reason = "FALLBACK_THRESHOLD_EXCEEDED"
        contaminated = True
    elif markers["http_error_count"] > 3:
        abort_reason = "HTTP_ERROR_THRESHOLD_EXCEEDED"
        contaminated = True
    elif markers["force_topic_seq_count"] < 2:
        abort_reason = "FORCE_TOPIC_SEQUENCE_NOT_OBSERVED_TWICE"
    elif markers["stress_injection_count"] == 0:
        abort_reason = "STRESS_INJECTION_NOT_OBSERVED"
    elif markers["cache_hit_map"] < 2:
        abort_reason = "CACHE_MAP_HOOK_NOT_FIRED_BOTH_CYCLES"
    elif markers["cache_hit_aggregate"] < 2:
        abort_reason = "CACHE_AGGREGATE_HOOK_NOT_FIRED_BOTH_CYCLES"
    elif mood_count == 0:
        abort_reason = "MISSING_MOOD_SAMPLES"

    manifest = {
        "d2_version": "D2.2E",
        "planning_commit": PLANNING_COMMIT,
        "run_id": run_id,
        "run_index_global": run_index_global,
        "sequence_id": sequence["id"],
        "rep": rep,
        "arm": arm["name"],
        "arm_no_l3": arm["no_l3"],
        "topic_sequence": topic_sequence,
        "stress_topic": sequence["stress_topic"],
        "observer_topic": sequence["observer_topic"],
        "relative_run_dir": str(run_dir.relative_to(RUNS_ROOT)).replace("\\", "/"),
        "source_mode": "cached_per_topic",
        "cache_dir": str(CACHE_DIR.relative_to(_ROOT)).replace("\\", "/"),
        "cache_hashes": _cache_hashes_for_sequence(sequence),
        "experimental_patch": {
            "file": "backend/cognition/mood_workspace_coupling.py",
            "winner": "tensions",
            "valence_delta": -0.05,
            "arousal_delta": 0.15,
        },
        "metric_hardening": {
            "enabled": True,
            "planning_commit": METRIC_HARDENING_PLANNING_COMMIT,
            "scope": "instrumentation_only",
            "behavior_changes": False,
        },
        "micro_decision_coupling": {
            "enabled": True,
            "planning_commit": PLANNING_COMMIT,
            "target_gate": "reflection_trigger",
            "scope": "reflection_directive_modifier",
            "directive_strengthened_in_d2_2e": False,
            "max_retry_changed": False,
            "certification_threshold_changed": False,
            "scoring_logic_changed": False,
            "winner_bias_changed_in_this_experiment": False,
            "valence_field_changed": False,
            "stress_injection_changed": False,
            "topic_sequence_changed": False,
        },
        "observer_window": observer_window,
        "behavior_metrics": behavior_metrics,
        "bias_provenance": bias_provenance,
        "mood_metrics": mood_metrics,
        "signal_metrics": signal_metrics,
        "decision_coupling_metrics": _decision_coupling_metrics(combined_text),
        "retry_strategy_hash_metrics": _retry_strategy_hash_metrics(observer_text, observer_window["found"]),
        "stress_mode": True,
        "stress_profile": "controlled_validation_failure",
        "stress_injection_observed": markers["stress_injection_count"] > 0,
        "force_topic_seq_observed": markers["force_topic_seq_count"] >= 2,
        "subprocess_exit_code": exit_code,
        "started_at": started_iso,
        "finished_at": finished_iso,
        "duration_seconds": round(finished - started, 1),
        "mood_sample_count": mood_count,
        "contaminated": contaminated,
        "abort_reason": abort_reason,
        **markers,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    print(
        f"[{run_id}] exit={exit_code} duration={manifest['duration_seconds']}s "
        f"seq_obs={manifest['force_topic_seq_observed']} "
        f"stress_obs={manifest['stress_injection_observed']} "
        f"cache_hits=({markers['cache_hit_map']},{markers['cache_hit_aggregate']}) "
        f"mood_n={mood_count} tensions_traces={markers['tensions_bid_trace_count']} "
        f"micro_applied={markers['micro_coupling_applied_count']} "
        f"retry_hash_available={_retry_strategy_hash_metrics(observer_text, observer_window['found'])['retry_hash_available']} "
        f"contam={contaminated} abort={abort_reason}"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abort-on-contam", action="store_true")
    args = parser.parse_args()

    all_cache_hashes = _preflight_cache_hashes()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = RUNS_ROOT / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    expected_runs = len(TOPIC_SEQUENCES) * len(REPLICAS) * len(ARMS)
    print("=" * 70)
    print("D2.2E DECISION EFFECT MEASUREMENT")
    print("=" * 70)
    print(f"Run root:       {run_root}")
    print(f"Planning commit: {PLANNING_COMMIT}")
    print(f"Sequences:      {[s['id'] for s in TOPIC_SEQUENCES]}")
    print(f"Replicas:       {REPLICAS}")
    print(f"Expected runs:  {expected_runs}")
    print("Scope: micro validation only, not D2.2 full")
    print("=" * 70)

    manifests = []
    aborted = False
    run_index = 0
    for sequence in TOPIC_SEQUENCES:
        for rep in REPLICAS:
            for arm in ARMS:
                run_index += 1
                run_id = f"d2_2e_{sequence['id']}_rep{rep:02d}_{arm['name'].lower()}"
                run_dir = run_root / sequence["id"] / f"rep_{rep:02d}" / arm["name"].lower()
                manifest = _run_one(sequence, rep, arm, run_dir, run_id, run_index)
                manifests.append(manifest)
                if args.abort_on_contam and (manifest["contaminated"] or manifest["abort_reason"]):
                    print(f"[D2.2E] ABORT: run failed sanity ({manifest['abort_reason']})")
                    aborted = True
                    break
            if aborted:
                break
        if aborted:
            break

    summary = {
        "d2_version": "D2.2E",
        "planning_commit": PLANNING_COMMIT,
        "started_at": manifests[0]["started_at"] if manifests else None,
        "finished_at": manifests[-1]["finished_at"] if manifests else None,
        "topic_sequences": TOPIC_SEQUENCES,
        "replicas": REPLICAS,
        "arms": [a["name"] for a in ARMS],
        "expected_subprocesses": expected_runs,
        "actual_subprocesses": len(manifests),
        "all_cache_hashes": all_cache_hashes,
        "stress_mode": True,
        "experimental_patch": {
            "file": "backend/cognition/mood_workspace_coupling.py",
            "winner": "tensions",
            "valence_delta": -0.05,
            "arousal_delta": 0.15,
        },
        "metric_hardening": {
            "enabled": True,
            "planning_commit": METRIC_HARDENING_PLANNING_COMMIT,
            "scope": "instrumentation_only",
            "behavior_changes": False,
        },
        "aborted": aborted,
        "manifests": manifests,
    }
    summary_path = run_root / "d2_2e_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print()
    print("=" * 70)
    print(f"Total runs:   {len(manifests)} / {expected_runs}")
    print(f"Contaminated: {sum(1 for m in manifests if m['contaminated'])}")
    print(f"Abort reasons: {[m['abort_reason'] for m in manifests if m['abort_reason']]}")
    print(f"Summary:      {summary_path}")
    print(f"Next: python backend/d2_2e_analyze.py {run_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
