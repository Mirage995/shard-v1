"""gwt_mood_microtest.py -- Verify mood_score actually moves workspace bids/winners.

Bypasses the full SHARD pipeline. Builds proposals matching the real
relational_context() pattern, then runs the arbiter 3 times with
mood_score in {0.0, -0.8, +0.8}, FeedbackField disabled, and prints:

  1. Per-block bid breakdown for each mood value
  2. Bid sensitivity (delta vs neutral) per block_type
  3. Winner distribution across the 3 modes

Decision rules (from GPT-5.5 review):
  - Esito A: winners shift between modes -> GWT lever is alive (next: Fix C action policy).
  - Esito B: bids shift but winners don't -> calibration issue (base_salience dominates).
  - Esito C: valence stays 1.0 -> bug in propagation or block_type mismatch.

Usage:
    python backend/gwt_mood_microtest.py
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "backend"))

from backend.cognition.workspace_arbiter import (
    WorkspaceArbiter,
    WorkspaceProposal,
    ValenceField,
)


# Snapshot of real proposals from CognitionCore.relational_context() with
# salience values copied from cognition_core.py call sites.
def build_proposals():
    # signature: WorkspaceProposal(module_name, content, base_salience, topic_affinity, block_type)
    return [
        WorkspaceProposal("identity",      "id_text",      0.70, 1.0, "identity"),
        WorkspaceProposal("experience",    "exp_text",     0.80, 1.0, "experience"),
        WorkspaceProposal("knowledge",     "know_text",    0.60, 1.0, "knowledge"),
        WorkspaceProposal("strategy",      "strat_text",   0.75, 1.0, "knowledge"),
        WorkspaceProposal("world",         "world_text",   0.55, 1.0, "world"),
        WorkspaceProposal("goal",          "goal_text",    0.65, 1.0, "goal"),
        WorkspaceProposal("real_identity", "real_id_text", 0.60, 1.0, "real_identity"),
        WorkspaceProposal("desire",        "desire_text",  0.65, 1.0, "desire"),
        WorkspaceProposal("tensions",      "tens_text",    0.85, 1.0, "behavior_directive"),
    ]


def run_mode(mood_score: float):
    arb = WorkspaceArbiter(
        max_tokens=500,
        ignition_threshold=0.4,
        enable_feedback=False,   # isolate ValenceField
    )
    for p in build_proposals():
        arb.add_proposal(p)
    selected = arb.run_competition(mood_score)
    return selected, arb._proposals


def fmt_bid(p):
    vmod = ValenceField.mod(p.block_type, 0.0)  # placeholder
    return f"{p.module_name:<14} block={p.block_type:<20} bid={p.computed_bid:.3f}"


def main():
    print("=" * 78)
    print("GWT MOOD MICRO-TEST -- ValenceField sensitivity check")
    print("=" * 78)
    print()
    print("Configuration: feedback disabled, ignition_threshold=0.4, max_tokens=500")
    print()

    # ── Run 3 modes ──────────────────────────────────────────────────────────
    runs = {}
    for label, mood in [("neutral", 0.0), ("forced_neg", -0.8), ("forced_pos", +0.8)]:
        selected, all_props = run_mode(mood)
        runs[label] = {
            "mood":      mood,
            "selected":  selected,
            "proposals": all_props,
        }
        print(f"--- mode={label}  mood_score={mood:+.2f} ---")
        for p in sorted(all_props, key=lambda x: x.computed_bid, reverse=True):
            mark = "[SEL]" if p in selected else "     "
            vmod = ValenceField.mod(p.block_type, mood)
            print(f"  {mark}  module={p.module_name:<14} block={p.block_type:<20} "
                  f"base={p.base_salience:.2f} val={vmod:.2f} aff={p.topic_affinity:.2f} "
                  f"-> bid={p.computed_bid:.3f}")
        print(f"  WINNERS: {[p.module_name for p in selected]}")
        print()

    # ── Bid sensitivity table ────────────────────────────────────────────────
    print("=" * 78)
    print("BID SENSITIVITY -- delta vs neutral")
    print("=" * 78)
    neut = {p.module_name: p.computed_bid for p in runs["neutral"]["proposals"]}
    neg  = {p.module_name: p.computed_bid for p in runs["forced_neg"]["proposals"]}
    pos  = {p.module_name: p.computed_bid for p in runs["forced_pos"]["proposals"]}
    print(f"  {'module':<16} {'block_type':<22} {'neutral':>9} {'neg(-0.8)':>11} {'pos(+0.8)':>11} {'d_neg':>8} {'d_pos':>8}")
    for name in sorted(neut.keys()):
        # find block_type from neutral run
        bt = next((p.block_type for p in runs["neutral"]["proposals"] if p.module_name == name), "?")
        bn, bg, bp = neut[name], neg[name], pos[name]
        dn, dp = bg - bn, bp - bn
        flag = ""
        if abs(dn) < 1e-6 and abs(dp) < 1e-6:
            flag = "  <-- INERT"
        print(f"  {name:<16} {bt:<22} {bn:>9.3f} {bg:>11.3f} {bp:>11.3f} {dn:>+8.3f} {dp:>+8.3f}{flag}")
    print()

    # ── Winner distribution ──────────────────────────────────────────────────
    print("=" * 78)
    print("WINNER DISTRIBUTION")
    print("=" * 78)
    print(f"  {'mode':<14} {'winners':<60}")
    for label, info in runs.items():
        winners = ", ".join(p.module_name for p in info["selected"])
        print(f"  {label:<14} [{winners}]")
    print()

    # ── Diagnosis ────────────────────────────────────────────────────────────
    print("=" * 78)
    print("DIAGNOSIS")
    print("=" * 78)
    w_neut = set(p.module_name for p in runs["neutral"]["selected"])
    w_neg  = set(p.module_name for p in runs["forced_neg"]["selected"])
    w_pos  = set(p.module_name for p in runs["forced_pos"]["selected"])

    bid_changed = any(abs(neg[k] - neut[k]) > 1e-6 or abs(pos[k] - neut[k]) > 1e-6
                      for k in neut.keys())
    winner_changed = (w_neut != w_neg) or (w_neut != w_pos) or (w_neg != w_pos)

    if not bid_changed:
        print("  ESITO C: bids identical across modes -> ValenceField propagation broken.")
    elif winner_changed:
        print("  ESITO A: winners shift between modes -> GWT lever IS ALIVE.")
        print("           Next step: verify outcome causality (Fix C: winner -> action policy).")
    else:
        print("  ESITO B: bids move but winners don't -> calibration issue.")
        print("           ValenceField receives mood but base_salience/threshold dominate.")
        print("           Tune: increase valence multipliers, lower ignition_threshold,")
        print("           or normalize base_salience.")
    print()


if __name__ == "__main__":
    main()
