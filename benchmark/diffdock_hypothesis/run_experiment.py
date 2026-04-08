"""run_experiment.py -- Test hypothesis: diffusion steps vs conformational accuracy.

HYPOTHESIS:
  Increasing inference_steps in DiffDock improves docking accuracy
  for flexible complexes (large conformational changes) but has
  marginal effect on rigid complexes.

EXPERIMENT:
  For each complex in dataset, run DiffDock with inference_steps in
  [10, 20, 50, 100]. Record best RMSD per run. Stratify by flexibility class.

OUTPUT:
  results/raw_results.csv  -- one row per (complex, steps) combination
  results/summary.json     -- mean RMSD per (flexibility_class, steps)
"""
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
from spyrmsd import rmsd as spyrmsd_rmsd
from rdkit import Chem

DIFFDOCK_DIR = Path("/diffdock")
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

INFERENCE_STEPS = [10, 20, 50, 100]
SAMPLES_PER_COMPLEX = 10   # keep low to reduce compute; paper uses 40
CONFIDENCE_CUTOFF = 0.0    # accept all poses


def run_diffdock(protein_pdb: str, ligand_sdf: str, steps: int, out_dir: Path) -> list[float]:
    """Run DiffDock and return list of RMSDs for all generated poses."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build input CSV for DiffDock
    csv_path = out_dir / "input.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["protein_path", "ligand_description", "protein_sequence"])
        writer.writerow([protein_pdb, ligand_sdf, ""])

    cmd = [
        sys.executable,
        str(DIFFDOCK_DIR / "inference.py"),
        "--protein_ligand_csv", str(csv_path),
        "--out_dir", str(out_dir / "poses"),
        "--inference_steps", str(steps),
        "--samples_per_complex", str(SAMPLES_PER_COMPLEX),
        "--batch_size", "8",
        "--actual_steps", str(steps),
        "--no_final_step_noise",
    ]

    t0 = time.time()
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(DIFFDOCK_DIR), timeout=600
    )
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"    DiffDock FAIL (steps={steps}): {result.stderr[-300:]}")
        return []

    # Collect generated SDF poses
    poses_dir = out_dir / "poses"
    sdf_files = sorted(poses_dir.glob("**/*.sdf"))
    if not sdf_files:
        return []

    # Compute RMSD against reference ligand
    ref_mol = Chem.MolFromMolFile(ligand_sdf, removeHs=True)
    if ref_mol is None:
        return []

    rmsds = []
    for sdf in sdf_files:
        pred_mol = Chem.MolFromMolFile(str(sdf), removeHs=True)
        if pred_mol is None:
            continue
        try:
            r = _compute_rmsd(ref_mol, pred_mol)
            rmsds.append(r)
        except Exception:
            continue

    print(f"    steps={steps:3d} | poses={len(rmsds):2d} | best_rmsd={min(rmsds):.2f}Å | time={elapsed:.1f}s")
    return rmsds


def _compute_rmsd(ref_mol, pred_mol) -> float:
    """Symmetry-corrected RMSD using spyrmsd."""
    from spyrmsd import molecule, rmsd as spyrmsd_module
    import numpy as np

    def mol_to_coords_elements(mol):
        conf = mol.GetConformer()
        coords = conf.GetPositions()
        elements = [a.GetAtomicNum() for a in mol.GetAtoms()]
        adj = Chem.GetAdjacencyMatrix(mol)
        return coords, elements, adj

    ref_coords, ref_el, ref_adj = mol_to_coords_elements(ref_mol)
    pred_coords, pred_el, pred_adj = mol_to_coords_elements(pred_mol)

    r = spyrmsd_module.symmrmsd(
        ref_coords, pred_coords,
        ref_el, pred_el,
        ref_adj, pred_adj,
        minimize=True,
    )
    return float(r) if not hasattr(r, '__iter__') else float(r[0])


def main():
    dataset_csv = Path("data/complexes.csv")
    if not dataset_csv.exists():
        print("ERROR: data/complexes.csv not found. Run prepare_dataset.py first.")
        sys.exit(1)

    df = pd.read_csv(dataset_csv)
    print(f"Loaded {len(df)} complexes.")
    print(f"Inference steps to test: {INFERENCE_STEPS}")
    print(f"Samples per complex: {SAMPLES_PER_COMPLEX}")
    print(f"Total runs: {len(df) * len(INFERENCE_STEPS)}\n")

    raw_results = []

    for _, row in df.iterrows():
        pdb_id = row["pdb_id"]
        flex_class = row["flexibility_class"]
        print(f"\n[{pdb_id}] flexibility={flex_class}")

        for steps in INFERENCE_STEPS:
            out_dir = RESULTS_DIR / pdb_id / f"steps_{steps:03d}"
            rmsds = run_diffdock(
                row["protein_pdb"],
                row["ligand_sdf"],
                steps,
                out_dir,
            )
            if rmsds:
                best_rmsd = min(rmsds)
                raw_results.append({
                    "pdb_id": pdb_id,
                    "flexibility_class": flex_class,
                    "inference_steps": steps,
                    "best_rmsd": best_rmsd,
                    "all_rmsds": ";".join(f"{r:.3f}" for r in rmsds),
                    "n_poses": len(rmsds),
                })

    # Save raw results
    raw_csv = RESULTS_DIR / "raw_results.csv"
    with open(raw_csv, "w", newline="") as f:
        if raw_results:
            writer = csv.DictWriter(f, fieldnames=raw_results[0].keys())
            writer.writeheader()
            writer.writerows(raw_results)
    print(f"\nRaw results saved: {raw_csv} ({len(raw_results)} rows)")

    # Compute summary
    if raw_results:
        results_df = pd.DataFrame(raw_results)
        summary = (
            results_df
            .groupby(["flexibility_class", "inference_steps"])["best_rmsd"]
            .agg(["mean", "median", "std", "count"])
            .reset_index()
            .rename(columns={"mean": "mean_rmsd", "median": "median_rmsd", "std": "std_rmsd"})
        )
        summary_path = RESULTS_DIR / "summary.json"
        summary.to_json(summary_path, orient="records", indent=2)
        print(f"Summary saved: {summary_path}")
        print("\n" + summary.to_string(index=False))

    return raw_results


if __name__ == "__main__":
    main()
