"""Tests for the data processing pipeline.

Run with: pytest test_task5.py -v
"""
from pathlib import Path

import pytest

# ── Import the fixed version ──────────────────────────────────────────────────
spec_path = Path(__file__).parent / "fixed_pipeline.py"
if not spec_path.exists():
    pytest.skip(f"fixed_pipeline.py not found at {spec_path}", allow_module_level=True)

from fixed_pipeline import Pipeline


# ── Basic processing ─────────────────────────────────────────────────────────

class TestProcessing:

    def test_basic_multiply(self):
        p = Pipeline(multiplier=2.0)
        assert p.process([1, 2, 3]) == [2.0, 4.0, 6.0]

    def test_default_multiplier(self):
        p = Pipeline()
        assert p.process([10, 20]) == [10.0, 20.0]

    def test_negative_values(self):
        p = Pipeline(multiplier=3.0)
        assert p.process([-1, 0, 1]) == [-3.0, 0.0, 3.0]

    def test_empty_batch(self):
        p = Pipeline(multiplier=5.0)
        assert p.process([]) == []

    def test_multiplier_change_affects_cached_values(self):
        """After changing multiplier, ALL values must use the new multiplier,
        even values that were previously processed and cached."""
        p = Pipeline(multiplier=2.0)
        r1 = p.process([5, 10])
        assert r1 == [10.0, 20.0]

        p.set_multiplier(3.0)
        r2 = p.process([5, 10])
        assert r2 == [15.0, 30.0], (
            f"Expected [15.0, 30.0] with multiplier=3 but got {r2}. "
            f"Cached results from multiplier=2 are being returned."
        )

    def test_multiplier_change_mix_cached_and_new(self):
        """Mix of previously-seen and new values after multiplier change."""
        p = Pipeline(multiplier=2.0)
        p.process([1, 2])

        p.set_multiplier(10.0)
        result = p.process([1, 2, 3])  # 1,2 were cached; 3 is new
        assert result == [10.0, 20.0, 30.0], (
            f"Expected [10.0, 20.0, 30.0] but got {result}. "
            f"Cache was not invalidated on multiplier change."
        )

    def test_many_multiplier_changes(self):
        p = Pipeline(multiplier=1.0)
        for m in [1, 2, 5, 10, 0.5]:
            p.set_multiplier(m)
            result = p.process([100])
            assert result == [100 * m], (
                f"With multiplier={m}, process([100]) should give [{100*m}] "
                f"but got {result}."
            )


# ── History tracking ─────────────────────────────────────────────────────────

class TestHistory:

    def test_records_batches(self):
        p = Pipeline()
        p.process([1, 2])
        p.process([3])
        assert p.get_history() == [[1, 2], [3]]

    def test_caller_mutation_does_not_affect_history(self):
        """If the caller mutates the input list after process(),
        the stored history must not change."""
        p = Pipeline()
        data = [1, 2, 3]
        p.process(data)

        data.append(999)
        data[0] = -1

        h = p.get_history()
        assert h[0] == [1, 2, 3], (
            f"History was corrupted by caller mutation: {h[0]}. "
            f"Pipeline should store a copy of the input, not a reference."
        )

    def test_history_mutation_does_not_affect_pipeline(self):
        """Mutating the returned history list must not affect internal state."""
        p = Pipeline()
        p.process([10])
        h = p.get_history()
        h.clear()
        assert p.get_history() == [[10]]

    def test_processed_count(self):
        p = Pipeline()
        p.process([1, 2, 3])
        p.process([4, 5])
        assert p.get_processed_count() == 5


# ── Reset ────────────────────────────────────────────────────────────────────

class TestReset:

    def test_clears_history(self):
        p = Pipeline()
        p.process([1, 2])
        p.reset()
        assert p.get_history() == []

    def test_clears_count(self):
        p = Pipeline()
        p.process([1, 2, 3])
        p.reset()
        assert p.get_processed_count() == 0

    def test_clears_cache(self):
        """After reset, cached values must not persist."""
        p = Pipeline(multiplier=2.0)
        p.process([10])
        p.set_multiplier(5.0)
        p.reset()
        result = p.process([10])
        assert result == [50.0], (
            f"Expected [50.0] after reset with new multiplier, got {result}. "
            f"Cache survived reset()."
        )

    def test_resets_id_sequence(self):
        """After reset, next_id() should restart from 0."""
        p = Pipeline()
        p.next_id()
        p.next_id()
        p.next_id()
        p.reset()
        assert p.next_id() == 0, (
            "ID sequence should restart from 0 after reset()."
        )

    def test_full_reset_cycle(self):
        """Complete cycle: process, change multiplier, reset, process again."""
        p = Pipeline(multiplier=2.0)
        p.process([1, 2, 3, 4, 5])
        p.set_multiplier(10.0)
        p.reset()
        result = p.process([1])
        assert result == [10.0], (
            f"After reset+multiplier change, expected [10.0] but got {result}."
        )
        assert p.get_processed_count() == 1
        assert p.get_history() == [[1]]
        assert p.next_id() == 0


# ── ID generation ────────────────────────────────────────────────────────────

class TestIdGeneration:

    def test_sequential(self):
        p = Pipeline()
        assert p.next_id() == 0
        assert p.next_id() == 1
        assert p.next_id() == 2

    def test_ids_independent_of_processing(self):
        p = Pipeline()
        id1 = p.next_id()
        p.process([1, 2, 3])
        id2 = p.next_id()
        assert id2 == id1 + 1

    def test_ids_across_resets(self):
        """IDs should restart after each reset."""
        p = Pipeline()
        p.next_id()  # 0
        p.next_id()  # 1
        p.reset()
        assert p.next_id() == 0
        p.next_id()  # 1
        p.reset()
        assert p.next_id() == 0


# ── Integration ──────────────────────────────────────────────────────────────

class TestIntegration:

    def test_two_independent_pipelines(self):
        """Two Pipeline instances must not share state."""
        p1 = Pipeline(multiplier=2.0)
        p2 = Pipeline(multiplier=10.0)

        p1.process([5])
        r2 = p2.process([5])
        assert r2 == [50.0], (
            f"Pipeline instances sharing cache: expected [50.0] but got {r2}."
        )

    def test_long_running_usage(self):
        """Simulate many batches with multiplier changes and resets."""
        p = Pipeline(multiplier=1.0)
        for cycle in range(5):
            m = (cycle + 1) * 2.0
            p.set_multiplier(m)
            for batch in range(10):
                result = p.process([1.0])
                assert result == [m], (
                    f"Cycle {cycle}, batch {batch}, multiplier={m}: "
                    f"expected [{m}] but got {result}."
                )
            p.reset()
