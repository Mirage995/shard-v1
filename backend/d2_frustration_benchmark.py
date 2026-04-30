"""d2_frustration_benchmark.py -- GWT under stress.

D2 Frustration Benchmark
========================

Purpose:
    Measure whether SHARD's GWT relational_context improves recovery
    dynamics under stress, not generic certify rate.

H0:
    GWT_ON makes no measurable difference in stress/retry regime
    compared to the same SHARD pipeline with relational_context
    disabled.

H1 (primary):
    GWT_ON improves recovery dynamics under stress. Reject H0 if at
    least ONE primary criterion holds:

    (a) SERR_A < SERR_B by >= 15 percentage points
        Lower same-error perseveration after failure.

    (b) SSR_A > SSR_B by >= 15 percentage points
        Higher strategy shift rate after failure.

    (c) TNA_A < TNA_B by >= 1 attempt
        Faster time to novel approach after initial failure.

Mechanism confirmation (NOT sufficient alone for H1):
    (d) ARM_A crosses mood_score <= -0.3 AND workspace winners shift
        toward experience / behavior_directive, with non-zero
        workspace_bias. Confirms GWT activation under stress but does
        not by itself prove operational advantage.

Secondary metrics:
    cert_rate, avg_score, recovery score delta, mood trajectory,
    workspace winner distribution.

Design (per GPT-5.5 review):
    - 3 topics (hard / medium-hard / medium) so we don't observe a
      ceiling effect in either direction.
    - Arms differ ONLY in `no_l3`. `use_affective_layer=True` for both
      so we are not lobotomizing 5 systems at once.
    - Paired interleaving: AB AB AB (not AAA BBB) reduces temporal
      drift in API/provider/cache between arms.
    - Identical shard_memory baseline restored before EVERY arm run.
    - mood_history.jsonl is moved aside per (session, arm) so each run
      writes its own clean trajectory file.

Usage:
    python backend/d2_frustration_benchmark.py
"""
import asyncio
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

# ── Topics: variable difficulty so we get readable signal ─────────────────────
TOPICS = [
    {"topic": "clean architecture python",         "difficulty": "hard"},
    {"topic": "sql injection prevention python",   "difficulty": "medium-hard"},
    {"topic": "python OOP design patterns",        "difficulty": "medium"},
]

TOPIC_BUDGET      = 30
SESSION_API_LIMIT = 200
PAIRED_SESSIONS   = 3   # AB AB AB — extend to 5 only if signal is noisy but promising

_MEM            = _ROOT / "shard_memory"
SNAPSHOT_DIR    = _ROOT / "shard_workspace" / "d2_baseline_snapshot"
RESULTS_PATH    = _ROOT / "shard_workspace" / "d2_frustration_results.json"
MOOD_HIST_FILE  = _MEM / "mood_history.jsonl"
MOOD_HIST_DIR   = _ROOT / "shard_workspace" / "d2_mood_history"

RANDOM_SEED = 4242  # logged in output for reproducibility


# ── Snapshot / Restore ────────────────────────────────────────────────────────

def take_snapshot() -> None:
    if SNAPSHOT_DIR.exists():
        shutil.rmtree(SNAPSHOT_DIR)
    shutil.copytree(_MEM, SNAPSHOT_DIR)
    print(f"[D2 SNAPSHOT] Saved baseline -> {SNAPSHOT_DIR}")


def restore_snapshot() -> None:
    """Full restore. Must run from a fresh process so ChromaDB handles are released."""
    if not SNAPSHOT_DIR.exists():
        raise RuntimeError("No D2 baseline snapshot. Take one first.")
    try:
        for mod_name in ("shard_db", "backend.shard_db"):
            if mod_name in sys.modules:
                sys.modules[mod_name].close()
                break
    except Exception:
        pass
    shutil.rmtree(_MEM)
    shutil.copytree(SNAPSHOT_DIR, _MEM)
    print(f"[D2 RESTORE] Baseline state restored from {SNAPSHOT_DIR}")


def archive_mood_history(label: str) -> Path:
    """Move the current mood_history.jsonl to archive dir under label, return new path.

    Each (session, arm) gets its own clean mood trajectory file. Returns the
    archived path; the live mood_history.jsonl is removed so the next run
    starts fresh.
    """
    MOOD_HIST_DIR.mkdir(parents=True, exist_ok=True)
    archived = MOOD_HIST_DIR / f"{label}.jsonl"
    if MOOD_HIST_FILE.exists():
        shutil.move(str(MOOD_HIST_FILE), str(archived))
        print(f"[D2 MOOD] Archived {len(archived.read_text(encoding='utf-8').splitlines())} samples -> {archived.name}")
    else:
        archived.write_text("", encoding="utf-8")
    return archived


# ── Per-topic runner ──────────────────────────────────────────────────────────

async def run_topic(topic: str, no_l3: bool) -> dict:
    """Run one topic with use_affective_layer=True; only no_l3 differs across arms."""
    from night_runner import NightRunner

    runner = NightRunner(
        cycles=1,
        timeout=30,
        pause=0,
        api_limit=SESSION_API_LIMIT,
        topic_budget=TOPIC_BUDGET,
        forced_topic=topic,
        use_affective_layer=True,   # SAME for both arms
        no_l3=no_l3,                # ONLY this differs
    )
    t0 = time.time()
    try:
        await runner.run()
    except Exception as exc:
        print(f"  ERROR on '{topic}': {exc}")
        return {
            "score":         0.0,
            "certified":     False,
            "llm_calls":     0,
            "time_seconds":  round(time.time() - t0, 1),
            "error":         str(exc)[:200],
        }
    elapsed = round(time.time() - t0, 1)
    cycle = runner.session_data[-1] if runner.session_data else {}
    return {
        "score":         float(cycle.get("score", 0.0)),
        "certified":     bool(cycle.get("certified", False)),
        "llm_calls":     int(cycle.get("topic_llm_calls", 0)),
        "time_seconds":  elapsed,
    }


# ── Session runner (one arm of one paired session) ────────────────────────────

async def run_session(session_idx: int, arm_label: str, no_l3: bool) -> dict:
    print(f"\n  --- SESSION {session_idx} [{arm_label}] no_l3={no_l3} ---")
    topic_results = []
    t0 = time.time()
    for entry in TOPICS:
        topic = entry["topic"]
        result = await run_topic(topic, no_l3)
        topic_results.append({
            "topic":      topic,
            "difficulty": entry["difficulty"],
            "certified":  result["certified"],
            "score":      result["score"],
            "llm_calls":  result["llm_calls"],
            "time_seconds": result.get("time_seconds", 0.0),
            "error":      result.get("error"),
        })
        cert_str = "CERT" if result["certified"] else "FAIL"
        print(f"    {cert_str} [{topic[:40]}] score={result['score']:.1f} llm={result['llm_calls']}")

    n = len(topic_results)
    cert_rate = sum(1 for r in topic_results if r["certified"]) / n if n else 0.0
    avg_score = sum(r["score"]     for r in topic_results) / n if n else 0.0
    avg_llm   = sum(r["llm_calls"] for r in topic_results) / n if n else 0.0

    return {
        "session":       session_idx,
        "arm":           arm_label,
        "no_l3":         no_l3,
        "cert_rate":     round(cert_rate, 4),
        "avg_score":     round(avg_score, 2),
        "avg_llm_calls": round(avg_llm, 1),
        "total_seconds": round(time.time() - t0, 1),
        "topics":        topic_results,
    }


def _save_partial(data: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps({**data, "partial": True}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Main with paired interleaving ─────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("D2 FRUSTRATION BENCHMARK -- GWT under stress")
    print("=" * 70)
    print(f"Topics:         {[t['topic'] for t in TOPICS]}")
    print(f"Paired sessions: {PAIRED_SESSIONS}")
    print(f"Random seed:    {RANDOM_SEED}")
    print(f"Arm A: use_affective_layer=True, no_l3=False  (GWT_ON)")
    print(f"Arm B: use_affective_layer=True, no_l3=True   (GWT_OFF, only relational_context disabled)")
    print("=" * 70)

    # Resume detection ── if results exist with all sessions, do nothing;
    # if partial with arm_a in pair P done but not arm_b, resume there.
    data: dict
    if RESULTS_PATH.exists():
        try:
            data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
            done_pairs = data.get("paired_runs", [])
            print(f"[D2 RESUME] Found {len(done_pairs)} paired runs in results")
            if len(done_pairs) >= PAIRED_SESSIONS and all(
                p.get("arm_a") and p.get("arm_b") for p in done_pairs
            ):
                print("[D2 RESUME] All paired runs complete — nothing to do")
                _print_summary(data)
                return
            # Find the resume point: first pair missing arm_b
            for i, p in enumerate(done_pairs):
                if p.get("arm_a") and not p.get("arm_b"):
                    print(f"[D2 RESUME] Resuming at pair {i+1} ARM_B (after fresh process restart)")
                    restore_snapshot()
                    arm_b = await run_session(i + 1, "ARM_B_GWT_OFF", no_l3=True)
                    archived_b = archive_mood_history(f"pair{i+1}_arm_b")
                    arm_b["mood_history_file"] = archived_b.name
                    p["arm_b"] = arm_b
                    _save_partial(data)
                    print(f"  -> Pair {i+1} complete. Re-run script for next pair.")
                    return
            # Partial pair list — continue from len(done_pairs)
        except Exception as e:
            print(f"[D2 RESUME] Could not resume: {e} — starting fresh")
            data = None  # type: ignore
    else:
        data = None  # type: ignore

    if not isinstance(data, dict):
        data = {
            "timestamp":   datetime.now().isoformat(),
            "config": {
                "topics":           [t["topic"] for t in TOPICS],
                "topic_budget":     TOPIC_BUDGET,
                "api_limit":        SESSION_API_LIMIT,
                "paired_sessions":  PAIRED_SESSIONS,
                "random_seed":      RANDOM_SEED,
                "arm_a":            {"use_affective_layer": True, "no_l3": False},
                "arm_b":            {"use_affective_layer": True, "no_l3": True},
            },
            "hypothesis": {
                "H0": "GWT_ON makes no measurable difference in stress regime",
                "H1_primary": [
                    "(a) SERR_A < SERR_B by >= 15pp",
                    "(b) SSR_A  > SSR_B by >= 15pp",
                    "(c) TNA_A  < TNA_B by >= 1 attempt",
                ],
                "mechanism_check": "(d) ARM_A: mood_score <= -0.3 AND winners shift to experience/behavior_directive AND workspace_bias != 0",
            },
            "paired_runs": [],
        }

    # Take baseline if not present
    if not SNAPSHOT_DIR.exists():
        # Archive any existing mood_history before snapshot
        if MOOD_HIST_FILE.exists():
            archive_mood_history("pre_d2_baseline")
        take_snapshot()

    # Run pair_idx starting from where we left off
    start_pair = len(data["paired_runs"])
    for pair_idx in range(start_pair, PAIRED_SESSIONS):
        print(f"\n=== PAIR {pair_idx + 1} / {PAIRED_SESSIONS} ===")
        pair = {"pair": pair_idx + 1, "arm_a": None, "arm_b": None}
        data["paired_runs"].append(pair)

        # ARM_A first in this pair (paired interleaving — restore between arms)
        restore_snapshot()
        arm_a = await run_session(pair_idx + 1, "ARM_A_GWT_ON", no_l3=False)
        archived_a = archive_mood_history(f"pair{pair_idx+1}_arm_a")
        arm_a["mood_history_file"] = archived_a.name
        pair["arm_a"] = arm_a
        _save_partial(data)

        # ARM_B requires fresh process so ChromaDB handles release.
        # Exit gracefully: caller must re-run the script. Resume detection
        # at the top of main() will pick up the dangling pair.
        print()
        print("=" * 70)
        print(f"[D2] Pair {pair_idx + 1} ARM_A done. Snapshot still valid.")
        print(f"[D2] Re-run the script to execute ARM_B for this pair.")
        print("=" * 70)
        data.pop("partial", None)
        RESULTS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return

    # Final write
    data.pop("partial", None)
    RESULTS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _print_summary(data)


def _print_summary(data: dict) -> None:
    print("\n" + "=" * 70)
    print("D2 FRUSTRATION BENCHMARK -- raw summary (full analysis: d2_analyze.py)")
    print("=" * 70)
    for p in data.get("paired_runs", []):
        print(f"\n  PAIR {p['pair']}:")
        for arm_key in ("arm_a", "arm_b"):
            arm = p.get(arm_key)
            if not arm:
                print(f"    {arm_key.upper()}: <pending>")
                continue
            print(f"    {arm_key.upper()} [{arm['arm']}]: cert={arm['cert_rate']:.1%}  score={arm['avg_score']:.2f}  llm={arm['avg_llm_calls']:.1f}  ({arm['total_seconds']:.0f}s)")
    print(f"\n[D2] Results:           {RESULTS_PATH}")
    print(f"[D2] Mood histories:    {MOOD_HIST_DIR}")
    print(f"[D2] Run d2_analyze.py for SERR / SSR / TNA / mechanism check.")


if __name__ == "__main__":
    asyncio.run(main())
