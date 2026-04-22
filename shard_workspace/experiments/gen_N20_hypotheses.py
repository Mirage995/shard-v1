"""
gen_N20_hypotheses.py — Direct ExperimentEngine run targeting N=20 research hypotheses.

Bypasses NightRunner to avoid the ~85% SWE dilution (only ~15% of NightRunner cycles
produce research hypotheses). This script calls study_topic(research_mode=True) directly
on cross-domain topics, logging all calibration records to a fresh alignment_log.

The calibration log is written automatically by _calib_append() in experiment_phases.py.
Each complete topic produces 0 or 1 hypothesis records. Iterate until N_TARGET reached.

Usage:
    cd backend
    python ../shard_workspace/experiments/gen_N20_hypotheses.py

Output: shard_workspace/experiments/alignment_log_<timestamp>.jsonl (auto-generated)
        shard_workspace/experiments/gen_N20_run_<timestamp>.json    (run summary)
"""

import asyncio
import json
import os
import sys
import time

_root = os.path.dirname(os.path.abspath(__file__)) + "/../.."
_backend = _root + "/backend"
sys.path.insert(0, _backend)
sys.path.insert(0, _root)
os.chdir(_backend)

from study_agent import StudyAgent

N_TARGET = 20    # stop when this many hypothesis records logged
MAX_TOPICS = 80  # safety cap (80 topics → expect ~20 hypotheses at ~25% hit rate)

# Diverse cross-domain topic pool — broad enough to avoid domain clustering
TOPIC_POOL = [
    # ML × science
    "transfer learning in protein folding",
    "attention mechanisms in fluid dynamics simulation",
    "reinforcement learning for chemical synthesis planning",
    "graph neural networks for materials discovery",
    "contrastive learning in climate modeling",
    # algorithms × domain science
    "dynamic programming in phylogenetics",
    "monte carlo methods in financial risk modeling",
    "spectral methods in network epidemiology",
    "gradient descent variants in geophysics inversion",
    "sparse recovery in astronomical imaging",
    # information theory × applications
    "entropy minimization in neural coding",
    "kolmogorov complexity in biological sequence analysis",
    "rate-distortion theory in video compression for robotics",
    "channel capacity bounds in sensor fusion",
    "mutual information in causal inference for economics",
    # signal processing × biology
    "wavelet transforms in EEG artifact removal",
    "compressed sensing in functional MRI",
    "matched filter theory in neural spike sorting",
    "time-frequency analysis in bat echolocation modeling",
    "source separation in gene expression microarrays",
    # optimization × engineering
    "convex relaxation in power grid scheduling",
    "stochastic approximation in queueing network control",
    "interior point methods in structural topology optimization",
    "semidefinite programming in robot motion planning",
    "proximal gradient methods in radar beamforming",
    # combinatorics × CS theory
    "probabilistic method in network coding",
    "expander graphs in distributed storage systems",
    "derandomization techniques in approximate counting",
    "ramsey theory applications in communication complexity",
    "extremal combinatorics in database query optimization",
    # physics × computation
    "quantum walk algorithms in graph isomorphism",
    "statistical mechanics of boolean satisfiability",
    "percolation theory in network resilience",
    "renormalization group in neural network generalization",
    "phase transition phenomena in constraint satisfaction",
    # cognitive science × ML
    "predictive coding in reinforcement learning",
    "working memory models for transformer architectures",
    "sparse coding principles in dictionary learning",
    "hierarchical temporal memory in sequence prediction",
    "active inference in autonomous navigation",
    # control theory × biology
    "lyapunov stability in gene regulatory networks",
    "feedback linearization in metabolic pathway engineering",
    "optimal control of epidemiological SIR models",
    "model predictive control for glucose regulation",
    "H-infinity robust control in neural prosthetics",
    # geometry × ML
    "riemannian geometry in latent space interpolation",
    "persistent homology in time-series classification",
    "discrete differential geometry in mesh deformation networks",
    "information geometry in natural gradient optimization",
    "hyperbolic embeddings in hierarchical text classification",
    # more cross-domain
    "auction theory in federated learning",
    "mechanism design in recommendation systems",
    "game theory in multi-agent reinforcement learning",
    "voting theory in ensemble learning",
    "contract theory in privacy-preserving machine learning",
    "topology data analysis in motion capture",
    "algebraic coding theory in DNA storage",
    "number theory in cryptographic hash functions",
    "analytic combinatorics in algorithm average-case analysis",
    "ergodic theory in stochastic gradient descent convergence",
    "measure theory in generative model evaluation",
    "functional analysis in kernel methods",
    "operator theory in quantum machine learning",
    "category theory in functional programming optimization",
    "sheaf theory in multi-sensor data fusion",
    "matroid theory in submodular optimization for ML",
    "tropical geometry in phylogenetic tree reconstruction",
    "non-commutative geometry in signal processing",
    "p-adic analysis in neural network weight initialization",
    "cohomology theory in topological data analysis",
    "stochastic geometry in wireless network analysis",
    "point process theory in neural spike train analysis",
    "branching processes in viral spread modeling",
    "fluid-structure interaction in cardiac simulation",
    "vortex dynamics in microfluidic mixing",
    "granular media mechanics in powder pharmaceutical processing",
    "dislocation dynamics in crystal plasticity modeling",
    "coagulation equations in atmospheric aerosol modeling",
    "kinetic theory in traffic flow simulation",
    "mean field games in crowd dynamics",
    "rough path theory in financial time series",
]


async def main():
    print(f"[GEN_N20] Target: {N_TARGET} research hypotheses, max {MAX_TOPICS} topics")
    print(f"[GEN_N20] Topics available: {len(TOPIC_POOL)}")
    if len(TOPIC_POOL) < MAX_TOPICS:
        print(f"[GEN_N20] WARNING: topic pool smaller than max_topics cap")

    agent = StudyAgent()
    run_id = time.strftime("%Y%m%d_%H%M%S")
    run_log = []
    n_hypotheses = 0
    n_skipped = 0

    for i, topic in enumerate(TOPIC_POOL[:MAX_TOPICS]):
        if n_hypotheses >= N_TARGET:
            print(f"\n[GEN_N20] TARGET REACHED: {n_hypotheses}/{N_TARGET} hypotheses after {i} topics")
            break

        print(f"\n[GEN_N20] Topic {i+1}/{min(MAX_TOPICS, len(TOPIC_POOL))}: '{topic}'")
        t0 = time.time()
        try:
            await agent.study_topic(topic, tier=1, research_mode=True)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            n_skipped += 1
            run_log.append({"topic": topic, "status": "error", "error": str(exc)})
            continue

        elapsed = round(time.time() - t0, 1)
        # Count hypothesis records written so far by reading latest calib log
        # (The log is auto-created by _calib_append on first call)
        from experiment_phases import _calib_log_path
        log_path = _calib_log_path()
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
            n_hypotheses = len(records)
            last_verdict = records[-1].get("final_verdict", "?") if records else "?"
        else:
            last_verdict = "no_log"

        print(f"  elapsed={elapsed}s | total hypothesis records={n_hypotheses} | last_verdict={last_verdict}")
        run_log.append({
            "topic":         topic,
            "status":        "done",
            "elapsed_s":     elapsed,
            "n_hyp_total":   n_hypotheses,
            "last_verdict":  last_verdict,
        })

    print(f"\n[GEN_N20] DONE — {n_hypotheses} hypothesis records, {n_skipped} topic errors")
    print(f"[GEN_N20] Calibration log: {_calib_log_path() if os.path.exists(_calib_log_path()) else 'not found'}")

    summary_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"gen_N20_run_{run_id}.json"
    )
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_id":        run_id,
            "n_target":      N_TARGET,
            "n_reached":     n_hypotheses,
            "n_topics_run":  len(run_log),
            "n_errors":      n_skipped,
            "calib_log":     _calib_log_path() if os.path.exists(_calib_log_path()) else None,
            "topic_log":     run_log,
        }, f, indent=2, ensure_ascii=False)
    print(f"[GEN_N20] Run summary: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
