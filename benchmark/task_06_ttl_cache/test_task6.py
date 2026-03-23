"""test_task6.py — Benchmark tests for Task 06: TTL Cache.

SHARD must produce fixed_cache.py that passes all tests.
"""
import time
import pytest

try:
    from fixed_cache import TTLCache
except ImportError:
    pytest.exit("fixed_cache.py not found — SHARD has not produced a solution yet.", returncode=2)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_cache(ttl=60):
    return TTLCache(ttl_seconds=ttl)


# ── Basic functionality ────────────────────────────────────────────────────────

def test_set_and_get():
    c = make_cache()
    c.set("a", 42)
    assert c.get("a") == 42


def test_get_missing_returns_none():
    c = make_cache()
    assert c.get("nope") is None


def test_overwrite():
    c = make_cache()
    c.set("k", 1)
    c.set("k", 2)
    assert c.get("k") == 2


def test_delete():
    c = make_cache()
    c.set("x", 99)
    c.delete("x")
    assert c.get("x") is None


def test_delete_nonexistent_is_noop():
    c = make_cache()
    c.delete("ghost")  # must not raise


def test_clear():
    c = make_cache()
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert c.get("a") is None
    assert c.get("b") is None


# ── TTL / expiry — the core bug ───────────────────────────────────────────────

def test_expired_entry_returns_none():
    """get() on an expired entry must return None, not the stale value."""
    c = TTLCache(ttl_seconds=0.05)
    c.set("stale", "old_value")
    time.sleep(0.1)
    result = c.get("stale")
    assert result is None, (
        f"Expected None for expired key, got {result!r}. "
        "Hint: the buggy code returns the stale value before deleting it."
    )


def test_expired_entry_counted_as_miss():
    """A get() on an expired key must increment misses, not hits."""
    c = TTLCache(ttl_seconds=0.05)
    c.set("k", "v")
    time.sleep(0.1)
    c.get("k")
    assert c.stats["misses"] == 1
    assert c.stats["hits"] == 0


def test_non_expired_entry_still_accessible():
    c = TTLCache(ttl_seconds=10)
    c.set("fresh", "data")
    assert c.get("fresh") == "data"


def test_multiple_keys_independent_ttl():
    """Expiry of one key must not affect others."""
    c = TTLCache(ttl_seconds=0.05)
    c.set("fast", "gone")
    c2 = TTLCache(ttl_seconds=60)
    c2.set("slow", "here")
    time.sleep(0.1)
    assert c.get("fast") is None
    assert c2.get("slow") == "here"


# ── Size — the second bug ─────────────────────────────────────────────────────

def test_size_excludes_expired_entries():
    """size must count only live (non-expired) entries."""
    c = TTLCache(ttl_seconds=0.05)
    c.set("a", 1)
    c.set("b", 2)
    time.sleep(0.1)
    # Both entries are now expired; size must be 0
    sz = c.size
    assert sz == 0, (
        f"Expected size=0 after all entries expired, got {sz}. "
        "Hint: size() must filter out expired entries."
    )


def test_size_live_only():
    c = TTLCache(ttl_seconds=60)
    assert c.size == 0
    c.set("x", 1)
    assert c.size == 1
    c.set("y", 2)
    assert c.size == 2
    c.delete("x")
    assert c.size == 1


def test_size_after_clear():
    c = make_cache()
    c.set("a", 1)
    c.clear()
    assert c.size == 0


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_hits_misses():
    c = make_cache()
    c.set("k", "v")
    c.get("k")   # hit
    c.get("k")   # hit
    c.get("z")   # miss
    s = c.stats
    assert s["hits"] == 2
    assert s["misses"] == 1


def test_stats_reset_on_clear():
    c = make_cache()
    c.set("k", "v")
    c.get("k")
    c.get("missing")
    c.clear()
    s = c.stats
    assert s["hits"] == 0
    assert s["misses"] == 0


# ── evict_expired ─────────────────────────────────────────────────────────────

def test_evict_expired_removes_stale():
    c = TTLCache(ttl_seconds=0.05)
    c.set("a", 1)
    c.set("b", 2)
    time.sleep(0.1)
    evicted = c.evict_expired()
    assert evicted == 2
    assert c.size == 0


def test_evict_expired_leaves_live_entries():
    c = TTLCache(ttl_seconds=60)
    c.set("live", 1)
    evicted = c.evict_expired()
    assert evicted == 0
    assert c.size == 1
