"""
Final test: does the updated CognitionCore actually produce richer output?
Tests query_world, query_goal, query_real_identity, and the new tensions.
"""
import sys, json
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, "/test")
_MEM = Path("/test/shard_memory")

# Patch deps
mock_conn = MagicMock()
mock_conn.execute.return_value.fetchone.return_value = {
    "total": 94, "cert": 18, "avg": 5.0,
    "topic": "REST API design patterns", "score": 7.5,
    "certified": 0, "timestamp": "2026-03-26T12:00:00"
}
sys.modules["shard_db"]  = MagicMock(get_db=lambda: mock_conn, query=lambda *a: [])
sys.modules["graph_rag"] = MagicMock(query_causal_context=lambda t: "")

import cognition_core as cc_mod
cc_mod._ROOT = Path("/test")
cc_mod._get_db = lambda: mock_conn

# Patch self_model + world_model + goal_engine paths
import self_model as _sm, world_model as _wm, goal_engine as _ge
_sm._MEMORY = _MEM;  _sm._SELF_MODEL_PATH = _MEM / "self_model.json"
_wm._MEMORY = _MEM;  _wm._WORLD_MODEL_PATH = _MEM / "world_model.json"
_ge._MEMORY = _MEM;  _ge._GOALS_PATH = _MEM / "goals.json"

from cognition_core import CognitionCore, _detect_tensions

PASS, FAIL = "[PASS]", "[FAIL]"
errors = []
def check(label, cond, detail=""):
    if cond: print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}" + (f" — {detail}" if detail else ""))
        errors.append(label)

core = CognitionCore()

# Pre-create autonomous goal so goals.json exists for query_goal()
from goal_engine import GoalEngine, GoalStorage
_ge_tmp = GoalEngine(GoalStorage())
_ge_tmp.autonomous_generate()

# ── query_world ────────────────────────────────────────────────────────────────
print("=" * 60)
print("TEST: query_world()")
print("=" * 60)
w = core.query_world("asyncio and async patterns in python")
print(f"  {w}")
check("returns relevance",  isinstance(w.get("relevance"), float), str(w.get("relevance")))
check("relevance > 0.8 for asyncio", w.get("relevance", 0) > 0.8)
check("domain = python",    w.get("domain") == "python", w.get("domain"))
check("no error",           "error" not in w)

# ── query_goal ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST: query_goal()")
print("=" * 60)
g = core.query_goal("algorithm complexity and performance optimization")
print(f"  {g}")
check("returns active_goal",  g.get("active_goal") is not None, str(g.get("active_goal")))
check("alignment > 0 for matching topic", g.get("alignment", 0) > 0)
check("goal_type = autonomous", g.get("goal_type") == "autonomous")
check("no error",              "error" not in g)

# ── query_real_identity ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST: query_real_identity()")
print("=" * 60)
ri = core.query_real_identity()
print(f"  momentum={ri.get('momentum')}  cert_rate={ri.get('real_cert_rate')}  blind_spots={ri.get('blind_spots',[][:2])}")
check("has momentum",      ri.get("momentum") in ("stable","accelerating","stagnating","early","unknown"))
check("has real_cert_rate", ri.get("real_cert_rate", -1) >= 0)
check("has blind_spots",   isinstance(ri.get("blind_spots"), list))
check("has prompt_fragment", len(ri.get("prompt_fragment","")) > 50)
check("no error",          "error" not in ri)

# ── _detect_tensions with new vettori ──────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST: _detect_tensions() — Vettori 4/5/6")
print("=" * 60)
exec_data = core.executive()
tensions = _detect_tensions(
    identity={}, experience={}, knowledge={},
    anchor=exec_data["anchor"],
    world={"relevance": 0.95, "domain": "python"},
    goal={"active_goal": "master: algorithm complexity", "alignment": 0.6},
    real_identity={"momentum": "stagnating", "real_cert_rate": 0.19},
)
print(f"  {len(tensions)} tensions detected:")
for t in tensions: print(f"    >> {t[:90]}")

check("Vettore 4 detected (high relevance + low cert)", any("Vettore 4" in t for t in tensions))
check("Vettore 5 detected (goal alignment)",            any("Vettore 5" in t for t in tensions))
check("Vettore 6 detected (momentum stagnation)",       any("Vettore 6" in t for t in tensions))

# ── relational_context() — full output ────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST: relational_context() — full output")
print("=" * 60)
ctx = core.relational_context("asyncio and async patterns in python")
print(ctx)
print()
check("contains Mondo section",       "Mondo:" in ctx)
check("contains Goal section",        "Goal:" in ctx)
check("contains Identità reale",      "Identità reale:" in ctx)
check("contains TENSIONI",            "TENSIONI" in ctx)
check("under 600 tokens (~2400 chars)", len(ctx) < 2400, f"len={len(ctx)}")

# ── FINAL ─────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if not errors:
    print(f"  ALL TESTS PASSED — CognitionCore integration complete")
    print(f"\n  relational_context now includes:")
    print(f"    Layer W — World model (relevance, domain)")
    print(f"    Layer G — Goal (active goal, alignment %)")
    print(f"    Layer R — Real identity (momentum, blind spots)")
    print(f"    Vettori 4/5/6 — 3 new tension types")
else:
    print(f"  {len(errors)} FAILURES: {errors}")
    sys.exit(1)
