"""test_task3.py — The Dirty Data Trap Benchmark.

Tests that optimized_processor.py is:
  1. CORRECT: produces identical results to legacy on dirty data
  2. FAST: at least 30% faster than legacy (relative, machine-independent)
  3. CLEAN: uses modern Python patterns, not just try/except wrapping

Exit Code 0 = SHARD wins.
Exit Code 1 = keep trying.

Run:  pytest test_task3.py -v
"""
import copy
import sys
import time
from pathlib import Path

import pytest

TASK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK_DIR))

from legacy_processor import TRANSACTIONS, process_transactions, _generate_transactions


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def optimized_module():
    """Import the optimized module."""
    spec_path = TASK_DIR / "optimized_processor.py"
    if not spec_path.exists():
        pytest.fail(
            f"optimized_processor.py not found at {spec_path}\n"
            "Create this file with an optimized process_transactions(transactions) function."
        )
    import importlib
    if "optimized_processor" in sys.modules:
        del sys.modules["optimized_processor"]
    return importlib.import_module("optimized_processor")


@pytest.fixture(scope="session")
def legacy_result():
    """Reference result from legacy processor."""
    return process_transactions(copy.deepcopy(TRANSACTIONS))


@pytest.fixture(scope="session")
def optimized_result(optimized_module):
    """Result from optimized processor."""
    return optimized_module.process_transactions(copy.deepcopy(TRANSACTIONS))


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1: CORRECTNESS — exact value matching against legacy
# ══════════════════════════════════════════════════════════════════════════════

class TestCorrectness:
    """Optimized must produce identical results to legacy on dirty data."""

    def test_total_completed(self, legacy_result, optimized_result):
        """Total completed amount must match exactly."""
        expected = legacy_result["total_completed"]
        got = optimized_result["total_completed"]
        assert got == expected, (
            f"total_completed wrong: expected {expected}, got {got}. "
            f"Diff: {got - expected:+.2f}. "
            f"Check: string amounts coerced? negative amounts included? zero amounts included?"
        )

    def test_avg_completed(self, legacy_result, optimized_result):
        """Average of completed transactions must match."""
        expected = legacy_result["avg_completed"]
        got = optimized_result["avg_completed"]
        assert got == expected, (
            f"avg_completed wrong: expected {expected}, got {got}. "
            f"Check: are you dividing by the right count? Zero-amount transactions count too."
        )

    def test_by_category(self, legacy_result, optimized_result):
        """Per-category totals must match. Categories must be cleaned (stripped)."""
        expected = legacy_result["by_category"]
        got = optimized_result["by_category"]

        # Check all expected categories exist
        for cat, val in expected.items():
            assert cat in got, (
                f"Missing category '{cat}'. Got categories: {list(got.keys())}. "
                f"Did you strip whitespace from category names? "
                f"Did you map empty strings to 'uncategorized'?"
            )
            assert got[cat] == val, (
                f"Category '{cat}' total wrong: expected {val}, got {got[cat]}. "
                f"Diff: {got[cat] - val:+.2f}"
            )

        # Check no extra categories
        extra = set(got.keys()) - set(expected.keys())
        assert not extra, (
            f"Extra categories found: {extra}. "
            f"Whitespace-padded categories should be stripped to their clean name, "
            f"not treated as separate categories."
        )

    def test_by_month(self, legacy_result, optimized_result):
        """Per-month totals must match. Epoch timestamps must be handled."""
        expected = legacy_result["by_month"]
        got = optimized_result["by_month"]
        assert got == expected, (
            f"by_month mismatch.\n"
            f"Expected months: {list(expected.keys())}\n"
            f"Got months: {list(got.keys())}\n"
            f"Check: are you handling epoch int timestamps alongside ISO strings?"
        )

    def test_unique_merchants(self, legacy_result, optimized_result):
        """Merchant count must handle missing keys and unicode names."""
        expected = legacy_result["unique_merchants"]
        got = optimized_result["unique_merchants"]
        assert got == expected, (
            f"unique_merchants wrong: expected {expected}, got {got}. "
            f"Check: missing 'merchant' keys should default to 'unknown'. "
            f"Unicode merchant names (e.g., cafe_muller_naive) must be preserved."
        )

    def test_top_merchants(self, legacy_result, optimized_result):
        """Top 5 merchants by total must match in order and values."""
        expected = legacy_result["top_merchants"]
        got = optimized_result["top_merchants"]
        assert len(got) == 5, f"Expected 5 top merchants, got {len(got)}"

        for i, (exp_m, exp_t) in enumerate(expected):
            got_m, got_t = got[i]
            assert got_m == exp_m, (
                f"Top merchant #{i+1} name wrong: expected '{exp_m}', got '{got_m}'"
            )
            assert got_t == exp_t, (
                f"Top merchant #{i+1} total wrong: expected {exp_t}, got {got_t}"
            )

    def test_duplicate_ids(self, legacy_result, optimized_result):
        """Duplicate transaction IDs must be detected."""
        expected = legacy_result["duplicate_ids"]
        got = optimized_result["duplicate_ids"]
        assert got == expected, (
            f"duplicate_ids wrong: expected {expected}, got {got}. "
            f"Two pairs of duplicate IDs exist in the data."
        )

    def test_flagged_negative(self, legacy_result, optimized_result):
        """Negative amounts on completed transactions must be flagged."""
        expected = legacy_result["flagged"]
        got = optimized_result["flagged"]
        assert got == expected, (
            f"flagged wrong: expected {expected}, got {got}. "
            f"Negative amount on completed transaction = data entry error = must be flagged."
        )

    def test_currency_totals(self, legacy_result, optimized_result):
        """Per-currency totals must match."""
        expected = legacy_result["currency_totals"]
        got = optimized_result["currency_totals"]
        assert got == expected, (
            f"currency_totals wrong.\n"
            f"Expected: {expected}\n"
            f"Got: {got}"
        )

    def test_return_type_and_keys(self, optimized_result):
        """Result must be a dict with all required keys."""
        required_keys = [
            "total_completed", "by_category", "by_month", "unique_merchants",
            "avg_completed", "top_merchants", "duplicate_ids", "flagged",
            "currency_totals",
        ]
        for key in required_keys:
            assert key in optimized_result, f"Missing key in result: '{key}'"


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2: PERFORMANCE — must be measurably faster than legacy
# ══════════════════════════════════════════════════════════════════════════════

class TestPerformance:
    """Optimized code must be genuinely faster, not just wrapped in try/except."""

    def _median_time(self, fn, data, runs=7):
        """Run fn(data) multiple times and return median elapsed time."""
        times = []
        for _ in range(runs):
            data_copy = copy.deepcopy(data)
            t0 = time.perf_counter()
            fn(data_copy)
            times.append(time.perf_counter() - t0)
        times.sort()
        return times[len(times) // 2]

    def test_faster_than_legacy(self, optimized_module):
        """Optimized must be at least 30% faster than legacy on same data."""
        data = TRANSACTIONS

        legacy_time = self._median_time(process_transactions, data)
        optimized_time = self._median_time(
            optimized_module.process_transactions, data
        )

        speedup = legacy_time / optimized_time if optimized_time > 0 else 999
        threshold = 1.3  # must be at least 1.3x faster

        assert speedup >= threshold, (
            f"Not fast enough. Legacy: {legacy_time*1000:.1f}ms, "
            f"Optimized: {optimized_time*1000:.1f}ms, "
            f"Speedup: {speedup:.2f}x (need >= {threshold}x). "
            f"A try/except wrapper has the same algorithmic complexity as legacy. "
            f"Use defaultdict, Counter, single-pass aggregation, or batch validation."
        )

    def test_scales_linearly(self, optimized_module):
        """Performance must scale linearly with 5x data."""
        small_data = _generate_transactions(n=2000, seed=99)
        large_data = _generate_transactions(n=10000, seed=99)

        small_time = self._median_time(
            optimized_module.process_transactions, small_data
        )
        large_time = self._median_time(
            optimized_module.process_transactions, large_data
        )

        # With 5x data, should take no more than 7x time (allowing overhead)
        ratio = large_time / small_time if small_time > 0 else 999
        assert ratio < 7.0, (
            f"Non-linear scaling detected. 2K: {small_time*1000:.1f}ms, "
            f"10K: {large_time*1000:.1f}ms, ratio: {ratio:.1f}x (max 7x for 5x data). "
            f"Check for O(n^2) patterns: nested loops, repeated list scans."
        )


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3: DIRTY DATA RESILIENCE — specific edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestDirtyDataResilience:
    """The optimized code must handle all 10 types of data corruption."""

    def test_string_amount(self, optimized_module):
        """String amounts like '12.50' must be coerced to float."""
        tx = [{"id": "T1", "amount": "42.50", "currency": "EUR",
               "category": "food", "status": "completed",
               "timestamp": "2025-06-15T10:00:00", "merchant": "m1"}]
        result = optimized_module.process_transactions(tx)
        assert result["total_completed"] == 42.50, (
            f"String amount '42.50' not coerced: got {result['total_completed']}"
        )

    def test_missing_merchant(self, optimized_module):
        """Missing 'merchant' key must not crash, default to 'unknown'."""
        tx = [{"id": "T1", "amount": 10.0, "currency": "EUR",
               "category": "food", "status": "completed",
               "timestamp": "2025-06-15T10:00:00"}]  # no merchant key!
        result = optimized_module.process_transactions(tx)
        assert result["unique_merchants"] >= 1

    def test_epoch_timestamp(self, optimized_module):
        """Epoch int timestamps must be parsed correctly."""
        # 2025-07-01 00:00:00 UTC = 1751328000
        tx = [{"id": "T1", "amount": 100.0, "currency": "EUR",
               "category": "food", "status": "completed",
               "timestamp": 1751328000, "merchant": "m1"}]
        result = optimized_module.process_transactions(tx)
        assert "2025-07" in result["by_month"] or "2025-06" in result["by_month"], (
            f"Epoch timestamp not parsed. Got months: {list(result['by_month'].keys())}"
        )

    def test_whitespace_category(self, optimized_module):
        """Categories with trailing whitespace must be stripped."""
        tx = [
            {"id": "T1", "amount": 10.0, "currency": "EUR",
             "category": "food", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m1"},
            {"id": "T2", "amount": 20.0, "currency": "EUR",
             "category": "food  ", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m1"},
        ]
        result = optimized_module.process_transactions(tx)
        assert "food" in result["by_category"], (
            f"Whitespace category not stripped. Got: {list(result['by_category'].keys())}"
        )
        assert "food  " not in result["by_category"], (
            "Whitespace category treated as separate! Must strip."
        )
        assert result["by_category"]["food"] == 30.0

    def test_empty_category(self, optimized_module):
        """Empty string category must map to 'uncategorized'."""
        tx = [{"id": "T1", "amount": 5.0, "currency": "EUR",
               "category": "", "status": "completed",
               "timestamp": "2025-06-15T10:00:00", "merchant": "m1"}]
        result = optimized_module.process_transactions(tx)
        assert "uncategorized" in result["by_category"], (
            f"Empty category not mapped. Got: {list(result['by_category'].keys())}"
        )

    def test_negative_completed_flagged(self, optimized_module):
        """Negative amount on completed transaction must be flagged."""
        tx = [
            {"id": "T1", "amount": 100.0, "currency": "EUR",
             "category": "food", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m1"},
            {"id": "T2", "amount": -25.0, "currency": "EUR",
             "category": "food", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m1"},
        ]
        result = optimized_module.process_transactions(tx)
        assert "T2" in result["flagged"], (
            f"Negative completed not flagged. flagged={result['flagged']}"
        )
        # Total should include the negative (it's a valid completed tx)
        assert result["total_completed"] == 75.0

    def test_duplicate_ids_detected(self, optimized_module):
        """Duplicate IDs must be reported."""
        tx = [
            {"id": "DUP", "amount": 10.0, "currency": "EUR",
             "category": "food", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m1"},
            {"id": "DUP", "amount": 20.0, "currency": "EUR",
             "category": "food", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m2"},
            {"id": "UNIQUE", "amount": 30.0, "currency": "EUR",
             "category": "food", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m3"},
        ]
        result = optimized_module.process_transactions(tx)
        assert result["duplicate_ids"] == ["DUP"]

    def test_zero_amount_completed(self, optimized_module):
        """Zero-amount completed transaction: counts in avg, not flagged."""
        tx = [
            {"id": "T1", "amount": 100.0, "currency": "EUR",
             "category": "food", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m1"},
            {"id": "T2", "amount": 0, "currency": "EUR",
             "category": "food", "status": "completed",
             "timestamp": "2025-06-15T10:00:00", "merchant": "m1"},
        ]
        result = optimized_module.process_transactions(tx)
        # avg = (100 + 0) / 2 = 50.0
        assert result["avg_completed"] == 50.0, (
            f"Zero amount broke average: expected 50.0, got {result['avg_completed']}"
        )
        assert "T2" not in result["flagged"], "Zero is not negative — don't flag it"

    def test_unicode_merchant(self, optimized_module):
        """Unicode merchant names must be preserved."""
        tx = [{"id": "T1", "amount": 10.0, "currency": "EUR",
               "category": "food", "status": "completed",
               "timestamp": "2025-06-15T10:00:00",
               "merchant": "cafe_muller_naive"}]
        result = optimized_module.process_transactions(tx)
        assert result["top_merchants"][0][0] == "cafe_muller_naive"


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4: STRUCTURAL QUALITY
# ══════════════════════════════════════════════════════════════════════════════

class TestStructure:
    """The optimized code must be a genuine improvement, not a band-aid."""

    def test_has_process_transactions(self, optimized_module):
        """Must expose process_transactions() function."""
        assert hasattr(optimized_module, "process_transactions"), (
            "Missing process_transactions function"
        )

    def test_no_excessive_try_except(self):
        """Must not have more than 5 try/except blocks (lazy wrapping)."""
        source = (TASK_DIR / "optimized_processor.py").read_text(encoding="utf-8")
        import re
        try_count = len(re.findall(r"\btry\s*:", source))
        assert try_count <= 5, (
            f"Found {try_count} try/except blocks. Max allowed: 5. "
            f"Use explicit type checking (isinstance) and .get() with defaults "
            f"instead of wrapping every field access in try/except. "
            f"This is about writing CLEAN code, not defensive spaghetti."
        )

    def test_uses_modern_patterns(self):
        """Must use at least one modern Python pattern."""
        source = (TASK_DIR / "optimized_processor.py").read_text(encoding="utf-8")
        modern_patterns = [
            "defaultdict", "Counter", "collections.",
            "enumerate", "zip(", "{k:", "{v:", "comprehension",
            ":=",  # walrus
        ]
        found = [p for p in modern_patterns if p in source]
        assert len(found) >= 1, (
            f"No modern Python patterns detected. Use defaultdict, Counter, "
            f"dict comprehensions, or other Pythonic constructs. "
            f"The goal is BETTER code, not just working code."
        )


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
