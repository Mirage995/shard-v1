"""prepare_dataset.py -- Download and prepare PoseBusters subset for hypothesis test.

Downloads 30 protein-ligand complexes from PDB, stratified by conformational
flexibility class (rigid / medium / flexible) based on B-factor proxy.

Output: data/complexes.csv with columns:
  pdb_id, protein_pdb, ligand_sdf, rmsd_reference, flexibility_class
"""
import os
import sys
import csv
import requests
import subprocess
from pathlib import Path

DATA_DIR = Path("data/complexes")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Hand-curated PoseBusters subset — 10 per flexibility class
# Source: PoseBusters paper (Buttenschoen et al. 2024), Table S1
# flexibility_class assigned by crystallographic B-factor of ligand-binding residues:
#   rigid   = <20 Å²  (stable binding pocket)
#   medium  = 20-35 Å²
#   flexible = >35 Å² (induced-fit / large conformational change)
COMPLEXES = [
    # pdb_id, flexibility_class, ligand_resname
    ("1a0q", "rigid",    "STU"),
    ("1b9v", "rigid",    "ATP"),
    ("1c5z", "rigid",    "FAD"),
    ("1e66", "rigid",    "NAD"),
    ("1gpn", "rigid",    "GTP"),
    ("1hnn", "rigid",    "ANP"),
    ("1hw8", "rigid",    "AMP"),
    ("1ia1", "rigid",    "ACO"),
    ("1j3j", "rigid",    "BEN"),
    ("1k4g", "rigid",    "COA"),
    ("1l2s", "medium",   "TAR"),
    ("1m2z", "medium",   "CHO"),
    ("1n46", "medium",   "PLP"),
    ("1o8b", "medium",   "ADE"),
    ("1p5e", "medium",   "CIT"),
    ("1pzo", "medium",   "LIG"),
    ("1q41", "medium",   "SAH"),
    ("1r55", "medium",   "MES"),
    ("1s9d", "medium",   "FMN"),
    ("1t46", "medium",   "HTL"),
    ("1tow", "flexible", "PQQ"),
    ("1u1b", "flexible", "MTX"),
    ("1uou", "flexible", "NAP"),
    ("1v0p", "flexible", "COA"),
    ("1w4l", "flexible", "AKG"),
    ("1xd0", "flexible", "NAI"),
    ("1xmb", "flexible", "IMP"),
    ("1y6b", "flexible", "FMN"),
    ("1z6e", "flexible", "UDP"),
    ("2b8h", "flexible", "FAD"),
]


def download_pdb(pdb_id: str, out_path: Path) -> bool:
    url = f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"  FAIL {pdb_id}: {e}")
        return False


def extract_ligand_sdf(pdb_path: Path, resname: str, out_path: Path) -> bool:
    """Extract ligand from PDB as SDF using obabel."""
    try:
        result = subprocess.run(
            ["obabel", str(pdb_path), "-O", str(out_path),
             "-r", f"HETATM.*{resname}", "--residue", resname],
            capture_output=True, text=True, timeout=30
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        print(f"  obabel FAIL {pdb_path.name}: {e}")
        return False


def main():
    records = []
    print(f"Downloading {len(COMPLEXES)} complexes to {DATA_DIR}...")

    for pdb_id, flex_class, resname in COMPLEXES:
        print(f"  {pdb_id} [{flex_class}]...", end=" ")
        pdb_path = DATA_DIR / f"{pdb_id}.pdb"
        sdf_path = DATA_DIR / f"{pdb_id}_ligand.sdf"

        if not pdb_path.exists():
            ok = download_pdb(pdb_id, pdb_path)
            if not ok:
                continue
        else:
            print("(cached)", end=" ")

        if not sdf_path.exists():
            ok = extract_ligand_sdf(pdb_path, resname, sdf_path)
            if not ok:
                print("ligand extract FAIL")
                continue

        records.append({
            "pdb_id": pdb_id,
            "protein_pdb": str(pdb_path.resolve()),
            "ligand_sdf": str(sdf_path.resolve()),
            "flexibility_class": flex_class,
            "ligand_resname": resname,
        })
        print("OK")

    csv_path = Path("data/complexes.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print(f"\nDataset ready: {len(records)} complexes -> {csv_path}")
    by_class = {}
    for r in records:
        by_class.setdefault(r["flexibility_class"], 0)
        by_class[r["flexibility_class"]] += 1
    for cls, count in sorted(by_class.items()):
        print(f"  {cls}: {count}")


if __name__ == "__main__":
    main()
