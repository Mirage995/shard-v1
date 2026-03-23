import re


def normalize_capability_name(name: str) -> str:
    """Normalize free-text capability names to snake_case identifiers."""
    text = (name or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s_-]", "", text)
    text = re.sub(r"[\s-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def is_valid_topic(topic: str) -> bool:
    """Quality gate for generated study topics.

    Blocks:
    - Too short / no alpha chars
    - Exact junk strings
    - Italian/natural language phrase fragments (not programming topics)
    - Off-topic pseudoscience (quantized inertia, dark matter, etc.)
    - Hallucination spirals (nested "integration of integration of...")
    - Topics explicitly named "impossible"
    """
    t = (topic or "").strip()
    if len(t) < 4:
        return False

    lowered = t.lower()

    # Exact banned strings
    banned_exact = {"test", "tmp", "none", "null", "asdf", "qwerty"}
    if lowered in banned_exact:
        return False

    # Require at least one alphabetic character
    if not any(ch.isalpha() for ch in t):
        return False

    # Italian phrase fragments / prompts masquerading as topics
    bad_tokens = {
        "chiedo", "facendo", "potrei", "quante", "completa",
        "scrivi", "esegui", "testa", "interrogative", "transitive",
    }
    if any(tok in lowered.split() for tok in bad_tokens):
        return False

    # Off-topic pseudoscience / fringe physics
    off_topic = [
        "quantized inertia", "galaxy rotation", "dark matter",
        "casimir effect", "modified newtonian", "hubble-scale",
        "modified gravity", "mond ", "qi theory",
        "n-body gravitational", "dark energy",
    ]
    if any(kw in lowered for kw in off_topic):
        return False

    # Reject topics starting with "impossible"
    if lowered.startswith("impossible"):
        return False

    # Hallucination spiral guard: max 1 level of "integration of"
    if lowered.count("integration of") >= 2:
        return False

    # Reject markdown headers and task-description strings
    # e.g. "# Task 04 — Fix the Banking Module", "## Fix the X"
    if t.startswith("#"):
        return False

    # Reject topics that look like imperative task descriptions
    # Pattern: starts with action verb + "the" (e.g. "Fix the ...", "Refactor the ...")
    task_verbs = {"fix", "refactor", "rewrite", "update", "implement", "create",
                  "build", "add", "remove", "delete", "clean", "migrate"}
    first_word = lowered.split()[0] if lowered.split() else ""
    if first_word in task_verbs and " the " in lowered:
        return False

    # Reject "Task XX" style strings (leftover from improvement_engine queue)
    if re.search(r"\btask\s*\d+\b", lowered):
        return False

    return True
