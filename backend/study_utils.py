"""study_utils.py -- Utility functions and types for the SHARD study pipeline.

Extracted from study_agent.py as part of SSJ3 Phase 1: Core Hardening.
Import from here instead of study_agent to avoid loading the full agent.
"""
import os
import re
import json
from typing import List, Dict
import numpy as np
from scipy.spatial.distance import cosine


def find_file(filename: str, start_path="."):
    for root, dirs, files in os.walk(start_path):
        if filename in files:
            return os.path.join(root, filename)
    return None


def safe_json_load(text):
    import json
    import re

    if not text:
        return None

    text = text.strip()

    # Stage 1: direct parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Stage 2: extract markdown JSON blocks
    md_blocks = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)

    for block in md_blocks:
        try:
            return json.loads(block)
        except Exception:
            continue

    # Stage 3: extract first JSON object
    obj_match = re.search(r"\{[\s\S]*\}", text)

    if obj_match:
        candidate = obj_match.group(0)

        try:
            return json.loads(candidate)
        except Exception:
            pass

    # Stage 4: attempt light sanitization
    cleaned = text.replace("'", '"')

    try:
        return json.loads(cleaned)
    except Exception:
        return None


GENERIC_CONCEPTS = {
    "system", "function", "value", "data", "object",
    "process", "algorithm", "result",
}

# ── TASK 2: Concept Validation ────────────────────────────────────────────────
STOPWORDS = {
    "data", "system", "thing", "information",
    "process", "example", "method"
}

# ── Semantic Concept Validation (Embedding-based) ──────────────────────────────
TECH_REFERENCE = [
    "algorithm",
    "neural network",
    "observability",
    "distributed system",
    "cryptography",
    "exception handling",
    "optimization",
    "database",
    "functional programming",
    "machine learning",
    "control flow",
    "software architecture"
]


def semantic_concept_score(name, embed_fn):
    """
    Score concept semantic relevance using embeddings.
    Returns max cosine similarity to reference tech concepts (0.0-1.0).
    Handles 2D arrays from embedding functions by flattening/unwrapping.
    """
    def normalize_vector(vec):
        """Normalize embedding vector to 1D array for cosine similarity."""
        vec = np.asarray(vec)
        # Unwrap if 2D (e.g., [[0.1, 0.2, ...]] from some embedding functions)
        if vec.ndim == 2:
            vec = vec[0]
        return vec

    try:
        concept_vec = normalize_vector(embed_fn(name))

        similarities = []
        for ref in TECH_REFERENCE:
            ref_vec = normalize_vector(embed_fn(ref))

            # Compute cosine similarity (1 - distance)
            sim = 1 - cosine(concept_vec, ref_vec)
            similarities.append(sim)

        return max(similarities) if similarities else 0.0

    except Exception as e:
        print(f"[SEMANTIC] Score error for '{name}': {e}")
        return 0.0


def valid_concept(name, embed_fn=None):
    """Validate concept name for quality and relevance, optionally with semantic scoring."""
    name = name.lower()

    if len(name) < 4:
        return False

    if name in STOPWORDS:
        return False

    if name.isnumeric():
        return False

    if embed_fn is not None:
        score = semantic_concept_score(name, embed_fn)
        if score < 0.25:
            return False

    return True


# ── PROGRESS TRACKER ──────────────────────────────────────────────────────────

PHASES = [
    {"name": "MAP",              "weight": 10},
    {"name": "AGGREGATE",        "weight": 20},
    {"name": "SYNTHESIZE",       "weight": 15},
    {"name": "STORE",            "weight": 5},
    {"name": "CROSS_POLLINATE",  "weight": 10},
    {"name": "MATERIALIZE",      "weight": 10},
    {"name": "SANDBOX",          "weight": 10},
    {"name": "VALIDATE",         "weight": 10},
    {"name": "EVALUATE",         "weight": 5},
    {"name": "CERTIFY",          "weight": 5},
]


class ProgressTracker:
    """Tracks study progress as a percentage across all phases."""
    def __init__(self):
        self.current_phase = ""
        self.phase_progress = {}  # phase_name -> 0.0 to 1.0
        self.total_weight = sum(p["weight"] for p in PHASES)

    def set_phase(self, phase_name: str, progress: float = 0.0):
        self.current_phase = phase_name
        self.phase_progress[phase_name] = min(1.0, max(0.0, progress))

    def complete_phase(self, phase_name: str):
        self.phase_progress[phase_name] = 1.0

    @property
    def percentage(self) -> int:
        total = 0
        for p in PHASES:
            total += p["weight"] * self.phase_progress.get(p["name"], 0.0)
        return min(100, int(total / self.total_weight * 100))

    @property
    def status(self) -> Dict:
        return {
            "phase": self.current_phase,
            "percentage": self.percentage,
            "phases": {p["name"]: self.phase_progress.get(p["name"], 0.0) for p in PHASES}
        }


def _extract_json_block(text: str) -> str:
    """Extract first JSON object from model output."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else text


def _filter_concepts(concepts: list, topic: str, capability_graph=None) -> list:
    """Filter low-quality or noisy concepts before capability graph updates."""
    topic_words = set(topic.lower().split())
    filtered = []
    for c in concepts:
        name = c.get("name", "") if isinstance(c, dict) else str(c)
        key = name.lower().strip()

        if len(key) < 4:
            print(f"[SYNTHESIZE] Skipped low-quality concept: {name}")
            continue
        if key in GENERIC_CONCEPTS:
            print(f"[SYNTHESIZE] Skipped low-quality concept: {name}")
            continue
        if any(ch.isdigit() for ch in key):
            print(f"[SYNTHESIZE] Skipped low-quality concept: {name}")
            continue
        if not any(ch.isalpha() for ch in key):
            print(f"[SYNTHESIZE] Skipped low-quality concept: {name}")
            continue
        if capability_graph and capability_graph.has_capability(key):
            print(f"[SYNTHESIZE] Skipped low-quality concept: {name}")
            continue
        concept_words = set(key.split())
        if topic_words and concept_words and not (topic_words & concept_words):
            print(f"[SYNTHESIZE] Skipped low-quality concept: {name}")
            continue

        filtered.append(c)
    return filtered
