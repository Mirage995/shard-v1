"""test_hypothesis_dedup.py -- Unit tests for _dedup_check_against_rows.

5 casi:
  A: hard duplicate CONFIRMED (ratio >= 0.82) → is_duplicate=True, DUPLICATE_CONFIRMED
  B: hard duplicate REFUTED  (ratio >= 0.82) → is_duplicate=True, DUPLICATE_REFUTED
  C: suspicious (0.70 <= ratio < 0.82)       → is_suspicious=True, not hard skip
  D: unrelated hypothesis (ratio < 0.70)     → proceeds, no flags
  E: same domain pair, completely different statement
     → domain_pair_seen=True, is_duplicate=False
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from study_agent import _dedup_check_against_rows, _DEDUP_HARD_THRESHOLD, _DEDUP_SUSPICIOUS_THRESHOLD


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row(id_, status, statement, domain_from="ML", domain_to="CV"):
    return {
        "id": id_,
        "status": status,
        "statement": statement,
        "domain_from": domain_from,
        "domain_to": domain_to,
        "confidence": 0.85,
    }


_CONFIRMED_STMT = (
    "Applying dropout regularization in transformer encoders reduces overfitting "
    "on low-resource NLP classification tasks by inhibiting co-adaptation of attention heads."
)

_REFUTED_STMT = (
    "Applying batch normalization before residual connections in ResNet architectures "
    "increases gradient variance and destabilizes training on CIFAR-10."
)

_EXISTING = [
    _row(1, "CONFIRMED", _CONFIRMED_STMT, "NLP", "Transformers"),
    _row(2, "REFUTED",   _REFUTED_STMT,   "CV",  "Training"),
    _row(3, "CONFIRMED", "Graph neural networks improve molecular property prediction.", "Chemistry", "GNN"),
]


# ── Case A: hard duplicate CONFIRMED ─────────────────────────────────────────

def test_case_a_hard_duplicate_confirmed():
    # Minimally paraphrased — should exceed 0.82
    hyp = {
        "statement":   _CONFIRMED_STMT,  # verbatim copy → ratio=1.0
        "domain_from": "NLP",
        "domain_to":   "Transformers",
    }
    result = _dedup_check_against_rows(hyp, _EXISTING)
    assert result["is_duplicate"] is True
    assert result["is_suspicious"] is False
    assert result["reason"] == "DUPLICATE_CONFIRMED"
    assert result["matched_id"] == 1
    assert result["matched_status"] == "CONFIRMED"
    assert result["similarity_ratio"] >= _DEDUP_HARD_THRESHOLD
    assert result["domain_pair_seen"] is True


# ── Case B: hard duplicate REFUTED ───────────────────────────────────────────

def test_case_b_hard_duplicate_refuted():
    hyp = {
        "statement":   _REFUTED_STMT,   # verbatim → ratio=1.0
        "domain_from": "CV",
        "domain_to":   "Training",
    }
    result = _dedup_check_against_rows(hyp, _EXISTING)
    assert result["is_duplicate"] is True
    assert "DUPLICATE_REFUTED" in result["reason"]
    assert "novelty_delta" in result["reason"]   # reminder note present
    assert result["matched_id"] == 2
    assert result["similarity_ratio"] >= _DEDUP_HARD_THRESHOLD


# ── Case C: suspicious similarity ────────────────────────────────────────────

def test_case_c_suspicious_similarity():
    # Moderately similar but not a copy — tweak a few words
    hyp = {
        "statement": (
            "Applying dropout regularization in transformer encoders reduces overfitting "
            "on low-resource NLP tasks by inhibiting co-adaptation of attention layers."
        ),
        "domain_from": "NLP",
        "domain_to":   "Transformers",
    }
    result = _dedup_check_against_rows(hyp, _EXISTING)
    # Should be suspicious (high similarity) but not hard duplicate
    # Ratio expected to be > 0.70 given the small rewording
    assert result["similarity_ratio"] >= _DEDUP_SUSPICIOUS_THRESHOLD
    if result["similarity_ratio"] < _DEDUP_HARD_THRESHOLD:
        assert result["is_suspicious"] is True
        assert result["is_duplicate"] is False
    else:
        # If SequenceMatcher rates it >= 0.82, the hard path is also acceptable
        assert result["is_duplicate"] is True


# ── Case D: unrelated hypothesis ─────────────────────────────────────────────

def test_case_d_unrelated_proceeds():
    hyp = {
        "statement": (
            "Applying entropy-based pruning strategies from information theory to "
            "financial portfolio rebalancing reduces drawdown by 18% on backtested data."
        ),
        "domain_from": "Information Theory",
        "domain_to":   "Finance",
    }
    result = _dedup_check_against_rows(hyp, _EXISTING)
    assert result["is_duplicate"]  is False
    assert result["is_suspicious"] is False
    assert result["similarity_ratio"] < _DEDUP_SUSPICIOUS_THRESHOLD
    assert result["domain_pair_seen"] is False


# ── Case E: same domain pair, different statement → warning only ──────────────

def test_case_e_same_domain_pair_different_statement():
    # domain_from="NLP", domain_to="Transformers" matches row 1 (CONFIRMED),
    # but the statement is completely different
    hyp = {
        "statement": (
            "Applying Fourier positional encodings from signal processing to "
            "transformer attention masks improves long-range dependency modeling."
        ),
        "domain_from": "NLP",
        "domain_to":   "Transformers",
    }
    result = _dedup_check_against_rows(hyp, _EXISTING)
    assert result["domain_pair_seen"] is True      # domain pair already CONFIRMED
    assert result["is_duplicate"]  is False         # but statement is novel
    assert result["is_suspicious"] is False


# ── Edge: empty DB → no-op ────────────────────────────────────────────────────

def test_empty_db_passes():
    hyp = {"statement": "Some hypothesis.", "domain_from": "A", "domain_to": "B"}
    result = _dedup_check_against_rows(hyp, [])
    assert result["is_duplicate"]  is False
    assert result["is_suspicious"] is False
    assert result["similarity_ratio"] == 0.0
