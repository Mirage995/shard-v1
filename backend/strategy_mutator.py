"""strategy_mutator.py — EvoScientist strategy mutation for SHARD (#14).

When a topic triggers pivot_on_chronic_block (≥3 consecutive failures or
near-miss variance loop), instead of deleting all strategies and starting
blank, we first synthesise an evolved hypothesis via LLM.

Algorithm:
  1. Take the top-2 strategies from the pre-pivot snapshot (best score first).
  2. Feed them to a single LLM call with an EvoScientist prompt.
  3. Store the evolved strategy in ChromaDB with metadata evolved=true.
  4. The caller then runs the normal wipe — the evolved strategy survives
     because it is stored AFTER the wipe.

Integration point (night_runner.py):
  After _pre_strategies snapshot, before pivot_on_chronic_block():

    evolved = await mutator.evolve(_pre_strategies, topic, study_agent._think_fast)
    _cleared = strategy_memory.pivot_on_chronic_block(topic)   # wipe old
    if evolved:
        await strategy_memory.store_strategy_async(           # store after wipe
            topic, evolved, outcome="evolved", score=5.0)
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Awaitable, Optional

logger = logging.getLogger("shard.strategy_mutator")

# Minimum / maximum length for a valid evolved strategy string
_MIN_LEN = 20
_MAX_LEN = 300


class StrategyMutator:
    """Synthesises an evolved strategy from two failing candidates.

    Stateless — safe to instantiate once and reuse across cycles.
    """

    # ── Prompt ────────────────────────────────────────────────────────────────

    _SYSTEM = (
        "You are EvoScientist, the hypothesis-evolution module of SHARD, "
        "an autonomous learning system. Your role is to synthesise ONE new "
        "operational hypothesis from two strategies that have failed."
    )

    _PROMPT_TMPL = """\
Topic: {topic}

Previous strategies tried (both failed to produce certification):
1. {s1}
2. {s2}

Task: synthesise ONE new operational hypothesis that:
- Preserves the valid insight from each strategy
- Resolves any logical contradictions between them
- Is expressed as a single actionable directive (20–100 words)
- Starts with an action verb (Use / Apply / Ensure / Combine / Replace …)

Return ONLY the hypothesis text. No explanation, no numbering, no markdown.
"""

    # ── Public API ─────────────────────────────────────────────────────────────

    async def evolve(
        self,
        strategies: list[dict],
        topic: str,
        llm_fn: Callable[[str], Awaitable[str]],
    ) -> Optional[str]:
        """Produce an evolved strategy string, or None on any failure.

        Args:
            strategies : pre-pivot strategy snapshot from night_runner
                         (list of dicts with at least a 'strategy' key
                          and an optional 'score' key).
            topic      : the study topic that triggered the pivot.
            llm_fn     : async callable (prompt: str) -> str, e.g.
                         study_agent._think_fast.

        Returns:
            Evolved strategy text (str) ready to store in ChromaDB, or
            None if evolution could not be performed.
        """
        top2 = self._select_top2(strategies)
        if len(top2) < 2:
            logger.debug(
                "[EVOSCI] Not enough strategies for topic '%s' (%d found) — skipping",
                topic[:60], len(top2),
            )
            return None

        s1, s2 = top2[0]["strategy"], top2[1]["strategy"]
        prompt = self._PROMPT_TMPL.format(topic=topic, s1=s1, s2=s2)

        try:
            raw = await llm_fn(prompt)
        except Exception as exc:
            logger.warning("[EVOSCI] LLM call failed for '%s': %s", topic[:60], exc)
            return None

        evolved = self._clean(raw)
        if not self._is_valid(evolved):
            logger.debug(
                "[EVOSCI] LLM output rejected for '%s': '%s'",
                topic[:60], (evolved or "")[:80],
            )
            return None

        logger.info(
            "[EVOSCI] Evolved strategy for '%s': '%s'",
            topic[:60], evolved[:100],
        )
        return evolved

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _select_top2(strategies: list[dict]) -> list[dict]:
        """Return the 2 strategies with the highest score, deduped by text."""
        seen: set[str] = set()
        unique = []
        for s in strategies:
            text = (s.get("strategy") or "").strip()
            if text and text not in seen:
                seen.add(text)
                unique.append(s)

        unique.sort(key=lambda s: float(s.get("score", 0.0)), reverse=True)
        return unique[:2]

    @staticmethod
    def _clean(raw: str | None) -> str:
        """Strip markdown fences, leading bullets/numbers, and excess whitespace."""
        if not raw:
            return ""
        text = re.sub(r"```[a-z]*|```", "", raw)
        text = re.sub(r"^\s*[\d\-\*\.]+\s*", "", text.strip())
        return text.strip()

    @staticmethod
    def _is_valid(text: str) -> bool:
        """True if text is a plausible actionable strategy string."""
        if not text or len(text) < _MIN_LEN or len(text) > _MAX_LEN:
            return False
        # Must start with an uppercase letter (action verb)
        if not text[0].isupper():
            return False
        return True
