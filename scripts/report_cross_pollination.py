from __future__ import annotations

from pathlib import Path

import pandas as pd


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    csv_path = repo / "knowledge_db" / "shard_memoria_grezza.csv"
    if not csv_path.exists():
        print("missing shard_memoria_grezza.csv")
        return 1

    df = pd.read_csv(csv_path, usecols=["embedding_id", "key", "string_value"])
    mask = df["string_value"].str.contains("cross_pollination", na=False, case=False)
    candidate_ids = df.loc[mask, "embedding_id"].unique()

    report_lines = ["# Cross-Pollination Report", ""]
    for eid in candidate_ids:
        rows = df[df["embedding_id"] == eid]
        report_lines.append(f"## {eid}")
        for _, row in rows.iterrows():
            key = row["key"]
            value = row["string_value"].strip()
            report_lines.append(f"- **{key}**: {value}")
        report_lines.append("")

    out_path = repo / "knowledge_db" / "cross_pollination_report.md"
    out_path.write_text("\n".join(report_lines), encoding="utf-8")
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
