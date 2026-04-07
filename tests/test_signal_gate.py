"""Tests for signal_gate — Signal scoring, gate selection, build_strategy_signal."""
import pytest
from unittest.mock import patch, MagicMock


class TestSignalScore:

    def setup_method(self):
        from backend.signal_gate import Signal
        self.Signal = Signal

    def test_strategy_signal_score(self):
        s = self.Signal(content="x", confidence=0.8, type="strategy", source="test")
        # 0.8 * 1.1 = 0.88
        assert s.score() == pytest.approx(0.88, abs=0.01)

    def test_diagnostic_signal_score_with_weight(self):
        s = self.Signal(content="x", confidence=0.5, type="diagnostic", source="IDEMPOTENCY")
        # 0.5 * 1.5 * 2.0 = 1.5 (if diag_weights["IDEMPOTENCY"] = 2.0)
        score = s.score(diag_weights={"IDEMPOTENCY": 2.0})
        assert score == pytest.approx(1.5, abs=0.01)

    def test_diagnostic_signal_score_without_diag_weights(self):
        s = self.Signal(content="x", confidence=0.6, type="diagnostic", source="X")
        # 0.6 * 1.5 = 0.90
        assert s.score() == pytest.approx(0.90, abs=0.01)

    def test_kb_signal_score(self):
        s = self.Signal(content="y", confidence=1.0, type="kb", source="knowledge_base")
        assert s.score() == pytest.approx(1.0, abs=0.01)


class TestGateFiltering:

    def setup_method(self):
        from backend.signal_gate import Signal, gate
        self.Signal = Signal
        self.gate = gate

    def _make(self, confidence, stype="kb", content="x"):
        return self.Signal(content=content, confidence=confidence, type=stype, source="test")

    def test_gate_returns_top_k(self):
        signals = [self._make(0.9), self._make(0.5), self._make(0.7), self._make(0.3)]
        result = self.gate(signals, top_k=2)
        assert len(result) == 2
        assert result[0].confidence == 0.9

    def test_gate_drops_below_min_confidence(self):
        signals = [self._make(0.05), self._make(0.8)]
        result = self.gate(signals, top_k=3, min_confidence=0.1)
        assert len(result) == 1
        assert result[0].confidence == 0.8

    def test_gate_drops_empty_content(self):
        signals = [self._make(0.9, content=""), self._make(0.7)]
        result = self.gate(signals, top_k=3)
        assert len(result) == 1

    def test_gate_empty_input(self):
        assert self.gate([], top_k=3) == []

    def test_strategy_outranks_kb_at_same_confidence(self):
        # strategy weight=1.1, kb weight=1.0 → strategy scores higher
        strategy = self.Signal(content="s", confidence=0.8, type="strategy", source="s")
        kb = self.Signal(content="k", confidence=0.8, type="kb", source="k")
        result = self.gate([kb, strategy], top_k=2)
        assert result[0].type == "strategy"


class TestStrategyMultiplier:

    def setup_method(self):
        from backend.signal_gate import strategy_multiplier
        self.fn = strategy_multiplier

    def test_high_avg_score_boosts(self):
        mult = self.fn(avg_score=9.0)
        assert mult > 1.0

    def test_low_avg_score_low_mult(self):
        mult = self.fn(avg_score=2.0)
        assert mult < 1.0

    def test_success_rate_boosts(self):
        m_no_sr  = self.fn(avg_score=7.0, success_rate=None)
        m_high_sr = self.fn(avg_score=7.0, success_rate=1.0)
        assert m_high_sr > m_no_sr

    def test_clamped_to_range(self):
        # extreme values should not escape [0.8, 1.5]
        assert 0.8 <= self.fn(avg_score=0.0, success_rate=0.0) <= 1.5
        assert 0.8 <= self.fn(avg_score=10.0, success_rate=1.0) <= 1.5


class TestBuildStrategySignal:

    def _make_strategy(self, text, score, outcome="success"):
        return {"strategy": text, "topic": "test", "score": score, "outcome": outcome}

    def test_empty_strategies_returns_none(self):
        from backend.signal_gate import build_strategy_signal
        assert build_strategy_signal([], topic="any") is None

    def test_valid_strategies_returns_signal(self):
        from backend.signal_gate import build_strategy_signal
        strats = [
            self._make_strategy("use guard clauses at entry points", 8.0),
            self._make_strategy("return deep copy of mutable state", 7.5),
        ]
        result = build_strategy_signal(strats, topic="mutation_state task")
        assert result is not None
        assert result.type == "strategy"
        assert 0.0 < result.confidence <= 1.0

    def test_confidence_clamped_to_one(self):
        from backend.signal_gate import build_strategy_signal
        strats = [self._make_strategy("perfect strategy", 10.0)] * 3
        with patch("backend.signal_gate.apply_routing", return_value=(strats, 2.0)):
            result = build_strategy_signal(strats, topic="test")
        # Even with boost=2.0, confidence must be <= 1.0
        if result:
            assert result.confidence <= 1.0

    def test_cluster_boost_increases_confidence(self):
        from backend.signal_gate import build_strategy_signal
        strats = [self._make_strategy("use thread lock around shared state", 7.5)]

        # Low boost
        with patch("backend.signal_gate.apply_routing", return_value=(strats, 1.0)):
            sig_low = build_strategy_signal(strats, topic="concurrency test")

        # High boost (concurrency = 1.40)
        with patch("backend.signal_gate.apply_routing", return_value=(strats, 1.40)):
            sig_high = build_strategy_signal(strats, topic="concurrency test")

        if sig_low and sig_high:
            assert sig_high.confidence > sig_low.confidence

    def test_all_blacklisted_returns_none(self):
        from backend.signal_gate import build_strategy_signal
        strats = [self._make_strategy("bcrypt argon2 key derivation", 8.0)]
        with patch("backend.signal_gate.apply_routing", return_value=([], 1.0)):
            result = build_strategy_signal(strats, topic="crypto")
        assert result is None
