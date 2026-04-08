from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd


def clean_text(text: str) -> str:
    text = text.strip()
    if len(text) > 200:
        text = text[:200].rsplit(" ", 1)[0] + "…"
    return text.replace("\n", " ")


def build_report(df: pd.DataFrame) -> str:
    groups = defaultdict(list)
    metadata = {}

    for _, row in df.iterrows():
        eid = row["embedding_id"]
        groups[eid].append((row["key"], row["string_value"]))
        if row["key"] == "topic" and eid not in metadata:
            metadata[eid] = {"topic": row["string_value"]}

    report = ["# Cross-Pollination Shortlist", ""]
    repeatable = []
    suspicious = []

    for eid, records in groups.items():
        topic = metadata.get(eid, {}).get("topic", eid)
        doc = "\n".join(value for key, value in records if key == "chroma:document")
        has_rec = any("Raccomandazione" in value or "Necessità" in value for _, value in records)
        repeats = len(records) > 3
        snippet = clean_text(doc) if doc else clean_text(records[0][1])
        entry = {
            "id": eid,
            "topic": topic,
            "snippet": snippet,
            "has_rec": has_rec,
            "repeats": repeats,
        }
        if repeats or has_rec:
            repeatable.append(entry)
        else:
            suspicious.append(entry)

    report.append("## Ripetibili / con raccomandazione")
    if repeatable:
        for item in repeatable:
            report.append(f"- **{item['topic']}** ({item['id']}): {item['snippet']}")
    else:
        report.append("- nessuna evidenza ripetuta")

    report.append("\n## Sospetti / una tantum")
    if suspicious:
        for item in suspicious:
            report.append(f"- **{item['topic']}** ({item['id']}): {item['snippet']}")
    else:
        report.append("- nessun evento sospetto")

    return "\n".join(report)


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    csv_path = repo / "knowledge_db" / "shard_memoria_grezza.csv"

    if not csv_path.exists():
        print("manca shard_memoria_grezza.csv")
        return 1

    df = pd.read_csv(csv_path, usecols=["embedding_id", "key", "string_value"])
    mask = df["string_value"].str.contains("cross_pollination", na=False, case=False)
    filtered = df[mask]

    report = build_report(filtered)
    out_path = repo / "knowledge_db" / "cross_pollination_shortlist.md"
    out_path.write_text(report, encoding="utf-8")
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
