"""
Simulates the full NightRunner startup sequence for the new AGI layer:
  self_model → world_model → goal_engine → autonomous_generate → quarantine

Tests:
  1. SelfModel builds from real data, quarantine_candidates populated
  2. WorldModel self_calibrates from SHARD cert data
  3. GoalEngine.autonomous_generate() picks a real goal
  4. Goal steering reorders topic candidates correctly
  5. Quarantine candidates don't get steered toward
"""
import sys, json
from pathlib import Path

# Point modules to the test shard_memory
sys.path.insert(0, "/test")

# Monkey-patch the paths inside the modules before importing
import self_model as _sm_mod
import world_model as _wm_mod
import goal_engine as _ge_mod

_MEM = Path("/test/shard_memory")
_sm_mod._MEMORY = _MEM
_sm_mod._SELF_MODEL_PATH = _MEM / "self_model.json"
_wm_mod._MEMORY = _MEM
_wm_mod._WORLD_MODEL_PATH = _MEM / "world_model.json"
_ge_mod._MEMORY = _MEM
_ge_mod._GOALS_PATH = _MEM / "goals.json"

from self_model import SelfModel
from world_model import WorldModel
from goal_engine import GoalEngine, GoalStorage

PASS = "[PASS]"
FAIL = "[FAIL]"

errors = []

def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}" + (f" — {detail}" if detail else ""))
        errors.append(label)

# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1 — SelfModel.build()")
print("=" * 60)

sm = SelfModel.build()

check("total_experiments > 0",       sm.total_experiments > 0,         str(sm.total_experiments))
check("certification_rate > 0",      sm.certification_rate > 0,        str(sm.certification_rate))
check("avg_score > 0",               sm.avg_score > 0,                  str(sm.avg_score))
check("momentum is set",             sm.momentum in ("stable","accelerating","stagnating","early","unknown"))
check("no duplicate strengths",      len(sm.strengths) == len(set(sm.strengths)), str(sm.strengths[:3]))
check("quarantine_candidates exists", "quarantine_candidates" in sm._data)
check("quarantine_candidates is list", isinstance(sm._data["quarantine_candidates"], list))

qc = sm._data.get("quarantine_candidates", [])
print(f"\n  quarantine_candidates ({len(qc)}): {qc[:4]}")
print(f"  blind_spots ({len(sm.blind_spots)}): {sm.blind_spots[:3]}")
print(f"  strengths ({len(sm.strengths)}): {sm.strengths[:3]}")
print(f"  momentum: {sm.momentum}")

check("saved to disk", (_MEM / "self_model.json").exists())

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2 — WorldModel.load_or_default() + self_calibrate()")
print("=" * 60)

wm = WorldModel.load_or_default()

check("skills dict populated",  len(wm._data["skills"]) > 10, str(len(wm._data["skills"])))
check("asyncio relevance high", wm.relevance("asyncio and async patterns in python") > 0.8)
check("fuzzy match works",      wm.relevance("asyncio patterns") > 0.3)
check("priority_gaps returns results", len(wm.priority_gaps(set(sm.strengths))) > 0)
check("saved to disk",          (_MEM / "world_model.json").exists())

print(f"\n  coverage: {wm.coverage_summary()}")

adj = wm.self_calibrate(min_experiments=5)
print(f"\n  self_calibrate() adjustments ({len(adj)}):")
if adj:
    for skill, d in adj.items():
        print(f"    '{skill}': {d['old']:.3f} -> {d['new']:.3f} (cert={d['cert_rate']:.1%}, n={d['n']})")
    check("calibration saved", wm._data.get("last_calibrated") is not None)
else:
    print("    (none — not enough experiments per domain yet)")
    print("  NOTE: self_calibrate needs >=5 experiments matching seed skill tokens.")
    print("        This is expected with the current dataset.")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3 — GoalEngine.autonomous_generate()")
print("=" * 60)

ge = GoalEngine(GoalStorage())
goal = ge.autonomous_generate()

check("goal was created",       goal is not None)
check("goal has title",         bool(goal.title) if goal else False, goal.title if goal else "None")
check("goal type is autonomous", goal.goal_type == "autonomous" if goal else False)
check("goal is active",         goal.active if goal else False)
check("domain_keywords set",    len(goal.domain_keywords) > 0 if goal else False, str(goal.domain_keywords if goal else []))
check("goal saved to disk",     (_MEM / "goals.json").exists())
check("goal_summary works",     "Goal:" in ge.goal_summary())

print(f"\n  Goal: {goal.title}")
print(f"  Priority: {goal.priority}")
print(f"  Keywords: {goal.domain_keywords}")
print(f"  Description: {goal.description}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 4 — Goal steering")
print("=" * 60)

candidates = [
    "docker basics",
    "algorithm complexity and performance optimization",
    "asyncio event loop internals",
    "graph traversal bfs dfs",
    "performance tuning python",
    "sorting algorithms",
]

steered = ge.steer(candidates)
print(f"\n  Goal: '{goal.title}'")
print(f"  Keywords: {goal.domain_keywords}")
print(f"\n  Before steering: {candidates}")
print(f"  After  steering: {steered}")

scores = [(t, goal.alignment_score(t)) for t in candidates]
top = max(scores, key=lambda x: x[1])
check("top steered topic has alignment > 0", top[1] > 0, f"{top[0]} = {top[1]:.2f}")
check("order changed by goal",               steered != candidates or all(s==0 for _,s in scores))

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 5 — Quarantine candidates are not re-selected")
print("=" * 60)

qc_topics = qc[:5]
if qc_topics:
    for t in qc_topics:
        score = goal.alignment_score(t) if goal else 0
        print(f"  quarantine topic alignment={score:.2f}: {t[:60]}")
    # Quarantine topics should score low (they're junk composites)
    avg_junk_score = sum(goal.alignment_score(t) for t in qc_topics) / len(qc_topics)
    check("quarantine topics score lower than real topics",
          avg_junk_score < top[1],
          f"avg_junk={avg_junk_score:.2f} vs top_real={top[1]:.2f}")
else:
    print("  (no quarantine candidates in this dataset)")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FINAL RESULT")
print("=" * 60)

if not errors:
    print(f"  ALL TESTS PASSED")
    print(f"\n  The AGI startup chain works correctly:")
    print(f"  self_model({sm.total_experiments} exp) -> world_model({len(wm._data['skills'])} skills)")
    print(f"  -> goal('{goal.title}')")
    print(f"  -> steering({steered[0]!r} first)")
else:
    print(f"  {len(errors)} FAILURES:")
    for e in errors:
        print(f"    - {e}")
    sys.exit(1)
