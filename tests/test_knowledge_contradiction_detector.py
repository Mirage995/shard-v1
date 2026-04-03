import logging
import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from knowledge_contradiction_detector import KnowledgeContradictionDetector


class TestKnowledgeContradictionDetector(unittest.TestCase):
    def _make_detector(self, db_rows=None, graph_rows=None, prerequisite_resolver=None):
        db_rows = db_rows or {}
        graph_rows = graph_rows or {}

        def db_query(sql, params=()):
            if "WHERE topic=?" in sql:
                return db_rows.get(("exact", params[0]), [])
            return db_rows.get(("related", None), [])

        def graph_query(topic):
            return graph_rows.get(topic, [])

        return KnowledgeContradictionDetector(
            db_query_fn=db_query,
            graphrag_query_fn=graph_query,
            prerequisite_resolver=prerequisite_resolver,
            logger=logging.getLogger("test.kcd"),
        )

    def test_1_no_contradictions_returns_empty_analysis(self):
        detector = self._make_detector()

        result = detector.analyze("binary search algorithm", predicted_score=5.5, category="algorithms")

        self.assertEqual(result["contradictions"], [])
        self.assertIsNone(result["recommended_action"])
        self.assertIsNone(result["highest_severity"])
        self.assertFalse(result["should_block"])
        self.assertEqual(result["warning_block"], "")

    def test_2_requires_missing_prerequisite_defer_payload_is_present(self):
        db_rows = {
            ("exact", "probability basics"): [
                {"topic": "probability basics", "score": 2.0, "certified": 0},
                {"topic": "probability basics", "score": 3.0, "certified": 0},
                {"topic": "probability basics", "score": 4.0, "certified": 0},
            ],
            ("exact", "linear algebra basics"): [
                {"topic": "linear algebra basics", "score": 2.5, "certified": 0},
            ],
        }
        detector = self._make_detector(
            db_rows=db_rows,
            prerequisite_resolver=lambda topic, category, cg: ["probability basics", "linear algebra basics"],
        )

        result = detector.analyze(
            "Integration of transformer attention and quantum fourier transform",
            predicted_score=6.8,
            category="machine_learning",
        )

        self.assertEqual(result["recommended_action"], "force_prerequisite")
        self.assertEqual(result["highest_severity"], "high")
        signal = next(s for s in result["contradictions"] if s["type"] == "requires_missing_prerequisite")
        self.assertEqual(signal["metadata"]["prerequisite_topic"], "probability basics")
        self.assertEqual(signal["metadata"]["deferred_topic"], "Integration of transformer attention and quantum fourier transform")
        self.assertIn("defer_reason", signal["metadata"])

    def test_3_prerequisite_tiebreak_prefers_simpler_topic(self):
        db_rows = {
            ("exact", "probability basics"): [
                {"topic": "probability basics", "score": 2.0, "certified": 0},
                {"topic": "probability basics", "score": 2.5, "certified": 0},
            ],
            ("exact", "sequence modeling basics"): [
                {"topic": "sequence modeling basics", "score": 1.5, "certified": 0},
                {"topic": "sequence modeling basics", "score": 2.0, "certified": 0},
            ],
        }
        detector = self._make_detector(
            db_rows=db_rows,
            prerequisite_resolver=lambda topic, category, cg: ["sequence modeling basics", "probability basics"],
        )

        result = detector.analyze("Integration of transformer attention and QFT", predicted_score=7.0)

        self.assertEqual(result["recommended_action"], "force_prerequisite")
        self.assertEqual(result["metadata"]["prerequisite_topic"], "probability basics")

    def test_4_historical_antipattern_conflict_warns(self):
        db_rows = {
            ("related", None): [
                {"topic": "stream socket and multi-head attention", "score": 0.8, "certified": 0},
                {"topic": "stream socket and async batching", "score": 2.1, "certified": 0},
                {"topic": "stream socket concurrency", "score": 3.5, "certified": 0},
            ],
        }
        detector = self._make_detector(
            db_rows=db_rows,
            prerequisite_resolver=lambda topic, category, cg: [],
        )

        result = detector.analyze("Integration of stream socket and multi-head attention", category="concurrency")

        self.assertEqual(result["recommended_action"], "warn")
        signal = next(s for s in result["contradictions"] if s["type"] == "historical_antipattern_conflict")
        self.assertEqual(signal["severity"], "medium")
        self.assertEqual(signal["metadata"]["history_failures"], 3)

    def test_5a_confidence_history_mismatch_lowers_score(self):
        db_rows = {
            ("related", None): [
                {"topic": "post-quantum kem and logistic regression", "score": 4.0, "certified": 0},
                {"topic": "post-quantum tls and lbyl", "score": 3.5, "certified": 0},
                {"topic": "post-quantum parser integration", "score": 4.5, "certified": 0},
            ],
        }
        detector = self._make_detector(db_rows=db_rows)

        result = detector.analyze("Integration of post-quantum KEM and logistic regression", predicted_score=7.0)

        signal = next(s for s in result["contradictions"] if s["type"] == "confidence_history_mismatch")
        self.assertEqual(signal["recommended_action"], "lower_confidence")
        self.assertEqual(signal["metadata"]["adjusted_predicted_score"], 5.5)

    def test_5b_confidence_history_mismatch_respects_floor(self):
        db_rows = {
            ("related", None): [
                {"topic": "post-quantum kem and logistic regression", "score": 3.5, "certified": 0},
                {"topic": "post-quantum tls and lbyl", "score": 4.0, "certified": 0},
                {"topic": "post-quantum parser integration", "score": 4.2, "certified": 0},
            ],
        }
        detector = self._make_detector(db_rows=db_rows)

        signal = detector._check_confidence_history_mismatch(
            "Integration of post-quantum KEM and logistic regression",
            predicted_score=4.2,
            category=None,
        )
        self.assertIsNone(signal)

        signal = detector._check_confidence_history_mismatch(
            "Integration of post-quantum KEM and logistic regression",
            predicted_score=7.0,
            category=None,
        )
        self.assertIsNotNone(signal)
        self.assertGreaterEqual(signal["metadata"]["adjusted_predicted_score"], 3.0)

        floored_signal = {
            "type": "confidence_history_mismatch",
            "severity": "medium",
            "topic": "x",
            "evidence": [],
            "recommended_action": "lower_confidence",
            "metadata": {
                "predicted_score": 4.1,
                "adjusted_predicted_score": max(3.0, 4.1 - 1.5),
            },
        }
        self.assertEqual(floored_signal["metadata"]["adjusted_predicted_score"], 3.0)

    def test_6_causal_conflict_uses_causes_conflict_relations(self):
        graph_rows = {
            "Integration of asyncio and threading": [
                {
                    "source_concept": "asyncio",
                    "target_concept": "threading",
                    "relation_type": "causes_conflict",
                    "context": "Mixing asyncio with raw threads causes race conditions",
                    "confidence": 0.9,
                }
            ]
        }
        detector = self._make_detector(graph_rows=graph_rows)

        result = detector.analyze("Integration of asyncio and threading")

        signal = next(s for s in result["contradictions"] if s["type"] == "causal_conflict_with_prior_knowledge")
        self.assertEqual(signal["recommended_action"], "warn")
        self.assertEqual(signal["severity"], "medium")

    def test_7_aggregation_force_prerequisite_beats_warn(self):
        db_rows = {
            ("exact", "probability basics"): [
                {"topic": "probability basics", "score": 2.0, "certified": 0},
            ],
            ("related", None): [
                {"topic": "quantum parser integration", "score": 3.0, "certified": 0},
                {"topic": "quantum sequence modeling", "score": 4.0, "certified": 0},
                {"topic": "quantum symbolic pipeline", "score": 2.5, "certified": 0},
            ],
        }
        detector = self._make_detector(
            db_rows=db_rows,
            prerequisite_resolver=lambda topic, category, cg: ["probability basics"],
        )

        result = detector.analyze("Integration of quantum models and parsing", predicted_score=6.8)

        self.assertEqual(result["recommended_action"], "force_prerequisite")
        self.assertEqual(result["highest_severity"], "high")

    def test_8_aggregation_lower_confidence_beats_warn(self):
        db_rows = {
            ("related", None): [
                {"topic": "post-quantum kem and logistic regression", "score": 4.0, "certified": 0},
                {"topic": "post-quantum tls and lbyl", "score": 3.5, "certified": 0},
                {"topic": "post-quantum parser integration", "score": 4.5, "certified": 0},
            ],
        }
        graph_rows = {
            "Integration of post-quantum KEM and logistic regression": [
                {
                    "source_concept": "post-quantum",
                    "target_concept": "runtime overhead",
                    "relation_type": "causes_conflict",
                    "context": "Post-quantum methods increase implementation complexity",
                    "confidence": 0.8,
                }
            ]
        }
        detector = self._make_detector(
            db_rows=db_rows,
            graph_rows=graph_rows,
            prerequisite_resolver=lambda topic, category, cg: [],
        )

        result = detector.analyze("Integration of post-quantum KEM and logistic regression", predicted_score=7.0)

        self.assertEqual(result["recommended_action"], "lower_confidence")
        self.assertIn("causal_conflict_with_prior_knowledge", result["warning_block"])

    def test_9_force_prerequisite_without_selected_prerequisite_degrades_to_warn(self):
        db_rows = {
            ("exact", "probability basics"): [
                {"topic": "probability basics", "score": 2.0, "certified": 0},
                {"topic": "probability basics", "score": 3.0, "certified": 0},
            ],
        }
        detector = self._make_detector(
            db_rows=db_rows,
            prerequisite_resolver=lambda topic, category, cg: ["probability basics"],
        )
        detector._select_best_prerequisite = lambda missing: None

        result = detector.analyze("Integration of transformer attention and QFT", predicted_score=6.8)

        signal = next(s for s in result["contradictions"] if s["type"] == "requires_missing_prerequisite")
        self.assertEqual(signal["recommended_action"], "warn")
        self.assertEqual(result["recommended_action"], "warn")
        self.assertNotIn("prerequisite_topic", signal["metadata"])


if __name__ == "__main__":
    unittest.main()
