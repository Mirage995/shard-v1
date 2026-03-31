"""strategy_compiler.py -- Transforms raw strategy text into grounded operational instructions.

Takes a strategy signal (text + confidence) and the current source code,
and produces a formatted instruction the LLM treats as a constraint, not context.

Confidence thresholds:
  >= 0.75  ->  HIGH: MANDATORY framing + failure condition
  0.60-0.74 -> MEDIUM: SUGGESTED framing
  < 0.60   ->  None (too weak -- gate should have dropped it already)

Grounding: heuristic function-name matching, no AST.
The goal is to anchor the strategy to specific functions in the current code
so the LLM knows WHERE to apply it, not just what the pattern is.
"""
from __future__ import annotations

import re

HIGH_THRESHOLD   = 0.75
MEDIUM_THRESHOLD = 0.60

# Words too generic to be useful for function matching
_STOPWORDS = {
    "this", "that", "with", "from", "your", "will", "have", "been", "when",
    "then", "also", "each", "make", "sure", "avoid", "apply", "always",
    "never", "should", "must", "return", "call", "function", "method",
    "code", "solution", "approach", "strategy", "issue", "problem", "test",
    "ensure", "implement", "check", "handle", "using", "used", "pass",
    "fail", "value", "object", "input", "output",
}


def _extract_relevant_functions(source: str, strategy_text: str) -> list[str]:
    """Heuristic: rank function definitions by keyword overlap with strategy text.

    Returns up to 2 relevant function names, or first function as fallback.
    """
    func_names = re.findall(r"def\s+(\w+)\s*\(", source)
    if not func_names:
        return []

    keywords = set(re.findall(r"\b\w{4,}\b", strategy_text.lower())) - _STOPWORDS

    scored: list[tuple[int, str]] = []
    for fn in func_names:
        fn_lower = fn.lower()
        score = sum(1 for kw in keywords if kw in fn_lower)
        # also check if strategy mentions the function name literally
        if fn_lower in strategy_text.lower():
            score += 3
        scored.append((score, fn))

    scored.sort(reverse=True)
    relevant = [fn for sc, fn in scored if sc > 0][:2]
    return relevant if relevant else [func_names[0]]


def _clean_strategy_text(text: str) -> str:
    """Strip aggregation headers and bullet formatting from build_strategy_signal output."""
    text = re.sub(r"\[STRATEGY GUIDANCE[^\]]*\]\s*\n+", "", text)
    text = re.sub(r"^[-•]\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def _to_numbered_steps(text: str) -> str:
    """Convert free-form strategy text into numbered action steps (max 5)."""
    # Split on sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip().rstrip(".,") for s in sentences if len(s.strip()) > 12]

    if not sentences:
        return f"1. {text}"
    return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences[:5]))


def compile(strategy_text: str, confidence: float, source_code: str = "") -> str | None:
    """Compile a raw strategy into an operational prompt instruction.

    Args:
        strategy_text : raw strategy content (from build_strategy_signal)
        confidence    : normalized score 0.0-1.0 (from Signal.confidence)
        source_code   : current buggy source code for function grounding

    Returns:
        Formatted instruction string, or None if confidence below threshold.
    """
    if confidence < MEDIUM_THRESHOLD:
        return None

    text = _clean_strategy_text(strategy_text)
    if not text:
        return None

    # Grounding: anchor instruction to specific functions
    relevant_fns = _extract_relevant_functions(source_code, text) if source_code else []
    if relevant_fns:
        fn_list = " and ".join(f"`{fn}()`" for fn in relevant_fns)
        grounding = f"Focus on: {fn_list}\n\n"
    else:
        grounding = ""

    steps = _to_numbered_steps(text)

    if confidence >= HIGH_THRESHOLD:
        return (
            "[STRATEGY - HIGH CONFIDENCE]\n\n"
            "You MUST apply this approach to fix the failing test(s) — apply ONLY if relevant to the current bug pattern:\n\n"
            f"{grounding}"
            f"{steps}\n\n"
            "FAILURE CONDITION:\n"
            "If this approach is not applied, the failing tests will not pass."
        )
    else:
        # MEDIUM confidence
        return (
            "[STRATEGY - SUGGESTED]\n\n"
            "Consider applying this approach:\n\n"
            f"{grounding}"
            f"{steps}"
        )
