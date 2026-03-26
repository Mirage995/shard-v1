"""
Test the CognitionCore integration points BEFORE implementing.
Questions:
  1. What does relational_context() currently output for a topic?
  2. What tensions are currently detected?
  3. What's missing (world, goal, real self_model data)?
  4. Where exactly should we inject?

This tells us WHAT to add, not just WHERE.
"""
import sys, json, re
from pathlib import Path
from unittest.mock import MagicMock, patch
from collections import defaultdict

sys.path.insert(0, "/test")
_MEM = Path("/test/shard_memory")

# ── Patch heavy dependencies before importing CognitionCore ───────────────────
# shard_db → mock SQLite
mock_conn = MagicMock()
mock_conn.execute.return_value.fetchone.return_value = {
    "total": 94, "cert": 18, "avg": 5.0,
    "topic": "REST API design patterns", "score": 7.5,
    "certified": 0, "timestamp": "2026-03-26T12:00:00"
}
sys.modules["shard_db"] = MagicMock(get_db=lambda: mock_conn, query=lambda *a: [])
sys.modules["graph_rag"] = MagicMock(query_causal_context=lambda t: "")

# Patch the ROOT path inside cognition_core before importing
import cognition_core as cc_mod
cc_mod._ROOT = Path("/test")

# Patch _get_db inside cognition_core
cc_mod._get_db = lambda: mock_conn

from cognition_core import CognitionCore, _detect_tensions

PASS = "[PASS]"
FAIL = "[FAIL]"
errors = []

def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}" + (f" — {detail}" if detail else ""))
        errors.append(label)

# ── 1. Baseline: what does CognitionCore produce TODAY ────────────────────────
print("=" * 60)
print("BASELINE: CognitionCore today (no world/goal)")
print("=" * 60)

core = CognitionCore(
    self_model=None,
    episodic_memory=None,
    strategy_memory=None,
    meta_learning=None,
)

exec_data = core.executive()
print(f"\n  executive(): {exec_data['summary'][:200]}")

# Simulate what relational_context produces
identity = core.query_identity()
experience = core.query_experience("asyncio and async patterns in python")
knowledge = core.query_knowledge("asyncio and async patterns in python")
tensions = _detect_tensions(identity, experience, knowledge, exec_data["anchor"])

print(f"\n  query_identity(): {identity}")
print(f"\n  query_experience(): attempts={experience.get('attempt_count')} err={experience.get('error','none')}")
print(f"\n  query_knowledge(): complexity={knowledge.get('complexity_level')} err={knowledge.get('error','none')}")
print(f"\n  tensions today: {tensions if tensions else '(none)'}")

print("\n  MISSING from relational_context today:")
print("    - World relevance of the topic")
print("    - Active goal and its alignment with the topic")
print("    - Real self_model data (momentum, blind_spots from experiment history)")
print("    - Tension: 'topic is high-relevance but SHARD cert_rate in this domain is low'")
print("    - Tension: 'active goal says study X, this topic has N% alignment'")

# ── 2. Simulate what NEW relational_context SHOULD produce ────────────────────
print("\n" + "=" * 60)
print("SIMULATION: What relational_context SHOULD produce after integration")
print("=" * 60)

# Load our real new models
from self_model import SelfModel
from world_model import WorldModel
from goal_engine import GoalEngine, GoalStorage

import self_model as _sm_mod, world_model as _wm_mod, goal_engine as _ge_mod
_sm_mod._MEMORY = _MEM
_sm_mod._SELF_MODEL_PATH = _MEM / "self_model.json"
_wm_mod._MEMORY = _MEM
_wm_mod._WORLD_MODEL_PATH = _MEM / "world_model.json"
_ge_mod._MEMORY = _MEM
_ge_mod._GOALS_PATH = _MEM / "goals.json"

sm = SelfModel.load_or_build()
wm = WorldModel.load_or_default()
ge = GoalEngine(GoalStorage())
goal = ge.autonomous_generate()

TOPIC = "asyncio and async patterns in python"

# World signal
relevance = wm.relevance(TOPIC)
domain = wm.domain_of(TOPIC)

# Goal signal
goal_alignment = goal.alignment_score(TOPIC) if goal else 0.0
goal_title = goal.title if goal else "none"

print(f"\n  Topic: '{TOPIC}'")
print(f"\n  [NEW] World signal:")
print(f"    relevance = {relevance:.0%}  domain = {domain}")

print(f"\n  [NEW] Goal signal:")
print(f"    active_goal = '{goal_title}'")
print(f"    alignment   = {goal_alignment:.2f}")

print(f"\n  [NEW] Self model signal:")
print(f"    momentum    = {sm.momentum}")
print(f"    blind_spots = {sm.blind_spots[:3]}")
print(f"    cert_rate   = {sm.certification_rate:.0%}")

# New tensions
new_tensions = []

if relevance > 0.7 and sm.certification_rate < 0.25:
    new_tensions.append(
        f"Vettore 4 (Mondo->Identità): topic ad alta rilevanza mondiale ({relevance:.0%}) "
        f"ma cert_rate SHARD = {sm.certification_rate:.0%} — gap critico da colmare"
    )

if goal_alignment > 0.3:
    new_tensions.append(
        f"Vettore 5 (Goal->Topic): topic allineato al goal attivo '{goal_title}' "
        f"(alignment={goal_alignment:.0%}) — studiarlo avanza il goal"
    )
elif goal_alignment == 0 and goal:
    new_tensions.append(
        f"Vettore 5 (Goal->Topic): topic NON allineato al goal '{goal_title}' "
        f"— valuta se questo studio è prioritario"
    )

if sm.momentum == "stagnating":
    new_tensions.append(
        "Vettore 6 (Momentum): SHARD in stagnazione — considera topic più fondamentali"
    )

print(f"\n  [NEW] Tensions from world+goal:")
if new_tensions:
    for t in new_tensions: print(f"    >> {t}")
else:
    print("    (none for this topic/state)")

# ── 3. Verify the injection points are correct ────────────────────────────────
print("\n" + "=" * 60)
print("INJECTION POINTS CHECK")
print("=" * 60)

check("query_world() should return relevance + domain",
      relevance > 0 and domain != "unknown", f"rel={relevance} dom={domain}")
check("query_goal() should return active goal",
      goal is not None, str(goal.title if goal else "None"))
check("goal alignment is computable",
      isinstance(goal_alignment, float), str(goal_alignment))
check("new tensions are non-empty for high-relevance topic",
      len(new_tensions) > 0, str(new_tensions))
check("self_model has real data",
      sm.total_experiments > 0 and sm.certification_rate > 0)
check("world_model relevance is calibrated",
      0.5 < relevance < 1.0, str(relevance))

# ── Final report ──────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("WHAT TO ADD TO cognition_core.py")
print("=" * 60)
print("""
1. query_world(topic) -> Dict
   Uses backend/world_model.py
   Returns: relevance, domain, is_known, priority_rank

2. query_goal(topic) -> Dict
   Uses backend/goal_engine.py
   Returns: active_goal_title, alignment_score, goal_progress, goal_type

3. query_real_identity() -> Dict  (augments existing query_identity)
   Uses backend/self_model.py (our new one)
   Returns: momentum, blind_spots, quarantine_candidates, real_cert_rate

4. _detect_tensions() — 3 new tension types:
   Vettore 4: high world relevance + low SHARD cert_rate in domain
   Vettore 5: topic alignment (or misalignment) with active goal
   Vettore 6: momentum stagnation signal

5. relational_context() — include world + goal + real identity sections
   Target: still <= 500 tokens total
""")

if not errors:
    print("  ALL CHECKS PASSED — safe to implement")
else:
    print(f"  {len(errors)} issues: {errors}")
    sys.exit(1)
