"""signal_gate.py -- Attention-based signal filtering for SHARD.

Each information source produces a Signal with a confidence score.
The gate ranks them and lets only the top-K into the prompt.

This shifts control: LLM no longer decides what matters from a wall of text.
SHARD decides what matters, then sends the LLM a focused brief.

Signal types and base weights:
  diagnostic      1.5  -- targeted, actionable, breaks attractors
  semantic_memory 1.2  -- past fixes for similar errors
  self_profile    1.0  -- identity context, always grounding
  kb              1.0  -- background knowledge
  episodic        0.8  -- past sessions, useful but verbose

Diagnostic weights are dynamic: loaded from shard_memory/diagnostic_weights.json.
improvement_engine is the sole writer of that file (based on outcome after each run).

#22 Cross-Task Router: build_strategy_signal() now accepts topic + error_text,
applies cluster-based filtering/boosting via cross_task_router.apply_routing().
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from cross_task_router import apply_routing

logger = logging.getLogger("shard.signal_gate")

# ── Static type weights ───────────────────────────────────────────────────────
_WEIGHTS: dict[str, float] = {
    "diagnostic":      1.5,
    "semantic_memory": 1.2,
    "strategy":        1.1,   # aggregated past strategies -- specific, competitive
    "self_profile":    1.0,
    "kb":              1.0,
    "episodic":        0.8,
}

_WEIGHTS_FILE = Path(__file__).resolve().parent.parent / "shard_memory" / "diagnostic_weights.json"


def load_diagnostic_weights() -> dict[str, float]:
    """Load per-diagnostic learned weights from file. Returns {} on any error."""
    try:
        if _WEIGHTS_FILE.exists():
            data = json.loads(_WEIGHTS_FILE.read_text(encoding="utf-8"))
            return {k: float(v.get("weight", 1.5)) for k, v in data.items()}
    except Exception as e:
        logger.debug("[signal_gate] Could not load diagnostic_weights.json: %s", e)
    return {}



@dataclass
class Signal:
    content:    str
    confidence: float   # 0.0 – 1.0, assigned by the producer
    type:       str     # one of the keys in _WEIGHTS
    source:     str     # human-readable label for logging

    def score(self, diag_weights: dict[str, float] | None = None) -> float:
        """Final ranking score = confidence x type_weight x diagnostic_weight (if applicable)."""
        base = self.confidence * _WEIGHTS.get(self.type, 1.0)
        if self.type == "diagnostic" and diag_weights:
            # source holds the diagnostic name (e.g. "IDEMPOTENCY")
            base *= diag_weights.get(self.source, 1.0)
        return base


def gate(signals: list[Signal], top_k: int = 3, min_confidence: float = 0.1) -> list[Signal]:
    """Return top-K signals by score.

    Loads dynamic diagnostic weights once per call.
    Signals below min_confidence or with empty content are dropped before ranking.
    """
    diag_weights = load_diagnostic_weights()
    valid = [s for s in signals if s.confidence >= min_confidence and s.content.strip()]
    return sorted(valid, key=lambda s: s.score(diag_weights), reverse=True)[:top_k]


def build_context(signals: list[Signal]) -> str:
    """Concatenate selected signals into a single context string."""
    return "\n\n".join(s.content.strip() for s in signals)


def strategy_multiplier(avg_score: float, success_rate: float | None = None) -> float:
    """Confidence multiplier from a strategy's track record.

    Range clamped [0.8, 1.5] -- prevents uncontrolled dominance.

    Args:
        avg_score    : average score of retrieved strategies (0-10 scale)
        success_rate : fraction of past runs that succeeded (0.0-1.0), optional
    """
    base = 0.9 + (avg_score / 10.0) * 0.4   # 0.90 – 1.30
    if success_rate is not None:
        base *= (0.9 + success_rate * 0.2)    # x0.90 – x1.10
    return max(0.8, min(1.5, round(base, 3)))


def build_strategy_signal(
    strategies: list[dict],
    topic: str = "",
    error_text: str = "",
) -> "Signal | None":
    """Aggregate top-N strategy results into ONE Signal for the gate.

    Args:
        strategies: list of dicts from strategy_memory.query() with keys
                    "strategy", "topic", "score" (0-10 range), "outcome".
        topic     : current study/benchmark topic -- used for cluster routing (#22)
        error_text: optional error message -- used for cluster detection (#22)

    Returns a single Signal or None if no usable strategies found.
    Confidence is boosted by strategy_multiplier() based on avg_score and
    success_rate -- strategies with a strong track record rank higher.
    Cluster boost (cross_task_router) is applied last, after track-record mult.
    """
    if not strategies:
        return None

    # #22 Cross-Task Router: filter blacklisted/penalized, get cluster boost
    filtered, cluster_boost = apply_routing(strategies, topic, error_text)
    if not filtered:
        return None

    # Cap at top-3 by score -- cross-inject can inflate to 9+ entries
    filtered = sorted(filtered, key=lambda s: float(s.get("score", 0)), reverse=True)[:3]

    scores = [float(s.get("score", 0)) for s in filtered]
    avg = sum(scores) / len(scores)

    confidence = round(max(0.0, min(1.0, avg / 10.0)), 3)
    if confidence < 0.1:
        return None

    # Track record multiplier -- boost confidence based on past performance
    successes = sum(1 for s in filtered if str(s.get("outcome", "")).lower() == "success")
    sr = round(successes / len(filtered), 3)
    mult = strategy_multiplier(avg, sr)

    # Apply cluster boost last (cluster_boost already encodes near-miss)
    confidence = round(max(0.0, min(1.0, confidence * mult * cluster_boost)), 3)

    lines = ["[STRATEGY GUIDANCE -- from past successful sessions]", ""]
    for s in filtered:
        strat_text = s.get("strategy", "").strip()
        if strat_text:
            lines.append(f"- {strat_text[:200]}")
    lines.append("")

    content = "\n".join(lines)
    logger.info(
        "[gate] strategy signal: topic='%s' cluster_boost=%.2f mult=%.3f confidence=%.3f (%d strategies)",
        topic[:50], cluster_boost, mult, confidence, len(filtered),
    )
    return Signal(
        content=content,
        confidence=confidence,
        type="strategy",
        source=(
            f"{len(filtered)} past strategies "
            f"(avg={avg:.1f}, sr={sr:.2f}, mult={mult:.3f}, boost={cluster_boost:.2f})"
        ),
    )


def log_gate_result(selected: list[Signal], all_signals: list[Signal]) -> None:
    """Print which signals were selected and which were dropped."""
    diag_weights = load_diagnostic_weights()
    selected_set = set(id(s) for s in selected)
    for s in all_signals:
        tag = "Selected" if id(s) in selected_set else "Dropped "
        try:
            print(f"  [gate] {tag}: {s.type:<16} score={s.score(diag_weights):.2f}  ({len(s.content):,} chars)  [{s.source}]")
        except Exception:
            pass
