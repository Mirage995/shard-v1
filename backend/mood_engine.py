"""mood_engine.py — Global affective state for SHARD.

Aggregates per-topic frustration, recent cert_rate, and momentum into a
single mood_score in [-1.0, +1.0].

  -1.0 = deeply frustrated, stagnating
   0.0 = neutral
  +1.0 = confident, flowing

mood_score is NOT a decoration — it injects directly into the study prompt,
changing how SHARD approaches the topic. High frustration → "approach from
scratch, ignore prior strategies". High confidence → "build on what you know".

Every value is derived from real SQLite data. Nothing is invented.
"""
from __future__ import annotations

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("shard.mood")

_ROOT      = Path(__file__).parent.parent.resolve()
_MOOD_FILE = _ROOT / "shard_memory" / "mood_state.json"

# ── Tunables ──────────────────────────────────────────────────────────────────

FRUSTRATION_WEIGHT  = 0.50   # biggest driver of bad mood
CERT_RATE_WEIGHT    = 0.35   # recent success rate
MOMENTUM_WEIGHT     = 0.15   # session momentum (stable/stagnating/growing)

FRUSTRATION_CAP     = 5      # hits at which frustration fully saturates mood
RECENT_CYCLES       = 10     # how many recent cycles to compute cert_rate from

MOOD_LABELS = {
    ( 0.5,  1.0): "confident",
    ( 0.1,  0.5): "focused",
    (-0.1,  0.1): "neutral",
    (-0.5, -0.1): "strained",
    (-1.0, -0.5): "frustrated",
}

# Text injected into study prompt per mood band
MOOD_PROMPT_HINTS = {
    "confident":  "You are in a confident state. Build on your existing knowledge and push deeper.",
    "focused":    "You are focused. Apply your known strategies methodically.",
    "neutral":    "Approach this topic with an open mind.",
    "strained":   "You have been struggling recently. Slow down, break the problem into smaller steps.",
    "frustrated": "You are in a high-frustration state on this domain. Ignore prior strategies entirely. Start from zero as if you have never seen this topic.",
}


class MoodEngine:
    """Compute and persist SHARD's global affective state."""

    def __init__(self):
        self._state      = self._load()
        self._last_label = self._state.get("label", "neutral")
        self._core_env   = None   # set by NightRunner after CognitionCore registration

    # ── Public API ────────────────────────────────────────────────────────────

    def compute(self, desire_engine=None, momentum: str = "stable") -> float:
        """Recompute mood_score from live data. Persists result.

        Returns mood_score in [-1.0, +1.0].
        """
        frustration_signal = self._frustration_signal(desire_engine)
        cert_signal        = self._cert_rate_signal()
        momentum_signal    = self._momentum_signal(momentum)

        score = round(
            - FRUSTRATION_WEIGHT * frustration_signal
            + CERT_RATE_WEIGHT   * cert_signal
            + MOMENTUM_WEIGHT    * momentum_signal,
            4,
        )
        score = max(-1.0, min(1.0, score))

        self._state["mood_score"]   = score
        self._state["label"]        = self._label(score)
        self._state["updated_at"]   = datetime.now().isoformat()
        self._state["components"]   = {
            "frustration": round(frustration_signal, 3),
            "cert_rate":   round(cert_signal, 3),
            "momentum":    round(momentum_signal, 3),
        }
        self._save()

        # Broadcast mood_shift if label changed — other modules react
        new_label = self._state["label"]
        if self._core_env is not None and new_label != self._last_label:
            self._core_env.broadcast(
                "mood_shift",
                {"from": self._last_label, "to": new_label, "score": score},
                source="mood_engine",
            )
            logger.info("[MOOD] mood_shift: %s → %s", self._last_label, new_label)
        self._last_label = new_label

        logger.info(
            "[MOOD] score=%.3f (%s) | frustration=%.2f cert=%.2f momentum=%.2f",
            score, self._state["label"],
            frustration_signal, cert_signal, momentum_signal,
        )
        return score

    def get_score(self) -> float:
        """Return last computed mood_score (no recompute)."""
        return float(self._state.get("mood_score", 0.0))

    def get_label(self) -> str:
        return self._state.get("label", "neutral")

    def get_prompt_hint(self) -> str:
        """Return the text to inject into the study prompt."""
        label = self.get_label()
        return MOOD_PROMPT_HINTS.get(label, MOOD_PROMPT_HINTS["neutral"])

    def get_status(self) -> dict:
        return dict(self._state)

    # ── CognitionCore interface ───────────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to events from other modules."""
        if event_type == "frustration_peak":
            # Immediate mood recompute when a topic hits chronic failure
            logger.debug("[MOOD] frustration_peak received — recomputing mood")
            self.compute(momentum=self._state.get("components", {}).get("momentum", 0.0))

        elif event_type == "momentum_changed":
            new_momentum = data.get("new", "stable")
            logger.debug("[MOOD] momentum_changed → %s — recomputing mood", new_momentum)
            self.compute(momentum=new_momentum)

    # ── Signal computation ────────────────────────────────────────────────────

    def _frustration_signal(self, desire_engine) -> float:
        """0.0 (no frustration) → 1.0 (max frustration)."""
        if desire_engine is None:
            return 0.0
        try:
            top = desire_engine.top_desire_topics(top_n=10)
            if not top:
                return 0.0
            total_hits = sum(t.get("frustration_hits", 0) for t in top)
            avg_hits   = total_hits / len(top)
            return min(1.0, avg_hits / FRUSTRATION_CAP)
        except Exception:
            return 0.0

    def _cert_rate_signal(self) -> float:
        """Weighted cert_rate from recent N cycles.

        Each certification is weighted by real difficulty:
          - curiosity_engine topic with difficulty < 0.3  → weight 0.5  (easy hybrid)
          - curated/improvement topic with difficulty > 0.7 → weight 1.5  (hard real topic)
          - everything else                               → weight 1.0

        This prevents easy hybrid topics from inflating the mood signal
        (Specification Gaming fix — backlog #17).
        """
        try:
            from shard_db import query as db_query
            rows = db_query(
                "SELECT certified, source, sig_difficulty FROM activation_log "
                "ORDER BY timestamp DESC LIMIT ?",
                (RECENT_CYCLES,),
            )
            if not rows:
                return 0.5
            total_weight = 0.0
            weighted_certs = 0.0
            for r in rows:
                diff = r["sig_difficulty"] or 0.5
                src  = r["source"] or ""
                # Compute weight
                if src == "curiosity_engine" and diff < 0.3:
                    w = 0.5   # easy hybrid — half credit
                elif diff > 0.7 and src in ("curated_list", "improvement_engine"):
                    w = 1.5   # hard real topic — bonus credit
                else:
                    w = 1.0
                total_weight += w
                if r["certified"]:
                    weighted_certs += w
            rate = weighted_certs / total_weight if total_weight > 0 else 0.5
            return round(rate, 4)
        except Exception:
            return 0.5

    def _momentum_signal(self, momentum: str) -> float:
        """Convert momentum string to [-1, +1] signal."""
        return {
            "growing":    1.0,
            "stable":     0.0,
            "stagnating": -1.0,
        }.get(momentum, 0.0)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _label(score: float) -> str:
        for (lo, hi), label in MOOD_LABELS.items():
            if lo <= score <= hi:
                return label
        return "neutral"

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            if _MOOD_FILE.exists():
                return json.loads(_MOOD_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"mood_score": 0.0, "label": "neutral", "updated_at": None, "components": {}}

    def _save(self) -> None:
        try:
            import tempfile, os
            _MOOD_FILE.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=_MOOD_FILE.parent, suffix=".tmp", delete=False,
            ) as tf:
                json.dump(self._state, tf, indent=2, ensure_ascii=False)
                tmp = tf.name
            os.replace(tmp, _MOOD_FILE)
        except Exception as e:
            logger.warning("[MOOD] save failed: %s", e)
