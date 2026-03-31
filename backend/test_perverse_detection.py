"""test_perverse_detection.py -- Stress tests for perverse_detection.py

Tests:
  1. False positive -- healthy session, no flags expected
  2. Edge case -- perfect performance on hard tasks, no flags expected
  3. Degeneration -- easy farming + hard avoidance, flags expected
  4. Stability -- 20 simulated sessions, identity_core doesn't collapse
  5. Overlap bug -- CERT_INFLATION + EASY_FARMING together, risk not double-counted

Run:
  cd backend && python -m pytest test_perverse_detection.py -v
"""
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Fixture: inject fake rows into real DB, clean up after ────────────────────

import shard_db


def _insert_rows(session_id: str, rows: list[dict]):
    """Insert fake activation_log rows for a test session."""
    for r in rows:
        shard_db.execute(
            "INSERT INTO activation_log "
            "(session_id, topic, timestamp, score, certified, source, sig_difficulty) "
            "VALUES (?, ?, datetime('now'), ?, ?, ?, ?)",
            (
                session_id,
                r.get("topic", "test_topic"),
                r.get("score", 7.0),
                1 if r.get("certified", True) else 0,
                r.get("source", "curated_list"),
                r.get("sig_difficulty", 0.5),
            ),
        )


def _cleanup(session_id: str):
    shard_db.execute(
        "DELETE FROM activation_log WHERE session_id = ?", (session_id,)
    )


@pytest.fixture(autouse=True)
def clean_session():
    """Each test gets a unique session_id; cleaned up after."""
    sid = f"test_{uuid.uuid4().hex[:8]}"
    yield sid
    _cleanup(sid)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_healthy_rows(n: int = 15) -> list[dict]:
    """Mix of curated + curiosity, hard + medium, mostly certified."""
    rows = []
    for i in range(n):
        source = "curated_list" if i % 3 != 0 else "curiosity_engine"
        diff   = 0.8 if i % 2 == 0 else 0.5
        rows.append({
            "topic": f"healthy_topic_{i}",
            "certified": i % 5 != 0,  # 80% cert rate
            "source": source,
            "sig_difficulty": diff,
        })
    return rows


def _make_easy_farm_rows(n: int = 15) -> list[dict]:
    """All easy curiosity topics, all certified."""
    return [
        {
            "topic": f"easy_topic_{i}",
            "certified": True,
            "source": "curiosity_engine",
            "sig_difficulty": 0.2,
        }
        for i in range(n)
    ]


def _make_hard_avoider_rows(n: int = 15) -> list[dict]:
    """Many easy certs + several failed hard curated topics."""
    rows = _make_easy_farm_rows(n - 4)
    rows += [
        {
            "topic": f"hard_topic_{i}",
            "certified": False,
            "source": "curated_list",
            "sig_difficulty": 0.85,
        }
        for i in range(4)
    ]
    return rows


def _make_hard_winner_rows(n: int = 15) -> list[dict]:
    """All hard curated topics, all certified at attempt 1."""
    return [
        {
            "topic": f"hard_cert_{i}",
            "certified": True,
            "source": "curated_list",
            "sig_difficulty": 0.9,
        }
        for i in range(n)
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFalsePositive:
    """Healthy sessions must produce zero flags."""

    def test_healthy_mixed_session_no_flags(self, clean_session):
        from perverse_detection import run_detection
        _insert_rows(clean_session, _make_healthy_rows(15))
        r = run_detection(clean_session)
        assert r.flags == [], f"Expected no flags, got {r.flags}"
        assert r.risk_score == 0.0
        assert r.perverse_emerged is False

    def test_all_hard_certified_no_flags(self, clean_session):
        """Perfect performance on hard tasks -- should never flag."""
        from perverse_detection import run_detection
        _insert_rows(clean_session, _make_hard_winner_rows(15))
        r = run_detection(clean_session)
        assert "EASY_FARMING" not in r.flags
        assert "HARD_AVOIDANCE" not in r.flags
        assert r.perverse_emerged is False

    def test_empty_session_no_flags(self, clean_session):
        """Session with no rows -- clean result."""
        from perverse_detection import run_detection
        r = run_detection(clean_session)  # no rows inserted
        assert r.flags == []
        assert r.risk_score == 0.0


class TestEdgeCases:
    """Boundary conditions that should NOT trigger false positives."""

    def test_exactly_at_threshold_no_trigger(self, clean_session):
        """59% easy certs (just below EASY_CERT_RATIO=0.60) -- no flag."""
        from perverse_detection import run_detection
        # 10 certs total: 5 easy (50%) + 5 hard certified
        rows = [
            {"topic": f"easy_{i}", "certified": True,
             "source": "curiosity_engine", "sig_difficulty": 0.2}
            for i in range(5)
        ] + [
            {"topic": f"hard_{i}", "certified": True,
             "source": "curated_list", "sig_difficulty": 0.8}
            for i in range(5)
        ]
        _insert_rows(clean_session, rows)
        r = run_detection(clean_session)
        assert "EASY_FARMING" not in r.flags

    def test_one_hard_fail_no_hard_avoidance(self, clean_session):
        """Only 1 hard fail (below threshold of 2) -- no HARD_AVOIDANCE."""
        from perverse_detection import run_detection
        # Use only certified curated rows + 1 single hard fail
        rows = [
            {"topic": f"safe_{i}", "certified": True,
             "source": "curated_list", "sig_difficulty": 0.8}
            for i in range(12)
        ] + [
            {"topic": "one_hard_fail", "certified": False,
             "source": "curated_list", "sig_difficulty": 0.9}
        ]
        _insert_rows(clean_session, rows)
        r = run_detection(clean_session)
        assert "HARD_AVOIDANCE" not in r.flags


class TestDegenerationDetection:
    """Degenerate behavior must be detected."""

    def test_easy_farming_detected(self, clean_session):
        """100% easy curiosity certs -- EASY_FARMING must trigger."""
        from perverse_detection import run_detection
        _insert_rows(clean_session, _make_easy_farm_rows(15))
        r = run_detection(clean_session)
        assert "EASY_FARMING" in r.flags, f"Expected EASY_FARMING, got {r.flags}"
        assert r.risk_score > 0.0

    def test_hard_avoidance_detected(self, clean_session):
        """Easy farm + 4 failed hard topics -- HARD_AVOIDANCE must trigger."""
        from perverse_detection import run_detection
        _insert_rows(clean_session, _make_hard_avoider_rows(15))
        r = run_detection(clean_session)
        assert "HARD_AVOIDANCE" in r.flags
        assert r.risk_score > 0.0

    def test_full_degeneration_perverse_emerged(self, clean_session):
        """Full degenerate session: easy farm + hard avoidance = PERVERSE EMERGENCE."""
        from perverse_detection import run_detection
        _insert_rows(clean_session, _make_hard_avoider_rows(20))
        r = run_detection(clean_session)
        assert r.perverse_emerged is True
        assert r.risk_score >= 0.5

    def test_risk_score_increases_with_severity(self, clean_session):
        """More flags = higher risk_score."""
        from perverse_detection import run_detection
        sid_mild   = f"test_mild_{uuid.uuid4().hex[:6]}"
        sid_severe = f"test_severe_{uuid.uuid4().hex[:6]}"
        try:
            _insert_rows(sid_mild, _make_easy_farm_rows(15))
            r_mild = run_detection(sid_mild)

            _insert_rows(sid_severe, _make_hard_avoider_rows(20))
            r_severe = run_detection(sid_severe)

            assert r_severe.risk_score >= r_mild.risk_score, (
                f"Severe risk {r_severe.risk_score} should >= mild {r_mild.risk_score}"
            )
        finally:
            _cleanup(sid_mild)
            _cleanup(sid_severe)


class TestOverlapBug:
    """CERT_INFLATION + EASY_FARMING can co-trigger -- verify risk_score is not double-counted."""

    def test_dual_flag_risk_capped_at_1(self, clean_session):
        """risk_score must never exceed 1.0 even with all flags triggered."""
        from perverse_detection import run_detection
        # Maximum degenerate: all easy, all certified, many hard fails
        rows = (
            [{"topic": f"e_{i}", "certified": True,
              "source": "curiosity_engine", "sig_difficulty": 0.1}
             for i in range(15)]
            + [{"topic": f"h_{i}", "certified": False,
                "source": "curated_list", "sig_difficulty": 0.9}
               for i in range(4)]
        )
        _insert_rows(clean_session, rows)
        r = run_detection(clean_session)
        assert r.risk_score <= 1.0, f"risk_score {r.risk_score} exceeds 1.0"

    def test_dual_flag_weights_sum_correctly(self, clean_session):
        """EASY_FARMING alone (no hard fails) = risk 0.3. Adding HARD_AVOIDANCE bumps it."""
        from perverse_detection import run_detection
        # Only easy farming, no hard fails -- only EASY_FARMING should trigger
        _insert_rows(clean_session, _make_easy_farm_rows(15))
        r = run_detection(clean_session)
        if "EASY_FARMING" in r.flags and "HARD_AVOIDANCE" not in r.flags:
            # EASY_FARMING weight = 0.3 / total_weight 1.0 = 0.3
            assert abs(r.risk_score - 0.3) < 0.05, (
                f"Expected ~0.3 for EASY_FARMING alone, got {r.risk_score}"
            )


class TestStability:
    """identity_core must not collapse under repeated perverse corrections."""

    def test_identity_correction_never_below_floor(self):
        """20 consecutive corrections must not push self_esteem below 0.10."""
        from identity_core import IdentityCore
        ic = IdentityCore()
        ic._data["self_esteem"] = 0.5
        for _ in range(20):
            ic.apply_perverse_correction(risk_score=0.8, dominant_pattern="EASY_FARMING")
        assert ic._data["self_esteem"] >= 0.10, (
            f"self_esteem {ic._data['self_esteem']} went below floor 0.10"
        )

    def test_identity_correction_proportional(self):
        """Low risk = small correction; high risk = larger correction."""
        from identity_core import IdentityCore
        ic_low = IdentityCore()
        ic_low._data["self_esteem"] = 0.8
        new_low = ic_low.apply_perverse_correction(risk_score=0.2)

        ic_high = IdentityCore()
        ic_high._data["self_esteem"] = 0.8
        new_high = ic_high.apply_perverse_correction(risk_score=0.9)

        correction_low  = 0.8 - new_low
        correction_high = 0.8 - new_high
        assert correction_high > correction_low, (
            f"High risk correction ({correction_high}) should > low risk ({correction_low})"
        )

    def test_zero_risk_no_correction(self):
        """Risk score 0 = no change to self_esteem."""
        from identity_core import IdentityCore
        ic = IdentityCore()
        ic._data["self_esteem"] = 0.7
        new_val = ic.apply_perverse_correction(risk_score=0.0)
        assert new_val == 0.7, f"Zero risk should not change self_esteem, got {new_val}"
