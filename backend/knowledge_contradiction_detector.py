"""knowledge_contradiction_detector.py -- operational contradiction gate for SHARD.

MVP detector used before study execution.

This module is intentionally rule-based:
- no LLM dependency
- no prompt injection
- deterministic outputs for testing and validation

It detects four operational contradiction types:
1. requires_missing_prerequisite
2. historical_antipattern_conflict
3. confidence_history_mismatch
4. causal_conflict_with_prior_knowledge

The detector returns structured signals plus an aggregated action that the
NightRunner can act on before spending a study cycle.

Note: skip_topic is part of the long-term contract but is not emitted by the
current MVP ruleset.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Dict, List, Optional


Severity = str
RecommendedAction = str


_SEVERITY_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

_ACTION_RANK = {
    "warn": 0,
    "lower_confidence": 1,
    "force_prerequisite": 2,
    "skip_topic": 3,
}

_KEYWORD_PREREQUISITES = {
    "post-quantum": ["cryptography basics", "probability basics"],
    "kem": ["cryptography basics"],
    "logistic regression": ["probability basics", "linear algebra basics"],
    "knn": ["probability basics", "machine learning basics"],
    "sgd": ["calculus basics", "machine learning basics"],
    "relu": ["linear algebra basics", "machine learning basics"],
    "hidden layers": ["linear algebra basics", "machine learning basics"],
    "transformer": ["linear algebra basics", "sequence modeling basics"],
    "attention": ["linear algebra basics", "sequence modeling basics"],
    "qft": ["probability basics", "linear algebra basics"],
    "quantum": ["probability basics", "linear algebra basics"],
    "bb84": ["probability basics", "cryptography basics"],
    "race condition": ["python thread safety basics", "async programming basics"],
    "thread": ["python thread safety basics"],
    "asyncio": ["async programming basics"],
    "stream socket": ["socket programming basics", "async programming basics"],
}


class KnowledgeContradictionDetector:
    """Operational contradiction detector used before topic study."""

    def __init__(
        self,
        db_query_fn: Callable[[str, tuple], List[dict]],
        graphrag_query_fn: Callable[[str], List[dict]],
        prerequisite_resolver: Optional[Callable[[str, Optional[str], object], List[str]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._db_query = db_query_fn
        self._graphrag_query = graphrag_query_fn
        self._resolve_prereqs = prerequisite_resolver
        self._logger = logger or logging.getLogger("shard.knowledge_contradiction_detector")

    def analyze(
        self,
        topic: str,
        predicted_score: Optional[float] = None,
        category: Optional[str] = None,
        capability_graph=None,
    ) -> dict:
        topic = (topic or "").strip()
        if not topic:
            return self._empty_analysis("")

        signals: List[dict] = []

        signal = self._check_requires_missing_prerequisite(topic, category, capability_graph)
        if signal:
            signals.append(signal)

        signal = self._check_historical_antipattern_conflict(topic, category)
        if signal:
            signals.append(signal)

        signal = self._check_confidence_history_mismatch(topic, predicted_score, category)
        if signal:
            signals.append(signal)

        signal = self._check_causal_conflict_with_prior_knowledge(topic)
        if signal:
            signals.append(signal)

        if not signals:
            return self._empty_analysis(topic)

        return self._aggregate(topic, signals)

    def _check_requires_missing_prerequisite(
        self,
        topic: str,
        category: Optional[str],
        capability_graph,
    ) -> Optional[dict]:
        prerequisites = self._infer_prerequisites(topic, category, capability_graph)
        if not prerequisites:
            return None

        missing: List[dict] = []
        for prereq in prerequisites:
            history = self._get_exact_topic_history(prereq)
            cert_count = sum(1 for row in history if row.get("certified"))
            fail_count = sum(1 for row in history if not row.get("certified"))
            if cert_count == 0:
                missing.append({
                    "topic": prereq,
                    "failures": fail_count,
                })

        if not missing:
            return None

        best = self._select_best_prerequisite(missing)
        if not best:
            return {
                "type": "requires_missing_prerequisite",
                "severity": "medium",
                "topic": topic,
                "evidence": [
                    f"Missing prerequisites inferred for topic '{topic}'",
                    "No concrete prerequisite topic could be selected",
                ],
                "recommended_action": "warn",
                "metadata": {
                    "missing_prerequisites": [m["topic"] for m in missing],
                },
            }

        return {
            "type": "requires_missing_prerequisite",
            "severity": "high",
            "topic": topic,
            "evidence": [
                f"Missing prerequisites inferred: {', '.join(m['topic'] for m in missing)}",
                f"Selected prerequisite '{best['topic']}' based on recent weakness",
            ],
            "recommended_action": "force_prerequisite",
            "metadata": {
                "prerequisite_topic": best["topic"],
                "deferred_topic": topic,
                "defer_reason": f"pending prerequisite: {best['topic']}",
                "missing_prerequisites": [m["topic"] for m in missing],
                "history_failures": best["failures"],
            },
        }

    def _check_historical_antipattern_conflict(
        self,
        topic: str,
        category: Optional[str],
    ) -> Optional[dict]:
        history = self._get_related_history(topic, category)
        failures = [row for row in history if not row.get("certified")]
        if len(failures) < 3:
            return None

        best_score = max((float(row.get("score") or 0.0) for row in failures), default=0.0)
        if best_score >= 5.0:
            return None

        examples = [row.get("topic", "") for row in failures[:3] if row.get("topic")]
        return {
            "type": "historical_antipattern_conflict",
            "severity": "medium",
            "topic": topic,
            "evidence": [
                f"{len(failures)} related failures found in recent history",
                f"Best failure score stayed below 5.0 ({best_score:.1f})",
            ],
            "recommended_action": "warn",
            "metadata": {
                "related_cluster": category,
                "history_failures": len(failures),
                "best_score": best_score,
                "similar_topics": examples,
            },
        }

    def _check_confidence_history_mismatch(
        self,
        topic: str,
        predicted_score: Optional[float],
        category: Optional[str],
    ) -> Optional[dict]:
        if predicted_score is None:
            return None

        history = self._get_related_history(topic, category)
        if not history:
            return None

        scores = [float(row.get("score") or 0.0) for row in history]
        avg_real = sum(scores) / len(scores) if scores else 0.0
        cert_rate = sum(1 for row in history if row.get("certified")) / len(history) if history else 0.0

        if predicted_score < 6.5 or avg_real > 4.5:
            return None

        adjusted = max(3.0, predicted_score - 1.5)
        return {
            "type": "confidence_history_mismatch",
            "severity": "medium",
            "topic": topic,
            "evidence": [
                f"Predicted score {predicted_score:.1f} is optimistic against historical average {avg_real:.1f}",
                f"Historical certification rate for related history is {cert_rate:.0%}",
            ],
            "recommended_action": "lower_confidence",
            "metadata": {
                "predicted_score": predicted_score,
                "adjusted_predicted_score": adjusted,
                "historical_avg_score": round(avg_real, 2),
                "historical_cert_rate": round(cert_rate, 4),
                "related_cluster": category,
            },
        }

    def _check_causal_conflict_with_prior_knowledge(self, topic: str) -> Optional[dict]:
        try:
            rows = self._graphrag_query(topic) or []
        except Exception as exc:
            self._logger.debug("[KCD] Graph query failed: %s", exc)
            rows = []

        if not rows:
            return None

        relevant = []
        topic_words = self._topic_words(topic)
        for row in rows:
            relation_type = str(row.get("relation_type", "")).strip().lower()
            if relation_type != "causes_conflict":
                continue
            haystack = " ".join([
                str(row.get("source_concept", "")),
                str(row.get("target_concept", "")),
                str(row.get("context", "")),
            ]).lower()
            if any(word in haystack for word in topic_words):
                relevant.append(row)

        if not relevant:
            return None

        severity = "high" if len(relevant) >= 2 else "medium"
        return {
            "type": "causal_conflict_with_prior_knowledge",
            "severity": severity,
            "topic": topic,
            "evidence": [
                f"{len(relevant)} prior causes_conflict relation(s) matched this topic",
            ],
            "recommended_action": "warn",
            "metadata": {
                "matching_relations": relevant[:5],
                "conflict_count": len(relevant),
            },
        }

    def _aggregate(self, topic: str, signals: List[dict]) -> dict:
        highest = max(signals, key=lambda s: _SEVERITY_RANK[s["severity"]])
        action_signal = max(signals, key=lambda s: _ACTION_RANK[s["recommended_action"]])
        return {
            "topic": topic,
            "contradictions": signals,
            "highest_severity": highest["severity"],
            "recommended_action": action_signal["recommended_action"],
            "should_block": action_signal["recommended_action"] == "skip_topic",
            "warning_block": self._render_warning_block(topic, signals, action_signal["recommended_action"]),
            "metadata": dict(action_signal.get("metadata") or {}),
        }

    def _render_warning_block(self, topic: str, signals: List[dict], action: str) -> str:
        lines = [
            "[CONTRADICTION WARNING]",
            f"Topic: {topic}",
        ]
        for signal in signals:
            lines.append(f"- {signal['type']} [{signal['severity']}]")
            for evidence in signal.get("evidence") or []:
                lines.append(f"  * {evidence}")
        lines.append(f"Recommended action: {action}")
        return "\n".join(lines)

    def _empty_analysis(self, topic: str) -> dict:
        return {
            "topic": topic,
            "contradictions": [],
            "highest_severity": None,
            "recommended_action": None,
            "should_block": False,
            "warning_block": "",
            "metadata": {},
        }

    def _infer_prerequisites(self, topic: str, category: Optional[str], capability_graph) -> List[str]:
        if self._resolve_prereqs:
            try:
                resolved = self._resolve_prereqs(topic, category, capability_graph) or []
                return [str(item).strip() for item in resolved if str(item).strip()]
            except Exception as exc:
                self._logger.debug("[KCD] prerequisite_resolver failed: %s", exc)

        lower_topic = topic.lower()
        found: List[str] = []
        for keyword, prereqs in _KEYWORD_PREREQUISITES.items():
            if keyword in lower_topic:
                found.extend(prereqs)

        if lower_topic.startswith("integration of ") and not found:
            found.append("python fundamentals review")

        deduped: List[str] = []
        seen = set()
        for prereq in found:
            if prereq not in seen:
                seen.add(prereq)
                deduped.append(prereq)
        return deduped

    def _select_best_prerequisite(self, missing: List[dict]) -> Optional[dict]:
        if not missing:
            return None
        return sorted(
            missing,
            key=lambda item: (-int(item.get("failures", 0)), len(str(item.get("topic", ""))), str(item.get("topic", ""))),
        )[0]

    def _get_exact_topic_history(self, topic: str) -> List[dict]:
        try:
            return self._db_query(
                "SELECT topic, score, certified FROM experiments WHERE topic=? ORDER BY timestamp DESC LIMIT 20",
                (topic,),
            ) or []
        except Exception as exc:
            self._logger.debug("[KCD] exact history query failed: %s", exc)
            return []

    def _get_related_history(self, topic: str, category: Optional[str]) -> List[dict]:
        try:
            rows = self._db_query(
                "SELECT topic, score, certified FROM experiments ORDER BY timestamp DESC LIMIT 200",
                (),
            ) or []
        except Exception as exc:
            self._logger.debug("[KCD] related history query failed: %s", exc)
            rows = []

        if not rows:
            return []

        topic_words = self._topic_words(topic)
        related = []
        for row in rows:
            candidate = str(row.get("topic", "")).lower()
            if not candidate:
                continue
            overlap = sum(1 for word in topic_words if word in candidate)
            if overlap >= 2:
                related.append(row)

        if related:
            return related

        if category:
            category_tokens = self._topic_words(category)
            category_related = []
            for row in rows:
                candidate = str(row.get("topic", "")).lower()
                if any(token in candidate for token in category_tokens):
                    category_related.append(row)
            return category_related

        return []

    @staticmethod
    def _topic_words(text: str) -> List[str]:
        words = re.findall(r"[a-z0-9\-]{3,}", (text or "").lower())
        stop = {
            "integration", "with", "and", "the", "for", "into", "from",
            "topic", "basics", "review", "python", "applied",
        }
        return [word for word in words if word not in stop]
