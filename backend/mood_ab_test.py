"""mood_ab_test.py — A/B test: FULL affective layer vs BYPASS on NightRunner study cycles.

RUN A (WITH):  use_affective_layer=True  — MoodEngine + IdentityCore injected into session_context
RUN B (WITHOUT): use_affective_layer=False — only EpisodicMemory, GraphRAG, StrategyMemory, CognitionCore

For each topic: run A first, then B. Collect score, certified, attempts, elapsed_s.
Results saved to shard_workspace/mood_ab_results.json.

Usage:
    python backend/mood_ab_test.py
    python backend/mood_ab_test.py --topics "python decorators" "python generators"
    python backend/mood_ab_test.py --n 10
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

RESULTS_PATH = _ROOT / "shard_workspace" / "mood_ab_results.json"
CURATED_TOPICS_FILE = _ROOT / "shard_memory" / "curated_topics.txt"

DEFAULT_N = 10


def _load_curated_topics(n: int) -> list[str]:
    topics = []
    if CURATED_TOPICS_FILE.exists():
        for line in CURATED_TOPICS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                topics.append(line)
                if len(topics) >= n:
                    break
    return topics


async def _run_one_cycle(topic: str, use_affective_layer: bool) -> dict:
    """Run a single NightRunner study cycle for the given topic. Returns metrics dict."""
    from night_runner import NightRunner

    runner = NightRunner(
        cycles=1,
        timeout=30,
        pause=0,
        api_limit=50,
        topic_budget=1,
        forced_topic=topic,
        use_affective_layer=use_affective_layer,
    )

    t0 = time.time()
    try:
        await runner.run()
    except Exception as exc:
        return {
            "condition": "WITH" if use_affective_layer else "WITHOUT",
            "topic": topic,
            "score": 0.0,
            "certified": False,
            "attempts": None,
            "elapsed_s": round(time.time() - t0, 1),
            "error": str(exc),
        }

    elapsed = round(time.time() - t0, 1)
    cycle = runner.session_data[-1] if runner.session_data else {}

    return {
        "condition": "WITH" if use_affective_layer else "WITHOUT",
        "topic": topic,
        "score": float(cycle.get("score", 0.0)),
        "certified": bool(cycle.get("certified", False)),
        "attempts": cycle.get("attempts", None),
        "elapsed_s": elapsed,
    }


async def run_ab(topics: list[str]) -> list[dict]:
    results = []

    for topic in topics:
        print(f"\n{'='*60}")
        print(f"[MOOD AB] Topic: {topic}")

        print(f"  --- RUN A: WITH affective layer ---")
        run_a = await _run_one_cycle(topic, use_affective_layer=True)
        print(f"  [A] score={run_a['score']:.1f} certified={run_a['certified']} ({run_a['elapsed_s']}s)")

        print(f"  --- RUN B: WITHOUT affective layer ---")
        run_b = await _run_one_cycle(topic, use_affective_layer=False)
        print(f"  [B] score={run_b['score']:.1f} certified={run_b['certified']} ({run_b['elapsed_s']}s)")

        delta = round(run_a["score"] - run_b["score"], 2)
        print(f"  [MOOD AB] {topic}: A={run_a['score']:.1f} B={run_b['score']:.1f} delta={delta:+.1f}")

        results.append({
            "topic":   topic,
            "with":    run_a,
            "without": run_b,
            "delta_score": delta,
            "with_wins": run_a["score"] > run_b["score"],
        })

    return results


def _summary(results: list[dict]) -> dict:
    if not results:
        return {}
    n = len(results)

    scores_a  = [r["with"]["score"]    for r in results]
    scores_b  = [r["without"]["score"] for r in results]
    cert_a    = sum(1 for r in results if r["with"]["certified"])
    cert_b    = sum(1 for r in results if r["without"]["certified"])
    att_a_raw = [r["with"]["attempts"]    for r in results if r["with"]["attempts"]    is not None]
    att_b_raw = [r["without"]["attempts"] for r in results if r["without"]["attempts"] is not None]

    avg_a   = round(sum(scores_a) / n, 2)
    avg_b   = round(sum(scores_b) / n, 2)
    cr_a    = round(cert_a / n, 3)
    cr_b    = round(cert_b / n, 3)
    att_a   = round(sum(att_a_raw) / len(att_a_raw), 2) if att_a_raw else None
    att_b   = round(sum(att_b_raw) / len(att_b_raw), 2) if att_b_raw else None
    with_wins = sum(1 for r in results if r["with_wins"])

    verdict = (
        "WITH WINS — affective layer improves performance"
        if cr_a - cr_b > 0.03 else
        "WITHOUT WINS (unexpected)" if cr_b - cr_a > 0.03 else
        "Affective layer does not improve performance. Candidates for removal."
    )

    return {
        "n_topics":         n,
        "with_wins":        with_wins,
        "without_wins":     n - with_wins,
        "avg_score_with":   avg_a,
        "avg_score_without": avg_b,
        "cert_rate_with":   cr_a,
        "cert_rate_without": cr_b,
        "avg_attempts_with":    att_a,
        "avg_attempts_without": att_b,
        "verdict": verdict,
    }


def main():
    parser = argparse.ArgumentParser(description="Mood/Identity affective layer A/B test")
    parser.add_argument("--topics", nargs="+", help="Topics to test (default: curated list)")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help=f"Number of curated topics (default {DEFAULT_N})")
    args = parser.parse_args()

    if args.topics:
        topics = args.topics
    else:
        topics = _load_curated_topics(args.n)
        if not topics:
            print(f"[MOOD AB] No topics found in {CURATED_TOPICS_FILE}")
            sys.exit(1)

    print(f"[MOOD AB] Running A/B test on {len(topics)} topics")
    print(f"[MOOD AB] RUN A: WITH MoodEngine + IdentityCore")
    print(f"[MOOD AB] RUN B: WITHOUT (bypass affective layer)")

    results = asyncio.run(run_ab(topics))
    summary = _summary(results)

    print(f"\n{'='*60}")
    print(f"[MOOD AB] SUMMARY ({summary['n_topics']} topics)")
    print(f"[MOOD AB] cert_rate A={summary['cert_rate_with']:.1%} B={summary['cert_rate_without']:.1%}")
    print(f"[MOOD AB] avg_score A={summary['avg_score_with']:.1f} B={summary['avg_score_without']:.1f}")
    if summary["avg_attempts_with"] is not None:
        print(f"[MOOD AB] avg_attempts A={summary['avg_attempts_with']:.1f} B={summary['avg_attempts_without']:.1f}")
    print(f"[MOOD AB] VERDICT: {summary['verdict']}")

    if abs(summary["cert_rate_with"] - summary["cert_rate_without"]) < 0.03:
        print("[MOOD AB] VERDICT: Affective layer does not improve performance. Candidates for removal.")

    output = {
        "run_at":  __import__("datetime").datetime.now().isoformat(),
        "summary": summary,
        "topics":  results,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\n[MOOD AB] Results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
