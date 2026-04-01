"""pipeline.py — Configurable data processing pipeline.

Transforms numeric values with a configurable multiplier,
tracks processing history, and assigns sequential IDs.
"""

import copy


class Pipeline:
    """Processes batches of numeric data with caching and history."""

    def __init__(self, multiplier=1.0):
        self._multiplier = float(multiplier)
        self._cache = {}
        self._id_seq = iter(range(100000))
        self._history = []
        self._processed_count = 0

    def set_multiplier(self, m):
        """Change the multiplier for future operations."""
        self._multiplier = float(m)
        self._cache = {}

    def process(self, values):
        """Transform values by the current multiplier. Returns list of results.

        Results are cached per input value for performance.
        """
        results = []
        for v in values:
            if v not in self._cache:
                self._cache[v] = v * self._multiplier
            results.append(self._cache[v])
        self._processed_count += len(values)
        self._history.append(copy.deepcopy(values))
        return results

    def next_id(self):
        """Return the next sequential ID (0, 1, 2, ...)."""
        return next(self._id_seq)

    def get_history(self):
        """Return list of all processed batches."""
        return list(self._history)

    def get_processed_count(self):
        """Return total number of individual values processed."""
        return self._processed_count

    def reset(self):
        """Reset pipeline to initial state. Clears all history and counters."""
        self._history = []
        self._processed_count = 0
        self._cache = {}
        self._id_seq = iter(range(100000))