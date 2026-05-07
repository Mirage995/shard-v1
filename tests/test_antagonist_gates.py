"""test_antagonist_gates.py -- Unit tests for normalize_antagonist_review gates.

6 cases:
  A: well-formed VALID with all fields populated → passes all gates → VALID
  B: VALID with empty alternative_mechanism → G4 forces INVALID_CORRECTABLE
  C: VALID with empty confounds → G5 forces INVALID_CORRECTABLE
  D: VALID with confidence 0.55 → G3 forces INVALID_CORRECTABLE
  E: INVALID_CORRECTABLE with "hardcoded" in missing_controls → G2 forces INVALID_FATAL
  F: malformed dict (missing verdict field) → G1 forces INVALID_CORRECTABLE + INVALID_FORMAT
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from experiment_phases import normalize_antagonist_review


def _good_valid() -> dict:
    return {
        "verdict":               "VALID",
        "confidence":            0.85,
        "alternative_mechanism": "Random initialization variance could explain the gap",
        "confounds":             ["dataset size", "learning rate schedule"],
        "missing_controls":      ["early stopping criterion"],
        "reason":                "Code correctly implements the mechanism; result is reproducible.",
        "corrected_code":        None,
        "review_quality":        "thorough",
    }


# ── Case A ────────────────────────────────────────────────────────────────────

def test_case_a_valid_passes_all_gates():
    result = normalize_antagonist_review(_good_valid())
    assert result["verdict"] == "VALID"
    assert result["forced_verdict"] is False
    assert result["force_reason"] == ""


# ── Case B ────────────────────────────────────────────────────────────────────

def test_case_b_valid_no_alternative_mechanism_forced():
    review = _good_valid()
    review["alternative_mechanism"] = ""
    result = normalize_antagonist_review(review)
    assert result["verdict"] == "INVALID_CORRECTABLE"
    assert result["forced_verdict"] is True
    assert "G4" in result["force_reason"]


# ── Case C ────────────────────────────────────────────────────────────────────

def test_case_c_valid_no_confounds_forced():
    review = _good_valid()
    review["confounds"] = []
    result = normalize_antagonist_review(review)
    assert result["verdict"] == "INVALID_CORRECTABLE"
    assert result["forced_verdict"] is True
    assert "G5" in result["force_reason"]


# ── Case D ────────────────────────────────────────────────────────────────────

def test_case_d_valid_low_confidence_forced():
    review = _good_valid()
    review["confidence"] = 0.55
    result = normalize_antagonist_review(review)
    assert result["verdict"] == "INVALID_CORRECTABLE"
    assert result["forced_verdict"] is True
    assert "G3" in result["force_reason"]
    assert "0.55" in result["force_reason"]


# ── Case E ────────────────────────────────────────────────────────────────────

def test_case_e_fatal_keyword_in_missing_controls():
    review = {
        "verdict":               "INVALID_CORRECTABLE",
        "confidence":            0.80,
        "alternative_mechanism": "Result may reflect dataset bias",
        "confounds":             ["class imbalance"],
        "missing_controls":      ["hardcoded baseline score found in line 42"],
        "reason":                "Baseline appears to be hardcoded.",
        "corrected_code":        "print('fixed')",
        "review_quality":        "thorough",
    }
    result = normalize_antagonist_review(review)
    assert result["verdict"] == "INVALID_FATAL"
    assert result["forced_verdict"] is True
    assert "G2" in result["force_reason"]
    assert "hardcoded" in result["force_reason"]


# ── Case F ────────────────────────────────────────────────────────────────────

def test_case_f_malformed_missing_verdict():
    review = {
        "confidence":  0.9,
        "reason":      "Looks fine.",
        "_parse_error": True,
    }
    result = normalize_antagonist_review(review)
    assert result["verdict"] == "INVALID_CORRECTABLE"
    assert result["forced_verdict"] is True
    assert "G1" in result["force_reason"]
    assert "INVALID_FORMAT" in result["force_reason"]
