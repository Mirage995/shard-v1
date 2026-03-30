"""Tests for the sequence analyzer.

Run with: pytest test_task14.py -v
"""
from pathlib import Path
import pytest

spec_path = Path(__file__).parent / "fixed_analyzer.py"
if not spec_path.exists():
    pytest.skip("fixed_analyzer.py not found", allow_module_level=True)

from fixed_analyzer import compute_changes, find_local_peaks, compute_moving_average, max_change


class TestComputeChanges:

    def test_basic(self):
        assert compute_changes([1, 3, 6, 10]) == [2, 3, 4]

    def test_single_element(self):
        assert compute_changes([5]) == []

    def test_empty(self):
        assert compute_changes([]) == []

    def test_negative_changes(self):
        assert compute_changes([10, 5, 3]) == [-5, -2]

    def test_mixed(self):
        assert compute_changes([1, 4, 2, 7]) == [3, -2, 5]

    def test_two_elements(self):
        assert compute_changes([3, 8]) == [5]

    def test_all_equal(self):
        assert compute_changes([4, 4, 4, 4]) == [0, 0, 0]


class TestFindLocalPeaks:

    def test_single_peak(self):
        assert find_local_peaks([1, 5, 2]) == [1]

    def test_multiple_peaks(self):
        assert find_local_peaks([1, 5, 2, 8, 3]) == [1, 3]

    def test_no_peaks_flat(self):
        assert find_local_peaks([3, 3, 3]) == []

    def test_first_element_not_peak(self):
        """First element cannot be a peak even if it is the largest."""
        assert 0 not in find_local_peaks([10, 5, 2])

    def test_last_element_not_peak(self):
        """Last element cannot be a peak even if it is the largest."""
        result = find_local_peaks([2, 5, 10])
        assert 2 not in result

    def test_empty(self):
        assert find_local_peaks([]) == []

    def test_two_elements(self):
        assert find_local_peaks([1, 2]) == []

    def test_three_elements_middle_peak(self):
        assert find_local_peaks([1, 9, 1]) == [1]

    def test_valley_not_peak(self):
        assert find_local_peaks([5, 1, 5]) == []


class TestMovingAverage:

    def test_basic(self):
        result = compute_moving_average([1, 2, 3, 4, 5], 3)
        assert result == [2.0, 3.0, 4.0]

    def test_window_equals_length(self):
        result = compute_moving_average([1, 2, 3], 3)
        assert result == [2.0]

    def test_window_one(self):
        result = compute_moving_average([1, 2, 3], 1)
        assert result == [1.0, 2.0, 3.0]

    def test_empty(self):
        assert compute_moving_average([], 3) == []

    def test_window_larger_than_data(self):
        assert compute_moving_average([1, 2], 5) == []


class TestMaxChange:

    def test_basic(self):
        assert max_change([1, 4, 2, 9]) == 7

    def test_single_element(self):
        assert max_change([5]) == 0

    def test_empty(self):
        assert max_change([]) == 0

    def test_decreasing(self):
        assert max_change([10, 5, 3]) == 5
