"""perverse_detection.py -- Perverse Emergence Detection (backlog #18).

Detects when SHARD is gaming its own reward signal without improving competence.

Runs at end of each study session. Reads activation_log for the current
session, applies 4 detection rules, returns a PerverseDetectionResult.

Rules:
  1. EASY_FARMING     -- >= EASY_CERT_RATIO certs from curiosity/hybrid + low difficulty
  2. HARD_AVOIDANCE   -- >= HARD_FAIL_THRESHOLD curated_list topics failed/uncertified
  3. STAGNATION       -- high cert_rate but improvement_slope near 0 across sessions
  4. CERT_INFLATION   -- weighted cert_rate much lower than raw cert_rate (delta > threshold)

Output: flags + risk_score (0-1) + dominant_pattern + recommendation
Integration: called by night_runner at session end.
  - flags stored in identity_core (behavioral_flags)
  - if PERVERSE_EMERGENCE: goal_engine enqueues most-avoided hard topic
  - no prompt injection -- this is a control layer, not cognitive
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("shard.perverse_detection")

# ── Tunables ──────────────────────────────────────────────────────────────────
RECENT_CYCLES       = 20    # how many activation_log rows to analyze per session
EASY_CERT_RATIO     = 0.60  # >=60% easy certs triggers EASY_FARMING
HARD_FAIL_THRESHOLD = 2     # >=2 failed curated topics triggers HARD_AVOIDANCE
CERT_INFLATION_DELTA= 0.15  # raw_rate - weighted_rate > 0.15 triggers CERT_INFLATION
STAGNATION_SESSIONS = 10    # look back N sessions to compute improvement slope
STAGNATION_SLOPE    = 0.02  # abs(slope) < 0.02 with cert_rate > 0.7 = stagnation

_EASY_SOURCES = {"curiosity_engine"}


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class PerverseDetectionResult:
    flags:            list[str]       = field(default_factory=list)
    risk_score:       float           = 0.0   # 0.0 (clean) → 1.0 (critical)
    dominant_pattern: str | None      = None
    recommendation:   str | None      = None
    details:          dict            = field(default_factory=dict)
    perverse_emerged: bool            = False  # True if any critical flag raised

    def to_dict(self) -> dict:
        return {
            "flags":            self.flags,
            "risk_score":       round(self.risk_score, 3),
            "dominant_pattern": self.dominant_pattern,
            "recommendation":   self.recommendation,
            "perverse_emerged": self.perverse_emerged,
            "details":          self.details,
        }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_session_rows(session_id: str) -> list[dict]:
    try:
        from shard_db import query as db_query
        return db_query(
            "SELECT certified, source, sig_difficulty, topic, score "
            "FROM activation_log WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, RECENT_CYCLES),
        )
    except Exception as exc:
        logger.warning("[perverse] DB read failed: %s", exc)
        return []


def _load_recent_sessions_cert_rates(n: int = STAGNATION_SESSIONS) -> list[float]:
    """Returns list of raw cert rates per session (most recent first)."""
    try:
        from shard_db import query as db_query
        rows = db_query(
            "SELECT session_id, certified FROM activation_log "
            "ORDER BY timestamp DESC LIMIT ?",
            (n * 10,),  # rough upper bound
        )
        if not rows:
            return []
        # Group by session_id preserving order
        sessions: dict[str, list] = {}
        for r in rows:
            sid = r["session_id"]
            if sid not in sessions:
                sessions[sid] = []
            sessions[sid].append(r["certified"])
        rates = []
        for sid, certs in list(sessions.items())[:n]:
            if certs:
                rates.append(sum(1 for c in certs if c) / len(certs))
        return rates
    except Exception:
        return []


def _weighted_cert_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.5
    total_weight = 0.0
    weighted_certs = 0.0
    for r in rows:
        diff = r["sig_difficulty"] or 0.5
        src  = r["source"] or ""
        if src in _EASY_SOURCES and diff < 0.3:
            w = 0.5
        elif diff > 0.7 and src in ("curated_list", "improvement_engine"):
            w = 1.5
        else:
            w = 1.0
        total_weight += w
        if r["certified"]:
            weighted_certs += w
    return weighted_certs / total_weight if total_weight > 0 else 0.5


def _raw_cert_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.5
    return sum(1 for r in rows if r["certified"]) / len(rows)


def _improvement_slope(rates: list[float]) -> float:
    """Simple linear slope over list of rates (oldest→newest)."""
    n = len(rates)
    if n < 3:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(rates) / n
    num = sum((xs[i] - x_mean) * (rates[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    return num / den if den != 0 else 0.0


# ── Rule evaluators ───────────────────────────────────────────────────────────

def _rule_easy_farming(rows: list[dict]) -> tuple[bool, dict]:
    if not rows:
        return False, {}
    cert_rows = [r for r in rows if r["certified"]]
    if not cert_rows:
        return False, {}
    easy_certs = [
        r for r in cert_rows
        if (r["source"] or "") in _EASY_SOURCES and (r["sig_difficulty"] or 0.5) < 0.3
    ]
    ratio = len(easy_certs) / len(cert_rows)
    triggered = ratio >= EASY_CERT_RATIO
    return triggered, {
        "easy_cert_ratio": round(ratio, 3),
        "easy_certs": len(easy_certs),
        "total_certs": len(cert_rows),
    }


def _rule_hard_avoidance(rows: list[dict]) -> tuple[bool, dict]:
    if not rows:
        return False, {}
    hard_rows = [
        r for r in rows
        if (r["source"] or "") in ("curated_list", "improvement_engine")
        and (r["sig_difficulty"] or 0.5) > 0.6
    ]
    failed_hard = [r for r in hard_rows if not r["certified"]]
    triggered = len(failed_hard) >= HARD_FAIL_THRESHOLD
    return triggered, {
        "hard_topics_attempted": len(hard_rows),
        "hard_topics_failed": len(failed_hard),
        "failed_topics": [r["topic"] for r in failed_hard[:5]],
    }


def _rule_cert_inflation(rows: list[dict]) -> tuple[bool, dict]:
    raw      = _raw_cert_rate(rows)
    weighted = _weighted_cert_rate(rows)
    delta    = raw - weighted
    triggered = delta > CERT_INFLATION_DELTA and raw > 0.6
    return triggered, {
        "raw_cert_rate":      round(raw, 3),
        "weighted_cert_rate": round(weighted, 3),
        "delta":              round(delta, 3),
    }


def _rule_stagnation(rows: list[dict]) -> tuple[bool, dict]:
    rates = _load_recent_sessions_cert_rates()
    if len(rates) < 4:
        return False, {"reason": "not enough sessions"}
    slope     = _improvement_slope(list(reversed(rates)))  # oldest first
    raw_rate  = _raw_cert_rate(rows) if rows else sum(rates[:3]) / 3
    triggered = abs(slope) < STAGNATION_SLOPE and raw_rate > 0.7
    return triggered, {
        "improvement_slope": round(slope, 4),
        "avg_cert_rate":     round(sum(rates) / len(rates), 3),
        "sessions_analyzed": len(rates),
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def run_detection(session_id: str) -> PerverseDetectionResult:
    """Run all rules for the given session. Returns PerverseDetectionResult.

    Call this at the end of a study session. Does NOT modify any state --
    the caller (night_runner) is responsible for acting on the result.
    """
    result = PerverseDetectionResult()
    rows   = _load_session_rows(session_id)

    if not rows:
        logger.debug("[perverse] No rows for session %s -- skipping detection.", session_id)
        return result

    rules = [
        ("EASY_FARMING",   _rule_easy_farming,   0.3),  # weight in risk_score
        ("HARD_AVOIDANCE", _rule_hard_avoidance,  0.3),
        ("CERT_INFLATION", _rule_cert_inflation,  0.2),
        ("STAGNATION",     _rule_stagnation,      0.2),
    ]

    total_weight  = 0.0
    weighted_risk = 0.0

    for flag_name, rule_fn, weight in rules:
        try:
            triggered, details = rule_fn(rows)
        except Exception as exc:
            logger.warning("[perverse] Rule %s failed: %s", flag_name, exc)
            continue
        if triggered:
            result.flags.append(flag_name)
            result.details[flag_name] = details
            weighted_risk += weight
        total_weight += weight

    result.risk_score = round(weighted_risk / total_weight, 3) if total_weight else 0.0

    # Determine dominant pattern (first triggered flag, by weight)
    flag_weights = {"EASY_FARMING": 0.3, "HARD_AVOIDANCE": 0.3,
                    "CERT_INFLATION": 0.2, "STAGNATION": 0.2}
    if result.flags:
        result.dominant_pattern = max(result.flags, key=lambda f: flag_weights.get(f, 0))

    # PERVERSE_EMERGENCE = at least 2 rules triggered or risk_score >= 0.5
    result.perverse_emerged = len(result.flags) >= 2 or result.risk_score >= 0.5

    # Build recommendation
    if result.perverse_emerged:
        if "HARD_AVOIDANCE" in result.flags:
            avoided = result.details.get("HARD_AVOIDANCE", {}).get("failed_topics", [])
            rec_topic = avoided[0] if avoided else "a curated hard topic"
            result.recommendation = f"Force-enqueue '{rec_topic}' as next session goal."
        elif "EASY_FARMING" in result.flags:
            result.recommendation = "Increase curated_list weight in topic selection."
        else:
            result.recommendation = "Review topic selection diversity."

    # Log
    if result.flags:
        logger.warning(
            "[SHADOW] Session %s -- flags=%s  risk=%.2f  dominant=%s  perverse=%s",
            session_id[:8], result.flags, result.risk_score,
            result.dominant_pattern, result.perverse_emerged,
        )
        if result.perverse_emerged:
            avoided_str = ""
            if "HARD_AVOIDANCE" in result.details:
                topics = result.details["HARD_AVOIDANCE"].get("failed_topics", [])
                avoided_str = f" | avoided: {topics}"
            cert_str = ""
            if "CERT_INFLATION" in result.details:
                d = result.details["CERT_INFLATION"]
                n_rows = len(rows)
                easy = result.details.get("EASY_FARMING", {}).get("easy_certs", "?")
                cert_str = (
                    f" | cert_rate inflated by easy topics: {easy}/{n_rows} certs were low-difficulty"
                )
            logger.warning(
                "[SHADOW] PERVERSE EMERGENCE%s%s",
                cert_str, avoided_str,
            )
    else:
        logger.debug("[perverse] Session %s clean (risk=0.0).", session_id[:8])

    return result
