"""test_kaggle_quota.py -- Unit tests for kaggle_quota module.

8 test cases:
  A: run under quota              → allowed, added to ledger
  B: run over KAGGLE_MAX_HOURS    → blocked (EXCEEDS_MAX_PER_RUN)
  C: total quota exceeded         → blocked (QUOTA_EXHAUSTED)
  D: dispatch disabled by default → can_dispatch() = False
  E: manual approval required     → can_dispatch() = False
  F: ledger persists across calls → pending_hours accumulates correctly
  G: queue health warnings        → over-budget + stale-queue flags
  H: estimate_gpu_hours heuristic → keyword tier detection
"""
import os
import sqlite3
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import kaggle_quota as kq


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_conn():
    """In-memory SQLite with kaggle_quota_ledger schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    kq._ensure_ledger(conn)
    return conn


def _hyp(statement="Synthetic MLP accuracy test", confidence=0.80, **kw):
    base = {
        "statement":          statement,
        "minimum_experiment": "Train a 2-layer MLP on synthetic data for 5 epochs.",
        "rationale":          "Basic regularization sanity check.",
        "confidence":         confidence,
    }
    base.update(kw)
    return base


# ── Case A: run under quota ───────────────────────────────────────────────────

def test_case_a_run_under_quota_accepted():
    conn = _fresh_conn()
    env = {
        "KAGGLE_GPU_HOURS_AVAILABLE": "28",
        "KAGGLE_MAX_HOURS_PER_RUN":   "2",
    }
    with patch.dict(os.environ, env, clear=False):
        result = kq.try_enqueue(hypothesis_id=1, hypothesis=_hyp(), conn=conn)

    assert result["allowed"]    is True,      "Under-quota run must be accepted"
    assert result["run_id"]     is not None,  "run_id must be assigned"
    assert result["run_id"]     >= 1
    assert result["reason"]     == ""
    assert result["estimated_hours"] <= 2.0


def test_case_a_run_appears_in_ledger():
    conn = _fresh_conn()
    with patch.dict(os.environ, {"KAGGLE_GPU_HOURS_AVAILABLE": "28", "KAGGLE_MAX_HOURS_PER_RUN": "2"}, clear=False):
        kq.try_enqueue(hypothesis_id=2, hypothesis=_hyp(), conn=conn)

    rows = conn.execute("SELECT * FROM kaggle_quota_ledger WHERE status='PENDING'").fetchall()
    assert len(rows) == 1
    r = dict(rows[0])
    assert r["hypothesis_id"]   == 2
    assert r["backend"]         == "kaggle"
    assert r["estimated_gpu_hours"] > 0
    assert r["validation_tier_target"] == "gpu_replicated"


# ── Case B: KAGGLE_MAX_HOURS_PER_RUN exceeded ────────────────────────────────

def test_case_b_run_over_max_per_run_blocked():
    conn = _fresh_conn()
    # Cap to 1h per run, but hypothesis needs >=0.5h (light); force heavy → 1.5h > 1.0h cap
    heavy_hyp = _hyp(statement="GPT fine-tuning on custom corpus with full training run")
    env = {"KAGGLE_GPU_HOURS_AVAILABLE": "28", "KAGGLE_MAX_HOURS_PER_RUN": "1"}
    with patch.dict(os.environ, env, clear=False):
        # estimate_gpu_hours is capped at max_per_run (1.0), so check_quota sees 1.0 <= 1.0
        # But the raw estimate before cap is 1.5. Test the raw estimate check path by
        # directly calling check_quota with an over-limit value.
        result = kq.check_quota(estimated_hours=1.5, conn=conn)

    assert result["allowed"] is False
    assert "EXCEEDS_MAX_PER_RUN" in result["reason"]


def test_case_b_try_enqueue_respects_cap():
    """try_enqueue caps estimate at max_per_run, so even heavy hyp is within cap."""
    conn = _fresh_conn()
    heavy_hyp = _hyp(statement="GPT fine-tuning on custom corpus with full training run")
    # With max=2.0, estimate is capped at 2.0 (not over-limit)
    env = {"KAGGLE_GPU_HOURS_AVAILABLE": "28", "KAGGLE_MAX_HOURS_PER_RUN": "2"}
    with patch.dict(os.environ, env, clear=False):
        result = kq.try_enqueue(hypothesis_id=3, hypothesis=heavy_hyp, conn=conn)
    assert result["allowed"] is True
    assert result["estimated_hours"] <= 2.0


# ── Case C: total quota exceeded ─────────────────────────────────────────────

def test_case_c_total_quota_exceeded_blocked():
    conn = _fresh_conn()
    # Fill 27.5 hours of pending
    conn.execute(
        "INSERT INTO kaggle_quota_ledger "
        "(hypothesis_id, estimated_gpu_hours, status, backend) VALUES (?, ?, 'PENDING', 'kaggle')",
        (99, 27.5),
    )
    conn.commit()

    env = {"KAGGLE_GPU_HOURS_AVAILABLE": "28", "KAGGLE_MAX_HOURS_PER_RUN": "2"}
    with patch.dict(os.environ, env, clear=False):
        result = kq.try_enqueue(hypothesis_id=4, hypothesis=_hyp(), conn=conn)

    assert result["allowed"] is False
    assert "QUOTA_EXHAUSTED" in result["reason"]
    assert result["pending_hours"] >= 27.5


def test_case_c_completed_hours_not_counted():
    """Completed runs do NOT count against pending quota."""
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO kaggle_quota_ledger "
        "(hypothesis_id, estimated_gpu_hours, status, backend) VALUES (?, ?, 'COMPLETED', 'kaggle')",
        (100, 25.0),
    )
    conn.commit()

    env = {"KAGGLE_GPU_HOURS_AVAILABLE": "28", "KAGGLE_MAX_HOURS_PER_RUN": "2"}
    with patch.dict(os.environ, env, clear=False):
        result = kq.try_enqueue(hypothesis_id=5, hypothesis=_hyp(), conn=conn)

    assert result["allowed"] is True, "COMPLETED hours must not block new PENDING runs"


# ── Case D: dispatch disabled by default ─────────────────────────────────────

def test_case_d_dispatch_disabled_by_default():
    """KAGGLE_DISPATCH_ENABLED defaults to false → can_dispatch()=False."""
    env = {}
    with patch.dict(os.environ, env, clear=False):
        # Remove the key to test the default
        env_without = {k: v for k, v in os.environ.items()
                       if k != "KAGGLE_DISPATCH_ENABLED"}
        with patch.dict(os.environ, {}, clear=True):
            os.environ.update(env_without)
            assert kq._cfg_dispatch_enabled() is False
            assert kq.can_dispatch() is False


def test_case_d_dispatch_stays_off_even_with_approval_disabled():
    """Both flags must be in dispatch-allowed state for can_dispatch() to return True."""
    with patch.dict(os.environ,
                    {"KAGGLE_DISPATCH_ENABLED": "false",
                     "KAGGLE_REQUIRE_MANUAL_APPROVAL": "false"},
                    clear=False):
        assert kq.can_dispatch() is False


# ── Case E: manual approval required ─────────────────────────────────────────

def test_case_e_manual_approval_blocks_dispatch():
    """KAGGLE_REQUIRE_MANUAL_APPROVAL=true (default) → can_dispatch()=False."""
    with patch.dict(os.environ,
                    {"KAGGLE_DISPATCH_ENABLED": "true",
                     "KAGGLE_REQUIRE_MANUAL_APPROVAL": "true"},
                    clear=False):
        assert kq._cfg_require_manual_approval() is True
        assert kq.can_dispatch() is False


def test_case_e_dispatch_only_when_both_flags_set():
    """can_dispatch()=True only when dispatch=true AND require_approval=false."""
    with patch.dict(os.environ,
                    {"KAGGLE_DISPATCH_ENABLED": "true",
                     "KAGGLE_REQUIRE_MANUAL_APPROVAL": "false"},
                    clear=False):
        assert kq.can_dispatch() is True


# ── Case F: ledger persists between calls ─────────────────────────────────────

def test_case_f_pending_hours_accumulate():
    """Pending hours from prior enqueues are counted on next check_quota call."""
    conn = _fresh_conn()
    env = {"KAGGLE_GPU_HOURS_AVAILABLE": "28", "KAGGLE_MAX_HOURS_PER_RUN": "2"}

    with patch.dict(os.environ, env, clear=False):
        r1 = kq.try_enqueue(hypothesis_id=10, hypothesis=_hyp(), conn=conn)
        h1 = r1["estimated_hours"]

        r2 = kq.try_enqueue(hypothesis_id=11, hypothesis=_hyp(), conn=conn)
        h2 = r2["estimated_hours"]

    # Both should be allowed
    assert r1["allowed"] is True
    assert r2["allowed"] is True

    # Pending hours accumulated
    pending = kq.get_pending_ledger_hours(conn)
    assert abs(pending - (h1 + h2)) < 0.01, (
        f"Expected pending={h1 + h2:.2f}, got {pending:.2f}"
    )


def test_case_f_ledger_survives_new_connection():
    """Ledger is in SQLite — would survive process restart (simulated with file DB)."""
    import tempfile, os as _os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        # First 'session': add a run
        conn1 = sqlite3.connect(db_path)
        conn1.row_factory = sqlite3.Row
        kq._ensure_ledger(conn1)
        with patch.dict(os.environ, {"KAGGLE_GPU_HOURS_AVAILABLE": "28",
                                     "KAGGLE_MAX_HOURS_PER_RUN": "2"}, clear=False):
            kq.try_enqueue(hypothesis_id=20, hypothesis=_hyp(), conn=conn1)
        conn1.close()

        # Second 'session': open same file, hours are there
        conn2 = sqlite3.connect(db_path)
        conn2.row_factory = sqlite3.Row
        hours = kq.get_pending_ledger_hours(conn2)
        conn2.close()

        assert hours > 0.0, "Ledger must persist pending hours across connections"
    finally:
        _os.unlink(db_path)


# ── Case G: queue health warnings ────────────────────────────────────────────

def test_case_g_queue_health_over_budget_warning():
    """get_queue_health() warns when pending_estimated_hours > available."""
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO kaggle_quota_ledger "
        "(hypothesis_id, estimated_gpu_hours, status, backend) VALUES (?, ?, 'PENDING', 'kaggle')",
        (30, 30.0),
    )
    conn.commit()

    with patch.dict(os.environ, {"KAGGLE_GPU_HOURS_AVAILABLE": "28"}, clear=False):
        health = kq.get_queue_health(conn)

    assert health["pending_kaggle_runs"]   == 1
    assert health["pending_estimated_hours"] >= 30.0
    over_budget_warnings = [w for w in health["warnings"] if "OVER_BUDGET" in w]
    assert len(over_budget_warnings) >= 1, f"Expected OVER_BUDGET warning, got: {health['warnings']}"


def test_case_g_queue_health_no_warnings_when_empty():
    conn = _fresh_conn()
    with patch.dict(os.environ, {"KAGGLE_GPU_HOURS_AVAILABLE": "28"}, clear=False):
        health = kq.get_queue_health(conn)

    assert health["pending_kaggle_runs"]     == 0
    assert health["pending_estimated_hours"] == 0.0
    assert health["warnings"]                == []


def test_case_g_queue_health_reports_dispatch_state():
    conn = _fresh_conn()
    with patch.dict(os.environ,
                    {"KAGGLE_DISPATCH_ENABLED": "false",
                     "KAGGLE_REQUIRE_MANUAL_APPROVAL": "true",
                     "KAGGLE_GPU_HOURS_AVAILABLE": "28"},
                    clear=False):
        health = kq.get_queue_health(conn)

    assert health["dispatch_enabled"]        is False
    assert health["require_manual_approval"] is True
    assert health["can_dispatch"]            is False


# ── Case H: estimate_gpu_hours heuristic ──────────────────────────────────────

def test_case_h_light_estimate():
    # Use a hypothesis with no training/LLM keywords in any field
    hyp = {
        "statement":          "L2 regularization reduces overfitting in linear regression.",
        "minimum_experiment": "Compare R² on held-out test set with and without L2 penalty.",
        "rationale":          "Penalizing large weights should improve generalization.",
        "confidence":         0.75,
    }
    with patch.dict(os.environ, {"KAGGLE_MAX_HOURS_PER_RUN": "2"}, clear=False):
        h = kq.estimate_gpu_hours(hyp)
    assert h == 0.5


def test_case_h_medium_estimate_training():
    h = kq.estimate_gpu_hours(_hyp(
        "Training a convolutional network for 50 epochs with gradient descent on CIFAR-10."
    ))
    with patch.dict(os.environ, {"KAGGLE_MAX_HOURS_PER_RUN": "2"}, clear=False):
        assert h == 1.0


def test_case_h_heavy_estimate_llm():
    h = kq.estimate_gpu_hours(_hyp(
        "Fine-tuning a pre-trained BERT model on domain-specific NLP corpus."
    ))
    with patch.dict(os.environ, {"KAGGLE_MAX_HOURS_PER_RUN": "2"}, clear=False):
        assert h == 1.5


def test_case_h_capped_at_max_per_run():
    """Estimate never exceeds KAGGLE_MAX_HOURS_PER_RUN."""
    hyp = _hyp("GPT fine-tuning full training run pretraining LLM large model.")
    with patch.dict(os.environ, {"KAGGLE_MAX_HOURS_PER_RUN": "1"}, clear=False):
        h = kq.estimate_gpu_hours(hyp)
    assert h <= 1.0
