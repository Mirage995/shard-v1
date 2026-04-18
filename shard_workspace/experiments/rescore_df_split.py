"""
rescore_df_split.py — Triple re-score of H1-H5 from run 233916
using the new domain_fidelity_mechanism / domain_fidelity_data_realism split rubric.

Because minimum_experiment was not logged in run 233916, this script:
  1. Uses the original hypothesis statement + domains to call the synthesizer
     once per hypothesis to generate a fresh minimum_experiment
  2. Then calls _validate_experiment_alignment 3 times on that experiment
  3. Reports mean ± std of DF_mechanism, DF_data_realism, and all other criteria

Output: shard_workspace/experiments/rescore_df_split_H1H5_20260418.json

Usage:
    cd backend
    python ../shard_workspace/experiments/rescore_df_split.py
"""

import asyncio
import json
import os
import sys
import statistics
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../../backend")
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../../backend")

from study_agent import StudyAgent

# H1-H5 from alignment_log_20260417_233916.jsonl
HYPOTHESES = [
    {
        "statement":   "Applying dynamic ensemble selection techniques to time series forecasting can improve the accuracy of predictions.",
        "domain_from": "Machine Learning",
        "domain_to":   "Time Series Forecasting",
        "falsifiable": True,
        "confidence":  0.8,
        "rationale":   "Dynamic ensemble selection adapts model weights at test time based on local competence.",
    },
    {
        "statement":   "Applying memory mapping techniques to transactional memory systems can improve performance.",
        "domain_from": "Memory Management",
        "domain_to":   "Transactional Memory Systems",
        "falsifiable": True,
        "confidence":  0.8,
        "rationale":   "Memory-mapped regions reduce copy overhead in transaction commit paths.",
    },
    {
        "statement":   "Applying techniques from social network analysis to average-atom models can improve the accuracy of simulations.",
        "domain_from": "Social Network Analysis",
        "domain_to":   "Average-Atom Models",
        "falsifiable": True,
        "confidence":  0.75,
        "rationale":   "Graph centrality measures could identify dominant atomic configurations in ensemble averaging.",
    },
    {
        "statement":   "The introduction of probabilistic balancing in AVL trees can reduce the average rotation count per insertion.",
        "domain_from": "Probabilistic Data Structures",
        "domain_to":   "Database Indexing",
        "falsifiable": True,
        "confidence":  0.8,
        "rationale":   "Probabilistic skip of strict rebalancing trades worst-case height for fewer rotations on average.",
    },
    {
        "statement":   "Applying the LZ77 compression algorithm to DNA sequences can achieve a higher compression ratio than standard methods.",
        "domain_from": "data compression",
        "domain_to":   "bioinformatics",
        "falsifiable": True,
        "confidence":  0.75,
        "rationale":   "DNA exhibits repetitive subsequences analogous to sliding-window matches in LZ77.",
    },
]

N_RESCORE = 3   # validator calls per hypothesis (opzione 2: triplo)
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "rescore_df_split_H1H5_20260418.json"
)

SYNTH_PROMPT_TEMPLATE = """\
You are generating a minimum_experiment for the following cross-domain hypothesis.

Hypothesis: {statement}
Domain from: {domain_from}
Domain to: {domain_to}

Output a minimum_experiment in EXACTLY this 5-section format:
MECHANISM: [causal mechanism — VARIABLE: V = <observable formula>]
INTERVENTION: [technique vs baseline. Simulated as: generate <data> using numpy/scipy]
MEASUREMENT: [Metric: <name_of_V>, computed as <exact formula>]
SUCCESS CRITERION: [<name_of_V> condition with numeric threshold]
CONTROL: [1-2 confounders held constant]

CAPABILITY CONTRACT: experiment MUST be runnable with numpy/scipy only, NO external datasets.
Return ONLY the 5-section text, no explanation."""


async def synthesize_min_exp(agent: StudyAgent, hyp: dict) -> str:
    prompt = SYNTH_PROMPT_TEMPLATE.format(**hyp)
    return await agent._think(prompt, temperature=0.4)


async def rescore_hypothesis(agent: StudyAgent, hyp_base: dict, n: int = 3) -> dict:
    print(f"\n[RESCORE] Synthesizing min_exp for: '{hyp_base['statement'][:70]}...'")
    min_exp = await synthesize_min_exp(agent, hyp_base)
    print(f"  min_exp[:120]: {min_exp[:120]}")

    hyp = dict(hyp_base)
    hyp["minimum_experiment"] = min_exp

    scores = []
    for i in range(n):
        result = await agent._validate_experiment_alignment(hyp, attempt=i)
        c = result.get("criteria") or {}
        scores.append({
            "df_mechanism":    c.get("domain_fidelity_mechanism"),
            "df_data_realism": c.get("domain_fidelity_data_realism"),
            "domain_fidelity": c.get("domain_fidelity"),
            "causal_link":     c.get("causal_link"),
            "falsifiability":  c.get("falsifiability"),
            "implementability":c.get("implementability"),
            "alignment_score": result.get("alignment_score"),
            "verdict":         result.get("verdict"),
        })
        print(f"  [{i+1}/{n}] DF_mech={c.get('domain_fidelity_mechanism')} "
              f"DF_data={c.get('domain_fidelity_data_realism')} "
              f"FA={c.get('falsifiability')} score={result.get('alignment_score')}")

    def mean_field(field):
        vals = [s[field] for s in scores if s[field] is not None]
        return round(statistics.mean(vals), 3) if vals else None

    def std_field(field):
        vals = [s[field] for s in scores if s[field] is not None]
        return round(statistics.stdev(vals), 3) if len(vals) > 1 else None

    return {
        "hypothesis":      hyp_base["statement"][:100],
        "domain_from":     hyp_base["domain_from"],
        "domain_to":       hyp_base["domain_to"],
        "minimum_experiment": min_exp,
        "n_scores":        n,
        "mean": {
            "df_mechanism":    mean_field("df_mechanism"),
            "df_data_realism": mean_field("df_data_realism"),
            "domain_fidelity": mean_field("domain_fidelity"),
            "causal_link":     mean_field("causal_link"),
            "falsifiability":  mean_field("falsifiability"),
            "implementability":mean_field("implementability"),
            "alignment_score": mean_field("alignment_score"),
        },
        "std": {
            "df_mechanism":    std_field("df_mechanism"),
            "df_data_realism": std_field("df_data_realism"),
            "causal_link":     std_field("causal_link"),
            "falsifiability":  std_field("falsifiability"),
            "implementability":std_field("implementability"),
            "alignment_score": std_field("alignment_score"),
        },
        "raw_scores": scores,
    }


async def main():
    print(f"[RESCORE] Starting triple re-score on {len(HYPOTHESES)} hypotheses ({N_RESCORE} validator calls each)")
    print(f"[RESCORE] Total validator calls: {len(HYPOTHESES)} synthesis + {len(HYPOTHESES) * N_RESCORE} validator = "
          f"{len(HYPOTHESES) + len(HYPOTHESES) * N_RESCORE} LLM calls")

    agent = StudyAgent()
    results = []

    for i, hyp in enumerate(HYPOTHESES):
        print(f"\n{'='*60}")
        print(f"[RESCORE] H{i+1}/{len(HYPOTHESES)}")
        try:
            result = await rescore_hypothesis(agent, hyp, n=N_RESCORE)
            results.append(result)
            m = result["mean"]
            s = result["std"]
            print(f"  MEAN — DF_mech={m['df_mechanism']}±{s['df_mechanism']} "
                  f"DF_data={m['df_data_realism']}±{s['df_data_realism']} "
                  f"FA={m['falsifiability']}±{s['falsifiability']} "
                  f"score={m['alignment_score']}±{s['alignment_score']}")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append({"hypothesis": hyp["statement"][:100], "error": str(exc)})

    # Summary
    print(f"\n{'='*60}")
    print("[RESCORE] SUMMARY")
    df_mechs = [r["mean"]["df_mechanism"] for r in results if "mean" in r and r["mean"]["df_mechanism"] is not None]
    df_datas = [r["mean"]["df_data_realism"] for r in results if "mean" in r and r["mean"]["df_data_realism"] is not None]
    fas      = [r["mean"]["falsifiability"] for r in results if "mean" in r and r["mean"]["falsifiability"] is not None]
    if df_mechs:
        print(f"  DF_mechanism   mean={round(statistics.mean(df_mechs),3)} (N={len(df_mechs)})")
    if df_datas:
        print(f"  DF_data_realism mean={round(statistics.mean(df_datas),3)} (N={len(df_datas)})")
    if fas:
        print(f"  Falsifiability  mean={round(statistics.mean(fas),3)} (N={len(fas)})")

    output = {
        "run_id":    f"rescore_df_split_{time.strftime('%Y%m%d_%H%M%S')}",
        "source_run": "233916",
        "n_hypotheses": len(HYPOTHESES),
        "n_rescore_per_hyp": N_RESCORE,
        "results": results,
        "aggregate": {
            "df_mechanism_mean":    round(statistics.mean(df_mechs), 3) if df_mechs else None,
            "df_data_realism_mean": round(statistics.mean(df_datas), 3) if df_datas else None,
            "falsifiability_mean":  round(statistics.mean(fas), 3) if fas else None,
        }
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n[RESCORE] Output written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
