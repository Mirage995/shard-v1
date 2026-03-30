"""study_personas.py -- Dynamic Study Personas for SHARD.

Instead of running 3 parallel clones (API expensive), SHARD:
1. Selects ONE persona based on topic category + meta_learning history
2. Adjusts study parameters accordingly (tier, sandbox_retries, focus)
3. After certification: records which persona succeeded -> future selections improve

Personas:
  THEORETICAL -- tier=2, deep docs, theory first. Best for CS theory, algorithms, crypto.
  HACKER      -- tier=1, code examples first, sandbox retries. Best for APIs, libraries, frameworks.
  VISUAL      -- tier=2, diagram generation hint, conceptual. Best for architectures, ML concepts.

Integration: night_runner calls select_persona() -> passes config to study_topic().
"""
import json
import logging
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("shard.personas")

_PERSONA_LOG = Path(__file__).parent.parent / "shard_memory" / "persona_history.json"


class PersonaType(Enum):
    THEORETICAL = "theoretical"
    HACKER      = "hacker"
    VISUAL      = "visual"


@dataclass
class PersonaConfig:
    persona: PersonaType
    tier: int
    strategy_hint: str
    sandbox_retries: int = 1
    focus_note: str = ""       # appended to system prompt context


# ── Category -> default persona mapping ────────────────────────────────────────

_CATEGORY_DEFAULTS: dict[str, PersonaType] = {
    "algorithms":      PersonaType.THEORETICAL,
    "cryptography":    PersonaType.THEORETICAL,
    "security":        PersonaType.THEORETICAL,
    "mathematics":     PersonaType.THEORETICAL,
    "theory":          PersonaType.THEORETICAL,
    "data_structures": PersonaType.THEORETICAL,

    "web":             PersonaType.HACKER,
    "api":             PersonaType.HACKER,
    "framework":       PersonaType.HACKER,
    "library":         PersonaType.HACKER,
    "debugging":       PersonaType.HACKER,
    "testing":         PersonaType.HACKER,
    "python":          PersonaType.HACKER,

    "ml":              PersonaType.VISUAL,
    "machine_learning": PersonaType.VISUAL,
    "neural":          PersonaType.VISUAL,
    "architecture":    PersonaType.VISUAL,
    "design_patterns": PersonaType.VISUAL,
    "systems":         PersonaType.VISUAL,
}

_PERSONA_CONFIGS: dict[PersonaType, PersonaConfig] = {
    PersonaType.THEORETICAL: PersonaConfig(
        persona=PersonaType.THEORETICAL,
        tier=2,
        strategy_hint="theory_first: study official docs and formal definitions before code examples",
        sandbox_retries=1,
        focus_note="Focus on formal definitions, proofs, and edge cases.",
    ),
    PersonaType.HACKER: PersonaConfig(
        persona=PersonaType.HACKER,
        tier=1,
        strategy_hint="code_first: find working code examples, run in sandbox, learn from failures",
        sandbox_retries=3,
        focus_note="Prioritize runnable code examples and practical patterns.",
    ),
    PersonaType.VISUAL: PersonaConfig(
        persona=PersonaType.VISUAL,
        tier=2,
        strategy_hint="visual_first: understand system structure and component relationships before details",
        sandbox_retries=1,
        focus_note="Generate diagrams and identify component relationships first.",
    ),
}


# ── Persona history (persisted) ────────────────────────────────────────────────

def _load_history() -> dict:
    try:
        return json.loads(_PERSONA_LOG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_history(history: dict):
    try:
        _PERSONA_LOG.parent.mkdir(parents=True, exist_ok=True)
        _PERSONA_LOG.write_text(
            json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("[PERSONAS] Save failed: %s", e)


# ── Public API ─────────────────────────────────────────────────────────────────

def select_persona(topic: str, category: str | None = None) -> PersonaConfig:
    """Select the best persona for a topic based on history and category.

    Returns a PersonaConfig with tier, strategy_hint, and focus_note.
    """
    history = _load_history()
    category_key = (category or "").lower().replace(" ", "_")

    # Check if this specific category has a winner from history
    if category_key and category_key in history.get("winners", {}):
        winner_name = history["winners"][category_key]
        try:
            persona = PersonaType(winner_name)
            config = _PERSONA_CONFIGS[persona]
            logger.info("[PERSONAS] Using history winner '%s' for category '%s'", winner_name, category_key)
            return config
        except (ValueError, KeyError):
            pass

    # Fall back to category defaults
    for cat, persona in _CATEGORY_DEFAULTS.items():
        if cat in category_key or cat in topic.lower():
            config = _PERSONA_CONFIGS[persona]
            logger.info("[PERSONAS] Using category default '%s' for '%s'", persona.value, topic)
            return config

    # Default: HACKER (practical, works for most programming topics)
    logger.info("[PERSONAS] Using default HACKER persona for '%s'", topic)
    return _PERSONA_CONFIGS[PersonaType.HACKER]


def record_outcome(
    topic: str,
    category: str | None,
    persona: PersonaType,
    certified: bool,
    score: float,
):
    """After a study cycle, record which persona produced what result.

    Used to improve future persona selection via meta-learning.
    """
    history = _load_history()
    category_key = (category or "unknown").lower().replace(" ", "_")

    # Per-category stats
    cats = history.setdefault("categories", {})
    cat_data = cats.setdefault(category_key, {})
    p_data = cat_data.setdefault(persona.value, {"attempts": 0, "certified": 0, "total_score": 0.0})
    p_data["attempts"] += 1
    p_data["total_score"] = round(p_data["total_score"] + score, 2)
    if certified:
        p_data["certified"] += 1

    # Update winner if this persona is now best for the category
    best_persona = None
    best_cert_rate = -1.0
    for p_name, stats in cat_data.items():
        if stats["attempts"] >= 2:  # min 2 attempts before crowning winner
            cert_rate = stats["certified"] / stats["attempts"]
            avg_score = stats["total_score"] / stats["attempts"]
            # Combined metric: cert rate + normalized avg score
            metric = cert_rate * 0.7 + (avg_score / 10.0) * 0.3
            if metric > best_cert_rate:
                best_cert_rate = metric
                best_persona = p_name

    if best_persona:
        history.setdefault("winners", {})[category_key] = best_persona
        logger.info("[PERSONAS] Updated winner for '%s': %s (metric=%.2f)",
                    category_key, best_persona, best_cert_rate)

    history["last_updated"] = datetime.now().isoformat()
    _save_history(history)


def get_persona_stats() -> dict:
    """Stats for /health endpoint."""
    history = _load_history()
    return {
        "winners": history.get("winners", {}),
        "category_count": len(history.get("categories", {})),
        "last_updated": history.get("last_updated"),
    }
