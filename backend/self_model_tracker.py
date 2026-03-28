"""self_model_tracker.py — SHARD Self-Model via Prediction Error (no-LLM core).

Architecture:
  1. BEFORE study: predict expected score using global + contextual feature weights
  2. AFTER study:  error = actual - predicted
                   update global_weight[feature]  (overall correlation)
                   update contextual_weight[(feature, context)]  (context-specific)
  3. INCONSISTENCY DETECTION (no LLM):
                   gap = |global_weight[f] - contextual_weight[(f, ctx)]|
                   if gap > threshold → genuine inconsistency in self-model
                   the gap IS the question — no verbalization needed
  4. Inconsistencies are injected into session context as data, not prose.
     The LLM reads real numbers, not manufactured reflection.

Context dimensions tracked:
  - source:   how the topic was selected (improvement_engine, failure_replay, etc.)
  - domain:   coarse topic category inferred from keywords

LLM is NOT called for question generation.
LLM is only used downstream when the system acts on an inconsistency it measured.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("shard.self_model_tracker")

_ROOT      = Path(__file__).resolve().parent.parent
_MEM       = _ROOT / "shard_memory"
_PRED_PATH = _MEM / "predictions.jsonl"
_WGHT_PATH = _MEM / "self_weights.json"

# Prediction error threshold to flag a cycle as "interesting"
ERROR_THRESHOLD        = 1.8
INCONSISTENCY_THRESHOLD = 0.4   # |global - contextual| gap to flag
AUDIT_ERROR_THRESHOLD  = 2.0    # |actual - predicted| to trigger audit reflection (Behavior #12)
LEARNING_RATE          = 0.08
MAX_CONTEXT_ITEMS      = 4      # injected into session prompt

FEATURE_KEYS = [
    "had_episodic_context",
    "strategy_reused",
    "near_miss_history",
    "first_attempt",
    "graphrag_hits",
    "source_improvement",
    # Continuous signals from DesireEngine / difficulty history (0.0–1.0)
    # These scale the adjustment proportionally — higher value = stronger effect.
    "sig_difficulty",   # 1 - cert_rate: strongest negative predictor (r=-0.664)
    "sig_desire",       # composite desire score: frustration + curiosity + engagement
    "sig_graphrag",     # causal knowledge coverage for this topic
]

# Features that carry continuous float values (0.0–1.0) — adjustment scales with value.
# Boolean features use binary on/off (value treated as 1.0 when active).
_CONTINUOUS_FEATURES = {"sig_difficulty", "sig_desire", "sig_graphrag"}

# Coarse domain inference from topic keywords
_DOMAIN_KEYWORDS = {
    "algorithm":   ["algorithm", "complexity", "sorting", "search", "graph", "tree", "dynamic"],
    "debugging":   ["debug", "fix", "bug", "error", "exception", "failure", "crash"],
    "ml":          ["neural", "cnn", "transformer", "attention", "gradient", "model", "train"],
    "concurrency": ["async", "thread", "race", "lock", "concurrent", "coroutine", "asyncio"],
    "data":        ["sql", "json", "parse", "serialize", "injection", "sanitize", "query"],
    "oop":         ["class", "pattern", "factory", "observer", "singleton", "interface"],
}


def _infer_domain(topic: str) -> str:
    t = topic.lower()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return domain
    return "general"


class SelfModelTracker:
    """Tracks prediction errors and detects weight inconsistencies.
    No LLM calls for question generation — inconsistencies are measured, not invented.

    CognitionCore citizen — interests: session_complete
    """

    def __init__(self, think_fn=None):
        self._think             = think_fn
        self._weights           = self._load_weights()
        self._pending: List[Dict] = []
        self._current_mood      = "neutral"   # updated via mood_shift event
        self._identity_baseline = 0.0         # updated via identity_updated event

    # ── CognitionCore interface ───────────────────────────────────────────────

    def on_event(self, event_type: str, data: Dict, source: str = "") -> None:
        if event_type == "mood_shift":
            self._current_mood = data.get("to", "neutral")
            logger.debug("[SELF_MODEL_TRACKER] mood updated to '%s'", self._current_mood)
        elif event_type == "identity_updated":
            # Shift prediction baseline by self_esteem: esteem 0.5=neutral, 1.0=+0.5, 0.0=-0.5
            esteem = data.get("self_esteem", 0.5)
            self._identity_baseline = round((esteem - 0.5) * 1.0, 3)
            logger.debug("[SELF_MODEL_TRACKER] identity_updated → baseline_adj=%.3f", self._identity_baseline)

    # ── Core API ──────────────────────────────────────────────────────────────

    def predict_before(self, topic: str, features: Dict[str, Any], source: str = "") -> float:
        """Predict score before study using global + contextual weights."""
        context = self._make_context(source, topic)
        base    = self._base_score(topic)

        adjustment = 0.0
        for key in FEATURE_KEYS:
            val = features.get(key, False)
            # Continuous features scale the weight by their value (0.0–1.0).
            # Boolean features use 1.0 when active, 0.0 when not.
            if key in _CONTINUOUS_FEATURES:
                scale = float(val) if val is not None else 0.0
            else:
                scale = 1.0 if (bool(val) if isinstance(val, bool) else float(val) > 0) else 0.0
            if scale == 0.0:
                continue
            # Prefer contextual weight, fall back to global
            ctx_key = (key, context)
            if ctx_key in self._weights["contextual"]:
                adjustment += self._weights["contextual"][ctx_key] * scale
            else:
                adjustment += self._weights["global"].get(key, 0.0) * scale

        # Mood modifier: frustrated → -0.5, confident/focused → +0.3, else 0
        _mood_mod = {"frustrated": -0.5, "strained": -0.2, "confident": 0.3, "focused": 0.1}.get(self._current_mood, 0.0)
        predicted = round(max(0.0, min(10.0, base + adjustment + self._identity_baseline + _mood_mod)), 2)

        self._pending.append({
            "topic": topic, "features": features,
            "predicted": predicted, "context": context,
        })
        logger.debug(
            "[SELF_MODEL] predict '%s' ctx=%s: base=%.1f adj=%.2f → %.2f",
            topic, context, base, adjustment, predicted,
        )
        return predicted

    def record_outcome(
        self,
        topic: str,
        actual_score: float,
        certified: bool,
        desire_engine=None,
        goal_engine=None,
    ) -> Optional[Dict]:
        """Record actual outcome, update weights, detect inconsistencies.
        Returns inconsistency dict if a significant gap was found, else None.
        No LLM call."""
        pending = next((p for p in self._pending if p["topic"] == topic), None)
        if not pending:
            return None
        self._pending = [p for p in self._pending if p["topic"] != topic]

        predicted = pending["predicted"]
        features  = pending["features"]
        context   = pending["context"]
        error     = round(actual_score - predicted, 2)

        # Update weights
        self._update_weights(features, context, error)

        # Detect inconsistencies in updated weights
        inconsistencies = self._detect_inconsistencies(features, context)

        # Persist prediction record
        self._save_prediction({
            "topic": topic, "predicted": predicted, "actual": actual_score,
            "error": error, "certified": certified,
            "features": features, "context": context,
            "timestamp": datetime.now().isoformat(),
        })

        # ── AUDIT BLINDNESS check (Behavior #12) ──────────────────────────────
        # When the gap between prediction and reality is ≥ 2.0, write a
        # structured audit record — no LLM. The fact IS the reflection.
        if abs(error) >= AUDIT_ERROR_THRESHOLD:
            self._save_audit_reflection(topic, predicted, actual_score, error, certified)

        if not inconsistencies:
            return None

        # Pick the largest gap
        worst = max(inconsistencies, key=lambda x: x["gap"])

        logger.info(
            "[SELF_MODEL] Inconsistency detected — feature '%s': "
            "global=%.2f  contextual[%s]=%.2f  gap=%.2f",
            worst["feature"], worst["global_w"],
            worst["context"], worst["contextual_w"], worst["gap"],
        )

        # Act on desire_engine: boost curiosity for this topic
        if desire_engine:
            try:
                ds = desire_engine._get_or_create(topic)
                ds.curiosity_pull = round(min(1.0, ds.curiosity_pull + 0.3), 4)
                ds.last_updated   = datetime.now().isoformat()
                desire_engine._save()
            except Exception as exc:
                logger.debug("[SELF_MODEL] desire boost failed: %s", exc)

        # Act on goal_engine: create investigation goal (no LLM — pure data)
        if goal_engine:
            try:
                goal_engine.create_goal(
                    title=(
                        f"investigate: why does '{worst['feature']}' "
                        f"behave differently in '{worst['context']}'?"
                    ),
                    description=(
                        f"Weight inconsistency detected:\n"
                        f"  feature: {worst['feature']}\n"
                        f"  global weight:     {worst['global_w']:+.3f}\n"
                        f"  contextual weight: {worst['contextual_w']:+.3f}  (ctx: {worst['context']})\n"
                        f"  gap: {worst['gap']:.3f}\n"
                        f"  detected on topic: {topic}  (error: {error:+.2f})"
                    ),
                    priority=0.7,
                    goal_type="investigation",
                    domain_keywords=[worst["feature"].replace("_", " ")],
                )
            except Exception as exc:
                logger.debug("[SELF_MODEL] goal creation failed: %s", exc)

        self._save_inconsistency(worst, topic, error)
        return worst

    # ── Audit reflection (Behavior #12 fix) ──────────────────────────────────

    def _save_audit_reflection(
        self,
        topic: str,
        predicted: float,
        actual: float,
        error: float,
        certified: bool,
    ) -> None:
        """Write a structured audit record when prediction gap ≥ 2.0.
        No LLM — the numbers are the reflection.
        Saved to session_reflections.jsonl with type='prediction_audit'."""
        try:
            direction = "underconfident" if error > 0 else "overconfident"
            severity  = "severe" if abs(error) >= 4.0 else "significant"
            record = {
                "type":      "prediction_audit",
                "ts":        datetime.now().isoformat(),
                "topic":     topic,
                "predicted": predicted,
                "actual":    actual,
                "error":     error,
                "certified": certified,
                "direction": direction,
                "severity":  severity,
            }
            rpath = _MEM / "session_reflections.jsonl"
            _MEM.mkdir(parents=True, exist_ok=True)
            with rpath.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.warning(
                "[AUDIT] %s prediction on '%s': predicted=%.1f actual=%.1f gap=%+.1f",
                direction.upper(), topic, predicted, actual, error,
            )
        except Exception as exc:
            logger.debug("[AUDIT] save_audit_reflection failed: %s", exc)

    # ── Inconsistency detection (pure math, no LLM) ───────────────────────────

    def _detect_inconsistencies(
        self, features: Dict, context: str
    ) -> List[Dict]:
        """Compare global vs contextual weights for active features.
        Returns list of gaps sorted by magnitude."""
        gaps = []
        for key in FEATURE_KEYS:
            val    = features.get(key, False)
            active = bool(val) if isinstance(val, bool) else float(val) > 0
            if not active:
                continue

            ctx_key     = (key, context)
            global_w    = self._weights["global"].get(key, 0.0)
            contextual_w = self._weights["contextual"].get(ctx_key)

            if contextual_w is None:
                continue   # no contextual data yet — no inconsistency to detect

            gap = abs(global_w - contextual_w)
            if gap >= INCONSISTENCY_THRESHOLD:
                gaps.append({
                    "feature":      key,
                    "context":      context,
                    "global_w":     round(global_w, 4),
                    "contextual_w": round(contextual_w, 4),
                    "gap":          round(gap, 4),
                })

        return sorted(gaps, key=lambda x: x["gap"], reverse=True)

    # ── Weight update ─────────────────────────────────────────────────────────

    def _update_weights(self, features: Dict, context: str, error: float) -> None:
        g = self._weights["global"]
        c = self._weights["contextual"]

        for key in FEATURE_KEYS:
            val = features.get(key, False)
            if key in _CONTINUOUS_FEATURES:
                scale = float(val) if val is not None else 0.0
            else:
                scale = 1.0 if (bool(val) if isinstance(val, bool) else float(val) > 0) else 0.0
            if scale == 0.0:
                continue

            # Scale learning step by feature magnitude for continuous signals.
            step = LEARNING_RATE * error * scale

            # Global weight update
            g[key] = round(g.get(key, 0.0) + step, 4)

            # Contextual weight update
            ctx_key = (key, context)
            c[ctx_key] = round(c.get(ctx_key, 0.0) + step, 4)

        self._save_weights()

    # ── Context injection ─────────────────────────────────────────────────────

    @staticmethod
    def get_context_block(n: int = MAX_CONTEXT_ITEMS) -> str:
        """Inject known weight inconsistencies as plain data — no LLM-generated text.
        The LLM reads real numbers, not manufactured reflection."""
        ipath = _MEM / "self_inconsistencies.jsonl"
        if not ipath.exists():
            return ""
        try:
            lines = ipath.read_text(encoding="utf-8").strip().splitlines()
            recent = []
            for line in reversed(lines):
                try:
                    recent.append(json.loads(line))
                except Exception:
                    pass
                if len(recent) >= n:
                    break
            if not recent:
                return ""
            parts = ["=== SHARD SELF-MODEL INCONSISTENCIES (measured, not invented) ==="]
            for item in reversed(recent):
                ts  = item.get("timestamp", "")[:10]
                f   = item.get("feature", "")
                ctx = item.get("context", "")
                gw  = item.get("global_w", 0)
                cw  = item.get("contextual_w", 0)
                gap = item.get("gap", 0)
                parts.append(
                    f"[{ts}] '{f}': global={gw:+.3f}  in '{ctx}'={cw:+.3f}  gap={gap:.3f}"
                )
            parts.append(
                "These are real weight gaps — the model behaves differently "
                "in specific contexts than it does globally."
            )
            return "\n".join(parts)
        except Exception:
            return ""

    def get_weight_summary(self) -> Dict:
        """Return current weights for logging / frontend display."""
        return {
            "global": {k: v for k, v in self._weights["global"].items() if abs(v) > 0.01},
            "contextual": {
                f"{k[0]}@{k[1]}": v
                for k, v in self._weights["contextual"].items()
                if abs(v) > 0.01
            },
        }

    # ── Base score ────────────────────────────────────────────────────────────

    def _base_score(self, topic: str) -> float:
        try:
            from shard_db import query as db_query
            rows = db_query(
                "SELECT score FROM experiments WHERE topic=? AND score IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 5", (topic,),
            )
            if rows:
                scores = [r["score"] for r in rows if r["score"] is not None]
                return round(sum(scores) / len(scores), 2) if scores else 5.0
            global_row = db_query("SELECT avg_score FROM global_stats")
            if global_row and global_row[0].get("avg_score"):
                return round(float(global_row[0]["avg_score"]), 2)
        except Exception:
            pass
        return 5.0

    # ── Context key construction ──────────────────────────────────────────────

    @staticmethod
    def _make_context(source: str, topic: str) -> str:
        domain = _infer_domain(topic)
        src    = source.replace(" ", "_") if source else "unknown"
        return f"{src}:{domain}"

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_weights(self) -> Dict:
        try:
            if _WGHT_PATH.exists():
                raw = json.loads(_WGHT_PATH.read_text(encoding="utf-8"))
                # Convert contextual keys from "f|ctx" string back to (f, ctx) tuples
                ctx = {
                    tuple(k.split("|", 1)): v
                    for k, v in raw.get("contextual", {}).items()
                }
                return {"global": raw.get("global", {}), "contextual": ctx}
        except Exception:
            pass
        return {"global": {k: 0.0 for k in FEATURE_KEYS}, "contextual": {}}

    def _save_weights(self) -> None:
        try:
            _MEM.mkdir(parents=True, exist_ok=True)
            # Serialize tuple keys as "f|ctx" strings for JSON
            serializable = {
                "global": self._weights["global"],
                "contextual": {
                    f"{k[0]}|{k[1]}": v
                    for k, v in self._weights["contextual"].items()
                },
            }
            tmp = _WGHT_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(_WGHT_PATH))
        except Exception as exc:
            logger.warning("[SELF_MODEL] Failed to save weights: %s", exc)

    def _save_prediction(self, record: Dict) -> None:
        try:
            _MEM.mkdir(parents=True, exist_ok=True)
            with _PRED_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("[SELF_MODEL] Failed to save prediction: %s", exc)

    def _save_inconsistency(self, gap: Dict, topic: str, error: float) -> None:
        try:
            _MEM.mkdir(parents=True, exist_ok=True)
            ipath = _MEM / "self_inconsistencies.jsonl"
            record = {**gap, "topic": topic, "error": error,
                      "timestamp": datetime.now().isoformat()}
            with ipath.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("[SELF_MODEL] Failed to save inconsistency: %s", exc)
