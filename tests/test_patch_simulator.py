"""Tests for patch_simulator.py — static diff analysis and risk scoring."""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Stub ArchitectureMap before import so _find_dependents degrades gracefully
sys.modules["architecture_map"] = MagicMock()
sys.modules["backend.architecture_map"] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from patch_simulator import (
    _extract_public_api,
    _analyze_diff,
    _compute_risk_level,
    _build_summary,
    _count_required_args,
    simulate_patch_sync,
    SimulationReport,
)


# ── _extract_public_api ───────────────────────────────────────────────────────

class TestExtractPublicApi(unittest.TestCase):

    def test_extracts_regular_function(self):
        code = "def foo(a, b): pass"
        api = _extract_public_api(code)
        self.assertIn("foo", api["functions"])
        self.assertEqual(api["functions"]["foo"], ["a", "b"])

    def test_extracts_async_function(self):
        code = "async def bar(x, y=1): pass"
        api = _extract_public_api(code)
        self.assertIn("bar", api["functions"])
        self.assertEqual(api["functions"]["bar"], ["x", "y"])

    def test_skips_private_functions(self):
        code = "def _private(): pass\ndef public(): pass"
        api = _extract_public_api(code)
        self.assertNotIn("_private", api["functions"])
        self.assertIn("public", api["functions"])

    def test_extracts_class_and_methods(self):
        code = "class MyClass:\n    def method_a(self): pass\n    def method_b(self): pass"
        api = _extract_public_api(code)
        self.assertIn("MyClass", api["classes"])
        self.assertIn("method_a", api["classes"]["MyClass"])
        self.assertIn("method_b", api["classes"]["MyClass"])

    def test_skips_private_methods(self):
        code = "class Foo:\n    def _hidden(self): pass\n    def visible(self): pass"
        api = _extract_public_api(code)
        self.assertNotIn("_hidden", api["classes"]["Foo"])
        self.assertIn("visible", api["classes"]["Foo"])

    def test_skips_private_class(self):
        code = "class _Internal:\n    def method(self): pass"
        api = _extract_public_api(code)
        self.assertNotIn("_Internal", api["classes"])

    def test_returns_empty_on_syntax_error(self):
        api = _extract_public_api("def (broken: pass")
        self.assertEqual(api["functions"], {})
        self.assertEqual(api["classes"], {})

    def test_empty_code(self):
        api = _extract_public_api("")
        self.assertEqual(api["functions"], {})

    def test_no_args_function(self):
        code = "def greet(): return 'hello'"
        api = _extract_public_api(code)
        self.assertEqual(api["functions"]["greet"], [])

    def test_async_method_in_class(self):
        code = "class Service:\n    async def process(self, data): pass"
        api = _extract_public_api(code)
        self.assertIn("process", api["classes"]["Service"])


# ── _count_required_args ─────────────────────────────────────────────────────

class TestCountRequiredArgs(unittest.TestCase):

    def test_all_required(self):
        code = "def f(a, b, c): pass"
        self.assertEqual(_count_required_args(code, "f"), 3)

    def test_all_optional(self):
        code = "def f(a=1, b=2): pass"
        self.assertEqual(_count_required_args(code, "f"), 0)

    def test_mixed(self):
        code = "def f(a, b, c=3): pass"
        self.assertEqual(_count_required_args(code, "f"), 2)

    def test_self_counts(self):
        # self is a positional arg
        code = "def method(self, x): pass"
        self.assertEqual(_count_required_args(code, "method"), 2)

    def test_unknown_function_returns_zero(self):
        code = "def other(): pass"
        self.assertEqual(_count_required_args(code, "nonexistent"), 0)


# ── _analyze_diff ─────────────────────────────────────────────────────────────

class TestAnalyzeDiff(unittest.TestCase):

    def test_reports_line_counts(self):
        old = "line1\nline2\n"
        new = "line1\nline2\nline3\n"
        findings = _analyze_diff(old, new, "test.py")
        self.assertTrue(any("Lines:" in f for f in findings))
        self.assertTrue(any("+1" in f for f in findings))

    def test_detects_removed_function(self):
        old = "def foo(): pass\ndef bar(): pass"
        new = "def foo(): pass"
        findings = _analyze_diff(old, new, "test.py")
        self.assertTrue(any("BREAKING" in f and "bar" in f for f in findings))

    def test_detects_removed_class(self):
        old = "class Foo:\n    pass\nclass Bar:\n    pass"
        new = "class Foo:\n    pass"
        findings = _analyze_diff(old, new, "test.py")
        self.assertTrue(any("BREAKING" in f and "Bar" in f for f in findings))

    def test_detects_removed_method(self):
        old = "class Svc:\n    def run(self): pass\n    def stop(self): pass"
        new = "class Svc:\n    def run(self): pass"
        findings = _analyze_diff(old, new, "test.py")
        self.assertTrue(any("BREAKING" in f and "stop" in f for f in findings))

    def test_detects_signature_change(self):
        old = "def connect(host, port): pass"
        new = "def connect(host, port, timeout): pass"
        findings = _analyze_diff(old, new, "test.py")
        sig_findings = [f for f in findings if "SIGNATURE CHANGE" in f or "BREAKING" in f]
        self.assertTrue(len(sig_findings) > 0)

    def test_breaking_required_param_added(self):
        old = "def fetch(url): pass"
        new = "def fetch(url, auth_token): pass"
        findings = _analyze_diff(old, new, "test.py")
        # auth_token is required → BREAKING
        self.assertTrue(any("BREAKING" in f and "required param" in f for f in findings))

    def test_safe_optional_param_added(self):
        old = "def fetch(url): pass"
        new = "def fetch(url, timeout=30): pass"
        findings = _analyze_diff(old, new, "test.py")
        # timeout has default → SIGNATURE CHANGE (not BREAKING required param)
        sig_findings = [f for f in findings if "SIGNATURE CHANGE" in f]
        self.assertTrue(len(sig_findings) > 0)
        breaking_req = [f for f in findings if "BREAKING" in f and "required param" in f]
        self.assertEqual(len(breaking_req), 0)

    def test_no_changes_returns_just_line_count(self):
        code = "def foo(): pass"
        findings = _analyze_diff(code, code, "test.py")
        self.assertEqual(len(findings), 1)  # only "Lines: +0 added, -0 removed"

    def test_detects_async_function_removal(self):
        old = "async def process(data): pass"
        new = ""
        findings = _analyze_diff(old, new, "test.py")
        self.assertTrue(any("BREAKING" in f and "process" in f for f in findings))


# ── _compute_risk_level ───────────────────────────────────────────────────────

class TestComputeRiskLevel(unittest.TestCase):

    def test_low_risk_no_changes(self):
        risk, rec = _compute_risk_level(["Lines: +2 added, -1 removed"], 1, {})
        self.assertEqual(risk, "LOW")
        self.assertEqual(rec, "apply")

    def test_critical_breaking_many_dependents(self):
        changes = ["BREAKING: function 'llm_complete()' removed"]
        risk, rec = _compute_risk_level(changes, 5, {})
        self.assertEqual(risk, "CRITICAL")
        self.assertEqual(rec, "reject")

    def test_high_breaking_few_dependents(self):
        changes = ["BREAKING: function 'llm_complete()' removed"]
        risk, rec = _compute_risk_level(changes, 1, {})
        self.assertEqual(risk, "HIGH")
        self.assertEqual(rec, "apply_with_caution")

    def test_high_required_param_added_many_deps(self):
        changes = ["BREAKING: 'connect()' gained 1 required param(s) (host -> host, token)"]
        risk, rec = _compute_risk_level(changes, 4, {})
        self.assertEqual(risk, "CRITICAL")
        self.assertEqual(rec, "reject")

    def test_high_signature_change_multiple_deps(self):
        # SIGNATURE CHANGE with n_affected >= 2 → HIGH (not MEDIUM)
        changes = ["SIGNATURE CHANGE: 'foo(a)' -> 'foo(a, b=2)'"]
        risk, rec = _compute_risk_level(changes, 3, {})
        self.assertEqual(risk, "HIGH")
        self.assertEqual(rec, "apply_with_caution")

    def test_medium_signature_change_single_dep(self):
        # SIGNATURE CHANGE with n_affected < 2 → MEDIUM
        changes = ["SIGNATURE CHANGE: 'foo(a)' -> 'foo(a, b=2)'"]
        risk, rec = _compute_risk_level(changes, 1, {})
        self.assertEqual(risk, "MEDIUM")
        self.assertEqual(rec, "apply_with_caution")

    def test_medium_many_affected(self):
        risk, rec = _compute_risk_level(["Lines: +5 added, -0 removed"], 6, {})
        self.assertEqual(risk, "MEDIUM")

    def test_high_risk_modules_from_llm(self):
        module_risks = {
            "study_agent": "HIGH RISK: function signature mismatch will cause CRASH",
            "night_runner": "HIGH RISK: BREAK in API call",
        }
        risk, rec = _compute_risk_level(["Lines: +1 added, -0 removed"], 2, module_risks)
        self.assertEqual(risk, "MEDIUM")  # 2 high-risk modules → MEDIUM


# ── _build_summary ────────────────────────────────────────────────────────────

class TestBuildSummary(unittest.TestCase):

    def test_contains_filename(self):
        s = _build_summary("backend/llm_router.py", [], [], "LOW", "apply", {})
        self.assertIn("llm_router.py", s)

    def test_contains_risk_and_recommendation(self):
        s = _build_summary("f.py", [], ["mod_a"], "HIGH", "apply_with_caution", {})
        self.assertIn("HIGH", s)
        self.assertIn("apply_with_caution", s)

    def test_shows_dependents(self):
        s = _build_summary("f.py", [], ["mod_a", "mod_b"], "LOW", "apply", {})
        self.assertIn("mod_a", s)

    def test_truncates_long_dependent_list(self):
        affected = [f"mod_{i}" for i in range(10)]
        s = _build_summary("f.py", [], affected, "LOW", "apply", {})
        self.assertIn("+5 more", s)

    def test_flags_worst_module(self):
        risks = {"study_agent": "HIGH RISK: this will break the pipeline badly"}
        s = _build_summary("f.py", [], ["study_agent"], "HIGH", "apply_with_caution", risks)
        self.assertIn("study_agent", s)

    def test_shows_breaking_changes(self):
        changes = ["BREAKING: function 'foo()' removed", "Lines: +0, -5"]
        s = _build_summary("f.py", changes, [], "HIGH", "apply_with_caution", {})
        self.assertIn("Breaking", s)


# ── simulate_patch_sync ───────────────────────────────────────────────────────

class TestSimulatePatchSync(unittest.TestCase):
    """End-to-end sync simulation (no LLM calls)."""

    def test_returns_simulation_report(self):
        report = simulate_patch_sync("backend/test.py", "def foo(): pass", "def foo(): pass\ndef bar(): pass")
        self.assertIsInstance(report, SimulationReport)

    def test_no_changes_is_low_risk(self):
        code = "def foo(x): return x"
        report = simulate_patch_sync("f.py", code, code)
        self.assertEqual(report.risk_level, "LOW")

    def test_removing_function_raises_risk(self):
        old = "def foo(): pass\ndef bar(): pass"
        new = "def foo(): pass"
        report = simulate_patch_sync("f.py", old, new)
        self.assertIn(report.risk_level, ("HIGH", "CRITICAL"))

    def test_report_has_changes_detected(self):
        old = "def foo(): pass"
        new = ""
        report = simulate_patch_sync("f.py", old, new)
        self.assertTrue(len(report.changes_detected) > 0)

    def test_report_simulated_flag_true(self):
        report = simulate_patch_sync("f.py", "", "")
        self.assertTrue(report.simulated)

    def test_report_has_summary(self):
        report = simulate_patch_sync("f.py", "x = 1", "x = 2")
        self.assertTrue(len(report.summary) > 0)

    def test_added_required_param_is_high_risk(self):
        old = "def connect(host): pass"
        new = "def connect(host, token): pass"
        report = simulate_patch_sync("f.py", old, new)
        self.assertIn(report.risk_level, ("HIGH", "CRITICAL"))

    def test_added_optional_param_is_not_breaking(self):
        old = "def connect(host): pass"
        new = "def connect(host, timeout=30): pass"
        report = simulate_patch_sync("f.py", old, new)
        # Should be SIGNATURE CHANGE but not BREAKING required param
        breaking_req = [c for c in report.changes_detected if "BREAKING" in c and "required" in c]
        self.assertEqual(len(breaking_req), 0)


if __name__ == "__main__":
    unittest.main()
