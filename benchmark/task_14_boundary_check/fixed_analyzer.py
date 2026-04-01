"""Sequence analyzer — computes statistics on numerical time series.

Functions:
    compute_changes(series)     -- change between consecutive pairs
    find_local_peaks(data)      -- indices of local maxima
    compute_moving_average(data, window) -- sliding window average
"""


def compute_changes(series):
    """Return list of differences between consecutive elements.

    Example: [1, 3, 6, 10] -> [2, 3, 4]
    """
    changes = []
    for i in range(len(series) - 1):
        changes.append(series[i + 1] - series[i])
    return changes


def find_local_peaks(data):
    """Return indices of local maxima.

    A local maximum is an element strictly greater than both its neighbors.
    First and last elements are never peaks (no left/right neighbor).

    Example: [1, 5, 2, 8, 3] -> [1, 3]
    """
    peaks = []
    for i in range(1, len(data) - 1):
        if data[i] > data[i - 1] and data[i] > data[i + 1]:
            peaks.append(i)
    return peaks


def compute_moving_average(data, window):
    """Return moving averages using a sliding window.

    Only returns averages for complete windows.
    Example: [1, 2, 3, 4, 5], window=3 -> [2.0, 3.0, 4.0]
    """
    if not data or window <= 0 or window > len(data):
        return []
    result = []
    for i in range(len(data) - window + 1):
        avg = sum(data[i:i + window]) / window
        result.append(round(avg, 6))
    return result


def max_change(series):
    """Return the largest absolute change between consecutive elements.

    Returns 0 for series with fewer than 2 elements.
    """
    if len(series) < 2:
        return 0
    changes = compute_changes(series)
    return max(abs(c) for c in changes)