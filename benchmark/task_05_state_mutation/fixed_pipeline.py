"""pipeline.py — Configurable data processing pipeline.

Transforms numeric values with a configurable multiplier,
tracks processing history, and assigns sequential IDs.
"""

import threading
import copy


class Pipeline:
    """Processes batches of numeric data with caching and history."""

    def __init__(self, multiplier=1.0):
        self._multiplier = float(multiplier)
        self._cache = {}
        self._id_seq = iter(range(100000))
        self._history = []
        self._processed_count = 0
        self._lock = threading.RLock()
        self._initialized = True

    def set_multiplier(self, m):
        """Change the multiplier for future operations."""
        with self._lock:
            self._multiplier = float(m)
            self._cache = {}

    def process(self, values):
        """Transform values by the current multiplier. Returns list of results.

        Results are cached per input value for performance.
        """
        with self._lock:
            results = []
            for v in values:
                if v not in self._cache:
                    self._cache[v] = v * self._multiplier
                results.append(self._cache[v])
            self._processed_count += len(values)
            self._history.append(copy.copy(values))
            return results

    def next_id(self):
        """Return the next sequential ID (0, 1, 2, ...)."""
        with self._lock:
            return next(self._id_seq)

    def get_history(self):
        """Return list of all processed batches."""
        with self._lock:
            return list(self._history)

    def get_processed_count(self):
        """Return total number of individual values processed."""
        with self._lock:
            return self._processed_count

    def reset(self):
        """Reset pipeline to initial state. Clears all history and counters."""
        with self._lock:
            self._history = []
            self._processed_count = 0
            self._cache = {}
            self._id_seq = iter(range(100000))