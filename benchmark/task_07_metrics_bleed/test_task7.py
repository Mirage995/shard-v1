"""test_task7.py — Benchmark tests for Task 07: Metrics Bleed.

SHARD must produce fixed_metrics.py that passes all tests.
"""
import pytest

try:
    from fixed_metrics import Counter, Histogram, MetricsCollector
except ImportError:
    pytest.exit("fixed_metrics.py not found — SHARD has not produced a solution yet.", returncode=2)


# ── Counter ────────────────────────────────────────────────────────────────────

def test_counter_basic():
    c = Counter("requests")
    assert c.value() == 0
    c.increment()
    assert c.value() == 1
    c.increment(by=5)
    assert c.value() == 6


def test_counter_reset():
    c = Counter("c")
    c.increment(10)
    c.reset()
    assert c.value() == 0


def test_counter_invalid_increment():
    c = Counter("c")
    with pytest.raises(ValueError):
        c.increment(0)
    with pytest.raises(ValueError):
        c.increment(-1)


def test_counters_are_independent():
    c1 = Counter("a")
    c2 = Counter("b")
    c1.increment(5)
    assert c2.value() == 0, "Counters must not share state"


# ── Histogram — bucket isolation (the main bug) ────────────────────────────────

def test_histograms_do_not_share_buckets():
    """Creating two Histograms must not bleed counts between them."""
    h1 = Histogram("latency")
    h1.observe(5)    # bucket 0 (≤10)
    h1.observe(30)   # bucket 1 (≤50)

    h2 = Histogram("size")
    h2.observe(200)  # bucket 2 (≤100? no — bucket 3 ≤500)

    b1 = h1.bucket_counts()
    b2 = h2.bucket_counts()

    assert b1[0] == 1, f"h1 bucket[0] should be 1, got {b1[0]}"
    assert b1[1] == 1, f"h1 bucket[1] should be 1, got {b1[1]}"
    assert b2[2] == 0, f"h2 bucket[2] should be 0, got {b2[2]}"  # no value ≤100
    assert b2[3] == 1, f"h2 bucket[3] should be 1, got {b2[3]}"  # 200 ≤500


def test_new_histogram_does_not_reset_existing():
    """Creating a new Histogram must not wipe counts from existing ones."""
    h1 = Histogram("a")
    h1.observe(5)    # goes into bucket 0

    Histogram("b")   # creating this must NOT zero out h1's buckets

    assert h1.bucket_counts()[0] == 1, (
        "Creating a second Histogram reset h1's bucket counts. "
        "Hint: buckets must be instance-level, not class-level."
    )


def test_bucket_counts_correct():
    h = Histogram("h", bucket_bounds=(10, 50, 100))
    h.observe(5)    # ≤10
    h.observe(10)   # ≤10
    h.observe(11)   # ≤50
    h.observe(200)  # overflow
    counts = h.bucket_counts()
    assert counts[0] == 2   # ≤10
    assert counts[1] == 1   # ≤50
    assert counts[2] == 0   # ≤100
    assert counts[3] == 1   # overflow


# ── Histogram — percentile (the in-place sort bug) ────────────────────────────

def test_percentile_does_not_mutate_samples():
    """percentile() must not sort the internal samples list in-place."""
    h = Histogram("h")
    values = [30, 10, 50, 20, 40]
    for v in values:
        h.observe(v)

    original_order = list(h.samples)
    h.percentile(50)
    assert h.samples == original_order, (
        f"percentile() mutated samples. Before: {original_order}, After: {h.samples}. "
        "Hint: sort a copy, not the original list."
    )


def test_percentile_values():
    h = Histogram("h")
    for v in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]:
        h.observe(v)
    assert h.percentile(50) == 5
    assert h.percentile(90) == 9
    assert h.percentile(100) == 10


def test_percentile_empty():
    h = Histogram("h")
    assert h.percentile(50) == 0.0


def test_percentile_stable_across_calls():
    """Multiple percentile calls must return the same result."""
    h = Histogram("h")
    for v in [100, 1, 50, 10, 90]:
        h.observe(v)
    p1 = h.percentile(50)
    p2 = h.percentile(50)
    assert p1 == p2, "percentile() is not stable across calls"


def test_count_and_mean():
    h = Histogram("h")
    h.observe(10)
    h.observe(20)
    h.observe(30)
    assert h.count() == 3
    assert abs(h.mean() - 20.0) < 0.001


# ── MetricsCollector ──────────────────────────────────────────────────────────

def test_collector_counter():
    m = MetricsCollector()
    m.counter("req").increment(3)
    assert m.counter("req").value() == 3


def test_collector_histogram():
    m = MetricsCollector()
    m.histogram("lat").observe(42)
    assert m.histogram("lat").count() == 1


def test_collector_snapshot():
    m = MetricsCollector()
    m.counter("c").increment(5)
    m.histogram("h").observe(10)
    m.histogram("h").observe(20)
    snap = m.snapshot()
    assert snap["counters"]["c"] == 5
    assert snap["histograms"]["h"]["count"] == 2
    assert snap["histograms"]["h"]["mean"] == 15.0


def test_two_collectors_isolated():
    """Two MetricsCollector instances must not share histogram state."""
    m1 = MetricsCollector()
    m2 = MetricsCollector()

    m1.histogram("latency").observe(5)
    m1.histogram("latency").observe(5)

    m2.histogram("latency").observe(500)

    assert m1.histogram("latency").count() == 2
    assert m1.histogram("latency").bucket_counts()[0] == 2  # both in ≤10 bucket
    assert m2.histogram("latency").count() == 1
    assert m2.histogram("latency").bucket_counts()[0] == 0  # 500 not in ≤10
