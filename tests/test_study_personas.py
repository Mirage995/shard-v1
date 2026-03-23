"""Tests for study_personas.py — persona selection and outcome recording."""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from study_personas import (
    select_persona, record_outcome,
    PersonaType, PersonaConfig,
    _CATEGORY_DEFAULTS, _PERSONA_CONFIGS,
)

_EMPTY_HISTORY = {}


class TestSelectPersona(unittest.TestCase):
    """select_persona — category defaults, history winners, fallback."""

    def _select(self, topic, category=None, history=None):
        hist = history or _EMPTY_HISTORY
        with patch("study_personas._load_history", return_value=hist):
            return select_persona(topic, category)

    # ── Category defaults ─────────────────────────────────────────────────────

    def test_algorithms_returns_theoretical(self):
        cfg = self._select("Dijkstra sorting", category="algorithms")
        self.assertEqual(cfg.persona, PersonaType.THEORETICAL)

    def test_cryptography_returns_theoretical(self):
        cfg = self._select("RSA encryption", category="cryptography")
        self.assertEqual(cfg.persona, PersonaType.THEORETICAL)

    def test_web_returns_hacker(self):
        cfg = self._select("FastAPI routing", category="web")
        self.assertEqual(cfg.persona, PersonaType.HACKER)

    def test_python_returns_hacker(self):
        cfg = self._select("Python decorators", category="python")
        self.assertEqual(cfg.persona, PersonaType.HACKER)

    def test_ml_returns_visual(self):
        cfg = self._select("neural network layers", category="ml")
        self.assertEqual(cfg.persona, PersonaType.VISUAL)

    def test_architecture_returns_visual(self):
        cfg = self._select("microservices design", category="architecture")
        self.assertEqual(cfg.persona, PersonaType.VISUAL)

    def test_unknown_category_returns_hacker_default(self):
        cfg = self._select("some obscure topic", category="xyzunknown")
        self.assertEqual(cfg.persona, PersonaType.HACKER)

    def test_no_category_returns_hacker_default(self):
        cfg = self._select("random topic")
        self.assertEqual(cfg.persona, PersonaType.HACKER)

    # ── Topic keyword matching ────────────────────────────────────────────────

    def test_topic_contains_algorithm_keyword(self):
        cfg = self._select("binary search algorithms", category="general")
        self.assertEqual(cfg.persona, PersonaType.THEORETICAL)

    def test_topic_contains_neural_keyword(self):
        cfg = self._select("neural network backprop", category="general")
        self.assertEqual(cfg.persona, PersonaType.VISUAL)

    # ── History winners ───────────────────────────────────────────────────────

    def test_uses_history_winner_when_available(self):
        history = {"winners": {"python": "theoretical"}}
        cfg = self._select("Python async", category="python", history=history)
        self.assertEqual(cfg.persona, PersonaType.THEORETICAL)

    def test_ignores_invalid_history_winner(self):
        history = {"winners": {"python": "nonexistent_persona"}}
        cfg = self._select("Python async", category="python", history=history)
        # Falls back to category default
        self.assertEqual(cfg.persona, PersonaType.HACKER)

    def test_history_winner_overrides_category_default(self):
        """If history says HACKER wins for algorithms, use HACKER."""
        history = {"winners": {"algorithms": "hacker"}}
        cfg = self._select("Dijkstra", category="algorithms", history=history)
        self.assertEqual(cfg.persona, PersonaType.HACKER)

    # ── Returned config fields ────────────────────────────────────────────────

    def test_hacker_has_3_sandbox_retries(self):
        cfg = self._select("Flask routing", category="web")
        self.assertEqual(cfg.sandbox_retries, 3)

    def test_theoretical_has_1_sandbox_retry(self):
        cfg = self._select("Big O notation", category="algorithms")
        self.assertEqual(cfg.sandbox_retries, 1)

    def test_visual_tier_is_2(self):
        cfg = self._select("transformer architecture", category="ml")
        self.assertEqual(cfg.tier, 2)

    def test_hacker_tier_is_1(self):
        cfg = self._select("pytest fixtures", category="testing")
        self.assertEqual(cfg.tier, 1)

    def test_returns_persona_config_instance(self):
        cfg = self._select("something")
        self.assertIsInstance(cfg, PersonaConfig)

    def test_strategy_hint_not_empty(self):
        for persona_type in PersonaType:
            cfg = _PERSONA_CONFIGS[persona_type]
            self.assertTrue(cfg.strategy_hint)


class TestRecordOutcome(unittest.TestCase):
    """record_outcome — updates winner tracking in history."""

    def _record(self, topic, category, persona, certified, score, initial_history=None):
        saved = {}

        def mock_load():
            return initial_history or {}

        def mock_save(h):
            saved.update(h)

        with patch("study_personas._load_history", side_effect=mock_load):
            with patch("study_personas._save_history", side_effect=mock_save):
                record_outcome(topic, category, persona, certified, score)
        return saved

    def test_records_success_increments_certified(self):
        history = self._record(
            "asyncio", "python", PersonaType.HACKER, certified=True, score=8.5
        )
        cat_stats = history.get("categories", {}).get("python", {})
        hacker_stats = cat_stats.get("hacker", {})
        self.assertEqual(hacker_stats.get("certified", 0), 1)
        self.assertEqual(hacker_stats.get("attempts", 0), 1)

    def test_records_failure_increments_attempts_only(self):
        history = self._record(
            "RSA", "cryptography", PersonaType.THEORETICAL, certified=False, score=4.0
        )
        cat_stats = history.get("categories", {}).get("cryptography", {})
        theoretical_stats = cat_stats.get("theoretical", {})
        self.assertEqual(theoretical_stats.get("certified", 0), 0)
        self.assertEqual(theoretical_stats.get("attempts", 0), 1)

    def test_winner_set_after_enough_attempts(self):
        """After >= 2 attempts, the persona with best metric becomes winner."""
        # Pre-populate: hacker has 2 certified out of 2 attempts for web
        pre = {
            "categories": {
                "web": {
                    "hacker": {"certified": 2, "total_score": 18.0, "attempts": 2}
                }
            },
            "winners": {}
        }
        history = self._record("Flask", "web", PersonaType.HACKER, certified=True, score=9.0, initial_history=pre)
        # 3 certified out of 3 attempts → cert_rate=1.0 → crowned winner
        self.assertEqual(history.get("winners", {}).get("web"), "hacker")

    def test_save_called(self):
        """record_outcome must always call _save_history."""
        save_mock = MagicMock()
        with patch("study_personas._load_history", return_value={}):
            with patch("study_personas._save_history", save_mock):
                record_outcome("topic", "cat", PersonaType.HACKER, True, 7.0)
        save_mock.assert_called_once()

    def test_none_category_handled(self):
        """None category should not crash."""
        history = self._record("topic", None, PersonaType.HACKER, True, 7.0)
        self.assertIn("categories", history)


class TestPersonaConfigDefaults(unittest.TestCase):
    """Validate _PERSONA_CONFIGS has all PersonaType values."""

    def test_all_persona_types_have_config(self):
        for pt in PersonaType:
            self.assertIn(pt, _PERSONA_CONFIGS)

    def test_all_configs_have_required_fields(self):
        for pt, cfg in _PERSONA_CONFIGS.items():
            self.assertIsNotNone(cfg.strategy_hint, f"{pt} missing strategy_hint")
            self.assertIsInstance(cfg.tier, int, f"{pt} tier not int")
            self.assertGreater(cfg.sandbox_retries, 0, f"{pt} invalid sandbox_retries")

    def test_category_defaults_map_to_valid_personas(self):
        for cat, persona in _CATEGORY_DEFAULTS.items():
            self.assertIn(persona, _PERSONA_CONFIGS, f"Category {cat} maps to unknown persona {persona}")


if __name__ == "__main__":
    unittest.main()
