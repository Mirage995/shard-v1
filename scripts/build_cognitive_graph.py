from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


PAIR_SPLIT_RE = re.compile(r"\s+(?:applied to|and|applied|and/or|versus|with)\s+", re.IGNORECASE)


def parse_topics_from_id(eid: str) -> list[str]:
    base = re.sub(r"(_20\d{6,})$", "", eid)
    base = base.replace("integration_", "").replace("_", " ")
    parts = [part.strip() for part in PAIR_SPLIT_RE.split(base) if part.strip()]
    if not parts:
        return [base.strip()]
    return parts


def summarize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0][:140] if lines else ""


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    csv_path = repo / "knowledge_db" / "shard_memoria_grezza.csv"
    if not csv_path.exists():
        print("manca il CSV")
        return 1

    df = pd.read_csv(csv_path, usecols=["embedding_id", "key", "string_value"])
    df = df[df["string_value"].str.contains("cross_pollination", case=False, na=False)]

    node_counter = Counter()
    snippet_map = {}
    edges = Counter()

    for eid, group in df.groupby("embedding_id"):
        topics = parse_topics_from_id(eid)
        preview = "\n".join(group.loc[group["key"] == "chroma:document", "string_value"].tolist()) or group["string_value"].iloc[0]
        summary = summarize_text(preview)
        for topic in topics:
            node_counter[topic] += 1
            if topic not in snippet_map:
                snippet_map[topic] = summary
        for i in range(len(topics)):
            for j in range(i + 1, len(topics)):
                a, b = sorted((topics[i], topics[j]))
                edges[(a, b)] += 1

    nodes = []
    for idx, (label, count) in enumerate(node_counter.items()):
        nodes.append(
            {
                "id": str(idx),
                "label": label,
                "count": count,
                "snippet": snippet_map.get(label, ""),
            }
        )

    node_index = {node["label"]: node["id"] for node in nodes}
    edges_out = []
    for (a, b), weight in edges.items():
        if a in node_index and b in node_index:
            edges_out.append(
                {
                    "source": node_index[a],
                    "target": node_index[b],
                    "weight": weight,
                }
            )

    out = {"nodes": nodes, "edges": edges_out}
    out_path = repo / "knowledge_db" / "cognitive_graph.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
