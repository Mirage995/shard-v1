"""gwt_ab_test.py -- A/B test GWT impact on SHARD performance.

Conditions:
  A (GWT ON):  use_affective_layer=True  — Workspace Arbiter + ContextArbiter + Arousal Coupling
  B (GWT OFF): use_affective_layer=False — old sequential injection + fixed budget

Metrics:
  - cert_rate (simple)
  - weighted_cert_rate (strategic topics weight 1.5x, tactical 1.0x)
  - avg_score
  - avg_llm_calls_per_topic
  - total_time_seconds

Usage:
    python backend/gwt_ab_test.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

RESULTS_PATH = _ROOT / "shard_workspace" / "gwt_ab_results.json"

TOPICS = [
    {"topic": "python decorators and metaclasses",          "type": "tactical",  "weight": 1.0},
    {"topic": "debugging heisenbugs without reproduction",  "type": "strategic", "weight": 1.5},
    {"topic": "refactoring legacy code without tests",      "type": "strategic", "weight": 1.5},
]

TOPIC_BUDGET     = 25
SESSION_API_LIMIT = 100


# ── Per-topic runner ──────────────────────────────────────────────────────────

async def run_one(topic: str, use_affective_layer: bool) -> dict:
    from night_runner import NightRunner

    runner = NightRunner(
        cycles=1,
        timeout=30,
        pause=0,
        api_limit=SESSION_API_LIMIT,
        topic_budget=TOPIC_BUDGET,
        forced_topic=topic,
        use_affective_layer=use_affective_layer,
    )
    t0 = time.time()
    try:
        await runner.run()
    except Exception as exc:
        print("  ERROR: " + str(exc))
        return {
            "score": 0.0, "certified": False,
            "llm_calls": 0, "time_seconds": round(time.time() - t0, 1),
        }

    elapsed    = round(time.time() - t0, 1)
    cycle      = runner.session_data[-1] if runner.session_data else {}
    llm_calls  = getattr(runner, "api_calls_used", 0)

    return {
        "score":        float(cycle.get("score", 0.0)),
        "certified":    bool(cycle.get("certified", False)),
        "llm_calls":    llm_calls,
        "time_seconds": elapsed,
    }


# ── Condition runner ──────────────────────────────────────────────────────────

async def run_condition(use_affective_layer: bool, label: str) -> dict:
    print(f"\n{'─'*60}")
    print(f"[{label}] use_affective_layer={use_affective_layer}")
    print(f"{'─'*60}")

    topic_results = []
    session_start = time.time()

    for entry in TOPICS:
        topic = entry["topic"]
        print(f"  topic: {topic}")
        result = await run_one(topic, use_affective_layer)
        topic_results.append({
            "topic":        topic,
            "type":         entry["type"],
            "weight":       entry["weight"],
            "score":        result["score"],
            "certified":    result["certified"],
            "llm_calls":    result["llm_calls"],
            "time_seconds": result["time_seconds"],
        })
        cert_str = "CERT" if result["certified"] else "FAIL"
        print(f"    {cert_str} score={result['score']:.1f} llm_calls={result['llm_calls']} ({result['time_seconds']}s)")

    total_time = round(time.time() - session_start, 1)

    # ── Aggregate ─────────────────────────────────────────────────────────────
    n = len(topic_results)

    cert_rate       = sum(1 for r in topic_results if r["certified"]) / n if n else 0.0
    avg_score       = sum(r["score"] for r in topic_results) / n if n else 0.0
    avg_llm_calls   = sum(r["llm_calls"] for r in topic_results) / n if n else 0.0

    # Weighted cert rate: certified * weight / total_weight
    total_weight     = sum(r["weight"] for r in topic_results)
    weighted_cert    = sum(r["weight"] for r in topic_results if r["certified"])
    weighted_cert_rate = round(weighted_cert / total_weight, 4) if total_weight else 0.0

    return {
        "condition": label,
        "topics": topic_results,
        "aggregated": {
            "cert_rate":              round(cert_rate, 4),
            "weighted_cert_rate":     weighted_cert_rate,
            "avg_score":              round(avg_score, 2),
            "avg_llm_calls_per_topic": round(avg_llm_calls, 1),
            "total_time_seconds":     total_time,
        },
    }


# ── Verdict ───────────────────────────────────────────────────────────────────

def compute_verdict(a: dict, b: dict) -> dict:
    agg_a = a["aggregated"]
    agg_b = b["aggregated"]

    cert_delta    = round(agg_a["cert_rate"] - agg_b["cert_rate"], 4)
    score_delta   = round(agg_a["avg_score"] - agg_b["avg_score"], 2)
    calls_delta   = round(agg_a["avg_llm_calls_per_topic"] - agg_b["avg_llm_calls_per_topic"], 1)
    wcert_delta   = round(agg_a["weighted_cert_rate"] - agg_b["weighted_cert_rate"], 4)

    # Score: +1 per metric where A wins, -1 where B wins, 0 tie
    # cert_rate, score: higher = better for A
    # llm_calls: lower = better for A (negative delta is good)
    vote_cert  = 1 if cert_delta > 0.05 else (-1 if cert_delta < -0.05 else 0)
    vote_score = 1 if score_delta > 0.3  else (-1 if score_delta < -0.3  else 0)
    vote_calls = 1 if calls_delta < -1.0 else (-1 if calls_delta > 1.0   else 0)

    total_vote = vote_cert + vote_score + vote_calls

    if total_vote > 0:
        winner = "GWT_ON"
        recommendation = "KEEP GWT"
    elif total_vote < 0:
        winner = "GWT_OFF"
        recommendation = "REVERT GWT"
    else:
        winner = "TIE"
        recommendation = "INVESTIGATE"

    def _fmt(v):
        return ("+" if v >= 0 else "") + str(v)

    return {
        "winner":              winner,
        "cert_rate_delta":     _fmt(cert_delta),
        "weighted_cert_delta": _fmt(wcert_delta),
        "avg_score_delta":     _fmt(score_delta),
        "efficiency_delta":    _fmt(calls_delta) + " calls/topic",
        "vote_breakdown":      {"cert": vote_cert, "score": vote_score, "calls": vote_calls},
        "recommendation":      recommendation,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("GWT A/B TEST")
    print("=" * 60)

    result_a = await run_condition(True,  "GWT_ON")
    result_b = await run_condition(False, "GWT_OFF")

    verdict = compute_verdict(result_a, result_b)

    report = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "config": {
            "topics":           [e["topic"] for e in TOPICS],
            "topic_budget":     TOPIC_BUDGET,
            "session_api_limit": SESSION_API_LIMIT,
        },
        "run_a":   result_a,
        "run_b":   result_b,
        "verdict": verdict,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 60)
    print("[AB] VERDICT")
    print("=" * 60)
    agg_a = result_a["aggregated"]
    agg_b = result_b["aggregated"]
    print(f"  cert_rate:   GWT_ON={agg_a['cert_rate']:.1%}  GWT_OFF={agg_b['cert_rate']:.1%}  Δ={verdict['cert_rate_delta']}")
    print(f"  avg_score:   GWT_ON={agg_a['avg_score']:.2f}  GWT_OFF={agg_b['avg_score']:.2f}  Δ={verdict['avg_score_delta']}")
    print(f"  llm_calls:   GWT_ON={agg_a['avg_llm_calls_per_topic']:.1f}  GWT_OFF={agg_b['avg_llm_calls_per_topic']:.1f}  Δ={verdict['efficiency_delta']}")
    print(f"\n  WINNER: {verdict['winner']}")
    print(f"  RECOMMENDATION: {verdict['recommendation']}")
    print(f"\n[AB] Results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
