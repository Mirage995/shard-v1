"""Minimal tests for gwt_ab_test.py — import + compute_verdict logic."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from gwt_ab_test import compute_verdict


def _make_result(condition, cert_rate, avg_score, avg_llm_calls):
    return {
        "condition": condition,
        "topics": [],
        "aggregated": {
            "cert_rate":               cert_rate,
            "weighted_cert_rate":      cert_rate,
            "avg_score":               avg_score,
            "avg_llm_calls_per_topic": avg_llm_calls,
            "total_time_seconds":      10.0,
        },
    }


def test_compute_verdict_gwt_on_wins():
    a = _make_result("GWT_ON",  cert_rate=0.67, avg_score=8.0, avg_llm_calls=10.0)
    b = _make_result("GWT_OFF", cert_rate=0.33, avg_score=6.0, avg_llm_calls=14.0)
    v = compute_verdict(a, b)
    assert v["winner"] == "GWT_ON"
    assert v["recommendation"] == "KEEP GWT"


def test_compute_verdict_gwt_off_wins():
    a = _make_result("GWT_ON",  cert_rate=0.33, avg_score=5.0, avg_llm_calls=18.0)
    b = _make_result("GWT_OFF", cert_rate=0.67, avg_score=8.0, avg_llm_calls=10.0)
    v = compute_verdict(a, b)
    assert v["winner"] == "GWT_OFF"
    assert v["recommendation"] == "REVERT GWT"


def test_compute_verdict_tie():
    a = _make_result("GWT_ON",  cert_rate=0.50, avg_score=7.0, avg_llm_calls=12.0)
    b = _make_result("GWT_OFF", cert_rate=0.50, avg_score=7.0, avg_llm_calls=12.0)
    v = compute_verdict(a, b)
    assert v["winner"] == "TIE"
    assert v["recommendation"] == "INVESTIGATE"


def test_verdict_contains_required_keys():
    a = _make_result("GWT_ON",  0.5, 7.0, 12.0)
    b = _make_result("GWT_OFF", 0.5, 7.0, 12.0)
    v = compute_verdict(a, b)
    for key in ("winner", "cert_rate_delta", "avg_score_delta", "efficiency_delta", "recommendation"):
        assert key in v
