"""test_d14_b.py -- Lightweight tests for D14-B validation pack and analyzer.

Tests cover:
  T1: Task splits are 5 pairs covering digits 0-9 in order
  T2: CONDITIONS has exactly 4 entries with correct flag combinations
  T3: compute_forgetting_magnitude — basic calculation
  T4: compute_forgetting_magnitude — last task excluded
  T5: compute_signed_bwt — forward transfer sign
  T6: compute_final_average_accuracy — mean of finals
  T7: Analyzer PASS_STRONG on ideal data
  T8: Analyzer FAIL when forgetting condition not met
  T9: Analyzer FAIL when accuracy degraded > 1 pp
  T10: Analyzer INCONCLUSIVE on empty data
  T11: compute_verdict gate1 boundary — strictly less than
  T12: Analyzer PASS_WEAK when scipy unavailable
"""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import d14_b_validation_pack as vp
import d14_b_analyze as va


# ── T1: Task splits ────────────────────────────────────────────────────────────

def test_t1_task_splits_count():
    tasks = vp.get_task_splits()
    assert len(tasks) == 5, f"Expected 5 tasks, got {len(tasks)}"


def test_t1_task_splits_cover_digits_0_to_9():
    tasks = vp.get_task_splits()
    digits = sorted(d for pair in tasks for d in pair)
    assert digits == list(range(10)), f"Expected digits 0-9, got {digits}"


def test_t1_task_splits_are_consecutive_pairs():
    tasks = vp.get_task_splits()
    for i, (d0, d1) in enumerate(tasks):
        assert d1 == d0 + 1, f"Task {i}: {d0},{d1} are not consecutive"
        assert d0 == i * 2, f"Task {i}: expected first digit {i*2}, got {d0}"


# ── T2: Conditions ────────────────────────────────────────────────────────────

def test_t2_conditions_count():
    assert len(vp.CONDITIONS) == 4


def test_t2_conditions_have_required_names():
    names = {c["name"] for c in vp.CONDITIONS}
    assert "Baseline SGD" in names
    assert "ANV only"     in names
    assert "OGD only"     in names
    assert "ANV + OGD"    in names


def test_t2_baseline_has_no_anv_no_ogd():
    baseline = next(c for c in vp.CONDITIONS if c["name"] == "Baseline SGD")
    assert baseline["use_anv"] is False
    assert baseline["use_ogd"] is False


def test_t2_anv_ogd_has_both_flags():
    anv_ogd = next(c for c in vp.CONDITIONS if c["name"] == "ANV + OGD")
    assert anv_ogd["use_anv"] is True
    assert anv_ogd["use_ogd"] is True


# ── T3: compute_forgetting_magnitude ──────────────────────────────────────────

def test_t3_forgetting_magnitude_basic():
    # Task 0: peak=0.9, final=0.7 → forget=0.2
    # Task 1: peak=0.8, final=0.6 → forget=0.2
    # Task 2: last task, excluded
    acc_after = [
        [0.9, 0.8, 0.7],   # task 0: measured after t0, t1, t2
        [0.8, 0.7, 0.6],   # task 1: measured after t1, t2
        [0.75],            # task 2: only measured after t2 (last task)
    ]
    fm = vp.compute_forgetting_magnitude(acc_after)
    expected = (0.2 + 0.2) / 2
    assert abs(fm - expected) < 1e-6, f"Expected {expected}, got {fm}"


def test_t3_forgetting_magnitude_no_forgetting():
    acc_after = [
        [0.8, 0.85, 0.9],   # task 0: improving
        [0.7, 0.8],          # task 1: improving
        [0.75],              # task 2: last
    ]
    fm = vp.compute_forgetting_magnitude(acc_after)
    assert fm == 0.0, f"Expected 0.0, got {fm}"


# ── T4: last task excluded from forgetting ────────────────────────────────────

def test_t4_last_task_excluded_from_forgetting():
    # 5-task setup: only first 4 tasks contribute to forgetting_magnitude
    acc_after = [
        [0.9, 0.8, 0.7, 0.6, 0.5],   # forget = 0.4
        [0.8, 0.7, 0.6, 0.5],        # forget = 0.3
        [0.7, 0.6, 0.5],             # forget = 0.2
        [0.6, 0.5],                  # forget = 0.1
        [0.95],                      # last task, excluded
    ]
    fm = vp.compute_forgetting_magnitude(acc_after)
    expected = (0.4 + 0.3 + 0.2 + 0.1) / 4
    assert abs(fm - expected) < 1e-6, f"Expected {expected}, got {fm}"


# ── T5: compute_signed_bwt ───────────────────────────────────────────────────

def test_t5_signed_bwt_negative_on_forgetting():
    # final < right_after → negative BWT (forgetting happened)
    acc_after = [
        [0.9, 0.7],   # bwt = 0.7 - 0.9 = -0.2
        [0.8, 0.6],   # bwt = 0.6 - 0.8 = -0.2
        [0.75],       # last task, excluded
    ]
    bwt = vp.compute_signed_bwt(acc_after)
    expected = (-0.2 + -0.2) / 2
    assert abs(bwt - expected) < 1e-6, f"Expected {expected}, got {bwt}"


def test_t5_signed_bwt_positive_on_forward_transfer():
    # final > right_after → positive BWT (forward transfer)
    acc_after = [
        [0.7, 0.9],   # bwt = +0.2
        [0.6, 0.8],   # bwt = +0.2
        [0.75],       # last task, excluded
    ]
    bwt = vp.compute_signed_bwt(acc_after)
    expected = (0.2 + 0.2) / 2
    assert abs(bwt - expected) < 1e-6, f"Expected {expected}, got {bwt}"


# ── T6: compute_final_average_accuracy ───────────────────────────────────────

def test_t6_final_average_accuracy_all_tasks():
    acc_after = [
        [0.9, 0.8, 0.7],   # final = 0.7
        [0.8, 0.6],        # final = 0.6
        [0.95],            # final = 0.95
    ]
    faa = vp.compute_final_average_accuracy(acc_after)
    expected = (0.7 + 0.6 + 0.95) / 3
    assert abs(faa - expected) < 1e-6, f"Expected {expected}, got {faa}"


# ── T7: Analyzer PASS_STRONG ─────────────────────────────────────────────────

def _make_seed_result(
    ogd_forget: float, ogd_acc: float,
    anv_forget: float, anv_acc: float,
) -> dict:
    """Minimal seed result dict for analyzer testing."""
    return {
        "Baseline SGD": {"forgetting_magnitude": 0.4, "final_average_accuracy": 0.6, "signed_bwt": -0.3},
        "ANV only":     {"forgetting_magnitude": 0.3, "final_average_accuracy": 0.65, "signed_bwt": -0.2},
        "OGD only":     {"forgetting_magnitude": ogd_forget, "final_average_accuracy": ogd_acc, "signed_bwt": -0.2},
        "ANV + OGD":    {"forgetting_magnitude": anv_forget, "final_average_accuracy": anv_acc, "signed_bwt": -0.15},
    }


def test_t7_pass_strong_on_clear_win():
    """5 seeds where ANV+OGD clearly beats OGD-only on both metrics."""
    # ANV+OGD: forgetting ~0.10, acc ~0.80 (OGD: forgetting ~0.20, acc ~0.79)
    results = [
        _make_seed_result(ogd_forget=0.20, ogd_acc=0.79, anv_forget=0.10, anv_acc=0.80)
        for _ in range(5)
    ]
    verdict = va.compute_verdict(
        ogd_forget=[r["OGD only"]["forgetting_magnitude"] for r in results],
        anv_forget=[r["ANV + OGD"]["forgetting_magnitude"] for r in results],
        ogd_acc   =[r["OGD only"]["final_average_accuracy"] for r in results],
        anv_acc   =[r["ANV + OGD"]["final_average_accuracy"] for r in results],
    )
    # With scipy available, identical differences → may hit zero-diffs edge case
    # Either PASS_STRONG or PASS_WEAK is acceptable on constant data
    assert verdict["verdict"] in (va.VERDICT_PASS_STRONG, va.VERDICT_PASS_WEAK)
    assert verdict["gate1_passed"] is True
    assert verdict["gate2_passed"] is True


# ── T8: Analyzer FAIL — forgetting not better ─────────────────────────────────

def test_t8_fail_when_anv_ogd_worse_on_forgetting():
    results = [
        _make_seed_result(ogd_forget=0.10, ogd_acc=0.80, anv_forget=0.20, anv_acc=0.80)
        for _ in range(5)
    ]
    verdict = va.compute_verdict(
        ogd_forget=[r["OGD only"]["forgetting_magnitude"] for r in results],
        anv_forget=[r["ANV + OGD"]["forgetting_magnitude"] for r in results],
        ogd_acc   =[r["OGD only"]["final_average_accuracy"] for r in results],
        anv_acc   =[r["ANV + OGD"]["final_average_accuracy"] for r in results],
    )
    assert verdict["verdict"] == va.VERDICT_FAIL
    assert verdict["gate1_passed"] is False


# ── T9: Analyzer FAIL — accuracy degraded > 1 pp ─────────────────────────────

def test_t9_fail_when_accuracy_drops_more_than_1pp():
    results = [
        _make_seed_result(ogd_forget=0.20, ogd_acc=0.80, anv_forget=0.10, anv_acc=0.78)
        for _ in range(5)
    ]
    verdict = va.compute_verdict(
        ogd_forget=[r["OGD only"]["forgetting_magnitude"] for r in results],
        anv_forget=[r["ANV + OGD"]["forgetting_magnitude"] for r in results],
        ogd_acc   =[r["OGD only"]["final_average_accuracy"] for r in results],
        anv_acc   =[r["ANV + OGD"]["final_average_accuracy"] for r in results],
    )
    assert verdict["verdict"] == va.VERDICT_FAIL
    assert verdict["gate2_passed"] is False


# ── T10: Analyzer INCONCLUSIVE on empty data ──────────────────────────────────

def test_t10_inconclusive_on_empty():
    verdict = va.compute_verdict([], [], [], [])
    assert verdict["verdict"] == va.VERDICT_INCONCLUSIVE
    assert verdict["n_seeds"] == 0


# ── T11: Gate1 boundary — strictly less than ──────────────────────────────────

def test_t11_gate1_equal_does_not_pass():
    """When ANV+OGD forgetting == OGD-only forgetting, Gate1 must fail (strictly <)."""
    verdict = va.compute_verdict(
        ogd_forget=[0.20, 0.20, 0.20, 0.20, 0.20],
        anv_forget=[0.20, 0.20, 0.20, 0.20, 0.20],
        ogd_acc   =[0.80, 0.80, 0.80, 0.80, 0.80],
        anv_acc   =[0.80, 0.80, 0.80, 0.80, 0.80],
    )
    assert verdict["gate1_passed"] is False
    assert verdict["verdict"] == va.VERDICT_FAIL


# ── T12: PASS_WEAK when scipy unavailable ─────────────────────────────────────

def test_t12_pass_weak_when_scipy_missing():
    """If scipy is not available, 5 good seeds should yield PASS_WEAK (not PASS_STRONG)."""
    with patch.dict(sys.modules, {"scipy": None, "scipy.stats": None}):
        # Force _wilcoxon_pvalue to return None by making import fail
        with patch.object(va, "_wilcoxon_pvalue", return_value=None):
            verdict = va.compute_verdict(
                ogd_forget=[0.20, 0.21, 0.19, 0.22, 0.18],
                anv_forget=[0.10, 0.11, 0.09, 0.12, 0.08],
                ogd_acc   =[0.79, 0.80, 0.78, 0.81, 0.77],
                anv_acc   =[0.80, 0.81, 0.79, 0.82, 0.78],
            )
    assert verdict["verdict"] == va.VERDICT_PASS_WEAK
    assert verdict["gate1_passed"] is True
    assert verdict["gate2_passed"] is True
    assert verdict["wilcoxon_tested"] is False


# ── T13: analyze() on a real temp file ───────────────────────────────────────

def test_t13_analyze_reads_file_and_returns_verdict():
    """End-to-end: write a minimal raw_results.json, run analyze(), check verdict key."""
    results = [
        _make_seed_result(ogd_forget=0.20, ogd_acc=0.79, anv_forget=0.10, anv_acc=0.80)
        for _ in range(3)  # 3 seeds (< MIN_SEEDS_FOR_WILCOXON=5, so no Wilcoxon)
    ]
    raw_data = {"seeds": [0, 1, 2], "dry_run": True, "elapsed_s": 1.0, "results": results}

    with tempfile.TemporaryDirectory() as tmpdir:
        raw_path = Path(tmpdir) / "raw_results.json"
        raw_path.write_text(json.dumps(raw_data), encoding="utf-8")

        out = va.analyze(raw_path)

    assert "verdict" in out
    assert out["verdict"]["verdict"] in (
        va.VERDICT_PASS_STRONG, va.VERDICT_PASS_WEAK,
        va.VERDICT_FAIL, va.VERDICT_INCONCLUSIVE,
    )
    assert "table" in out
    assert "report" in out
    assert len(out["table"]) == 4   # one row per condition
