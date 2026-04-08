"""principle_engine.py -- Extract and inject cross-domain principles for SHARD.

Flow:
  CrossPollinatePhase generates free-text connections (ctx.connections / integration_report).
  extract_principles() parses those into structured dicts and appends to principles.json.
  inject_principles() is called by InitPhase to prepend relevant principles to episode_context.

Principle schema:
  {
    "id": "sha1[:8]",
    "name": "structural_optimization",
    "statement": "Structure enables efficiency across domains",
    "domains": ["algorithms", "concurrency"],
    "source_topic": "binary search",
    "confidence": 0.75,
    "created_at": "2026-04-04T..."
  }
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRINCIPLES_FILE = Path(__file__).parent.parent / "shard_memory" / "principles.json"
MAX_PRINCIPLES = 200   # cap to avoid unbounded growth
INJECT_TOP_K = 5       # how many principles to inject per study run


# ── I/O helpers ──────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    if PRINCIPLES_FILE.exists():
        try:
            return json.loads(PRINCIPLES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(principles: list[dict]) -> None:
    PRINCIPLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRINCIPLES_FILE.write_text(json.dumps(principles, indent=2, ensure_ascii=False), encoding="utf-8")


def _make_id(statement: str) -> str:
    return hashlib.sha1(statement.lower().strip().encode()).hexdigest()[:8]


# ── Extraction ────────────────────────────────────────────────────────────────

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "algorithms": ["algorithm", "complexity", "sorting", "search", "O(", "binary", "graph", "tree"],
    "concurrency": ["async", "concurrent", "thread", "coroutine", "await", "parallel", "lock"],
    "machine_learning": ["ml", "neural", "training", "gradient", "model", "diffusion", "transformer"],
    "security": ["crypto", "cipher", "hash", "auth", "vulnerability", "attack", "adversarial"],
    "graph_theory": ["graph", "node", "edge", "network", "topology", "path", "cluster"],
    "biology": ["protein", "ligand", "alphafold", "molecular", "binding", "structure", "drug"],
    "software_engineering": ["pipeline", "refactor", "module", "interface", "abstraction", "pattern"],
}


def _detect_domains(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(domain)
    return found or ["general"]


def _parse_connections_text(text: str, source_topic: str) -> list[dict]:
    """Parse free-text cross-domain connections into structured principles.

    Handles the numbered format produced by SHARD's cross-pollination prompts:
        1. Domini collegati: X e Y
           Principio strutturale condiviso: ...
    """
    principles: list[dict] = []

    # Split on numbered blocks (1. / 2. / etc.)
    blocks = re.split(r"\n(?=\d+\.)", text.strip())

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Extract "Principio strutturale condiviso" line
        match = re.search(
            r"[Pp]rincipio strutturale condiviso[:\s]+(.+?)(?:\n\n|\n[A-Z]|$)",
            block,
            re.DOTALL,
        )
        if not match:
            # Fallback: take the longest sentence as the principle statement
            sentences = [s.strip() for s in re.split(r"[.\n]", block) if len(s.strip()) > 40]
            if not sentences:
                continue
            statement = max(sentences, key=len)
        else:
            statement = match.group(1).strip().replace("\n", " ")

        # Condense to a single readable sentence (first 200 chars)
        statement = re.sub(r"\s+", " ", statement)[:200]

        # Extract domain pair from "Domini collegati: X e Y"
        dom_match = re.search(r"[Dd]omini collegati[:\s]+(.+?)(?:\n|$)", block)
        if dom_match:
            dom_text = dom_match.group(1)
            detected_domains = _detect_domains(dom_text)
        else:
            detected_domains = _detect_domains(block)

        # Empirical verifiability nudges confidence up
        verif = bool(re.search(r"verific|empiric|misur|test", block, re.I))
        confidence = 0.80 if verif else 0.65

        principles.append({
            "id": _make_id(statement),
            "name": _slugify(statement),
            "statement": statement,
            "domains": detected_domains,
            "source_topic": source_topic,
            "confidence": confidence,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    return principles


def _slugify(text: str) -> str:
    """Turn a sentence into a snake_case name (max 5 words)."""
    words = re.findall(r"[a-zA-Z]+", text.lower())[:5]
    return "_".join(words) if words else "unnamed_principle"


# ── Public API ────────────────────────────────────────────────────────────────

def extract_principles(connections_text: str, source_topic: str) -> list[dict]:
    """Parse connections_text, merge new principles into principles.json.

    Returns the list of newly added principles (duplicates skipped).
    """
    if not connections_text or not connections_text.strip():
        return []

    new_principles = _parse_connections_text(connections_text, source_topic)
    if not new_principles:
        return []

    existing = _load()
    existing_ids = {p["id"] for p in existing}

    added = []
    for p in new_principles:
        if p["id"] not in existing_ids:
            existing.append(p)
            existing_ids.add(p["id"])
            added.append(p)

    # Cap size
    if len(existing) > MAX_PRINCIPLES:
        existing = existing[-MAX_PRINCIPLES:]

    _save(existing)
    print(f"[PRINCIPLES] +{len(added)} new principles saved (total: {len(existing)})")
    return added


def inject_principles(topic: str, top_k: int = INJECT_TOP_K) -> str:
    """Return a formatted string of relevant principles for injection into episode_context.

    Relevance = domain overlap between topic keywords and principle domains.
    Falls back to most recent principles if no domain match.
    """
    principles = _load()
    if not principles:
        return ""

    topic_domains = set(_detect_domains(topic))
    topic_words = set(topic.lower().split())

    def relevance(p: dict) -> float:
        domain_overlap = len(topic_domains & set(p.get("domains", [])))
        word_overlap = any(w in p["statement"].lower() for w in topic_words if len(w) > 4)
        return domain_overlap * 0.6 + float(word_overlap) * 0.4 + p.get("confidence", 0.5) * 0.1

    ranked = sorted(principles, key=relevance, reverse=True)[:top_k]

    if not ranked:
        return ""

    lines = ["[PRINCIPLE LAYER] Relevant cross-domain principles extracted from past studies:"]
    for i, p in enumerate(ranked, 1):
        domains = ", ".join(p.get("domains", []))
        lines.append(f"{i}. [{domains}] {p['statement']} (confidence={p['confidence']:.2f})")

    return "\n".join(lines)


def list_principles(domain_filter: str | None = None) -> list[dict]:
    """Utility: return all principles, optionally filtered by domain."""
    principles = _load()
    if domain_filter:
        principles = [p for p in principles if domain_filter in p.get("domains", [])]
    return principles
