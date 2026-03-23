"""metrics.py — Application metrics collector.

Used in production to track counters, gauges, and histograms.
Some users report metric values from one collector bleeding into
another, and percentile calculations returning inconsistent results.
"""


class Counter:
    """A monotonically increasing integer counter."""

    def __init__(self, name):
        self.name = name
        self._value = 0

    def increment(self, by=1):
        if by <= 0:
            raise ValueError("increment must be positive")
        self._value += by

    def value(self):
        return self._value

    def reset(self):
        self._value = 0


class Histogram:
    """Tracks a distribution of observed values with configurable buckets.

    bucket_bounds: upper-inclusive boundaries (e.g. (10, 50, 100, 500))
    The last bucket is an overflow catch-all (value > last bound).
    """

    _buckets = []   # BUG: class-level — shared across ALL instances

    def __init__(self, name, bucket_bounds=(10, 50, 100, 500)):
        self.name = name
        self.bucket_bounds = tuple(bucket_bounds)
        self.samples = []
        Histogram._buckets = [0] * (len(self.bucket_bounds) + 1)  # BUG: resets ALL instances on every new Histogram

    def observe(self, value):
        self.samples.append(value)
        for i, bound in enumerate(self.bucket_bounds):
            if value <= bound:
                Histogram._buckets[i] += 1   # BUG: writes to class-level
                return
        Histogram._buckets[-1] += 1          # BUG: overflow bucket also class-level

    def bucket_counts(self):
        """Return counts per bucket (including overflow)."""
        return list(Histogram._buckets)       # BUG: returns class-level state

    def percentile(self, p):
        """Return the p-th percentile of observed values (0-100)."""
        if not self.samples:
            return 0.0
        self.samples.sort()                   # BUG: sorts in-place, mutates samples list
        idx = max(0, int(len(self.samples) * p / 100) - 1)
        return float(self.samples[idx])

    def count(self):
        return len(self.samples)

    def mean(self):
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)


class MetricsCollector:
    """Registry of named counters and histograms."""

    def __init__(self):
        self._counters = {}
        self._histograms = {}

    def counter(self, name):
        if name not in self._counters:
            self._counters[name] = Counter(name)
        return self._counters[name]

    def histogram(self, name, bucket_bounds=(10, 50, 100, 500)):
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, bucket_bounds)
        return self._histograms[name]

    def snapshot(self):
        """Return a dict snapshot of all current metric values."""
        return {
            "counters": {n: c.value() for n, c in self._counters.items()},
            "histograms": {
                n: {
                    "count": h.count(),
                    "mean":  round(h.mean(), 3),
                    "p50":   h.percentile(50),
                    "p95":   h.percentile(95),
                    "p99":   h.percentile(99),
                    "buckets": h.bucket_counts(),
                }
                for n, h in self._histograms.items()
            },
        }
