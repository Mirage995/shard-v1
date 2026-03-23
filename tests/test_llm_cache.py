"""Tests for llm_cache.py — in-memory LRU cache with TTL and bypass logic."""
import sys
import os
import time
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Mock shard_db before import (cache runs _ensure_table on import)
_mock_shard_db = MagicMock()
_mock_shard_db.query.return_value = []  # _load_from_db returns empty
sys.modules["shard_db"] = _mock_shard_db

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import llm_cache
from llm_cache import (
    _make_key, _get, _put, get_cache_stats, invalidate_all,
    _cache, _TTL_SECONDS, _MAX_ENTRIES,
)


def _reset_cache():
    """Clear module-level cache state between tests."""
    llm_cache._cache.clear()
    llm_cache._hits = 0
    llm_cache._misses = 0


class TestMakeKey(unittest.TestCase):
    """_make_key — deterministic MD5 hash."""

    def test_same_inputs_same_key(self):
        k1 = _make_key("hello", "sys", ["Gemini"])
        k2 = _make_key("hello", "sys", ["Gemini"])
        self.assertEqual(k1, k2)

    def test_different_prompt_different_key(self):
        k1 = _make_key("prompt A", "sys", ["Gemini"])
        k2 = _make_key("prompt B", "sys", ["Gemini"])
        self.assertNotEqual(k1, k2)

    def test_different_providers_different_key(self):
        k1 = _make_key("prompt", "sys", ["Gemini"])
        k2 = _make_key("prompt", "sys", ["Groq"])
        self.assertNotEqual(k1, k2)

    def test_returns_hex_string(self):
        key = _make_key("test", "", [])
        self.assertRegex(key, r"^[0-9a-f]{32}$")

    def test_prompt_truncated_at_key_len(self):
        """Two prompts that differ only beyond _PROMPT_KEY_LEN should produce same key."""
        from llm_cache import _PROMPT_KEY_LEN
        base = "x" * _PROMPT_KEY_LEN
        k1 = _make_key(base + "AAA", "sys", ["G"])
        k2 = _make_key(base + "BBB", "sys", ["G"])
        self.assertEqual(k1, k2)


class TestGetPut(unittest.TestCase):
    """_get / _put — in-memory LRU + TTL logic."""

    def setUp(self):
        _reset_cache()

    def test_miss_on_empty_cache(self):
        result = _get("nonexistent_key")
        self.assertIsNone(result)
        self.assertEqual(llm_cache._misses, 1)

    def test_put_then_get_returns_value(self):
        _put("k1", "response text")
        result = _get("k1")
        self.assertEqual(result, "response text")
        self.assertEqual(llm_cache._hits, 1)

    def test_expired_entry_returns_none(self):
        key = "expired_key"
        # Manually insert an already-expired entry
        llm_cache._cache[key] = (time.time() - 1, "stale response")
        result = _get(key)
        self.assertIsNone(result)
        self.assertNotIn(key, llm_cache._cache)

    def test_lru_eviction_when_full(self):
        # Fill cache to MAX_ENTRIES + 1 to trigger eviction
        for i in range(_MAX_ENTRIES + 1):
            _put(f"key_{i}", f"val_{i}")
        self.assertLessEqual(len(llm_cache._cache), _MAX_ENTRIES)

    def test_hit_moves_to_end(self):
        """LRU: accessing a key should move it to most-recently-used position."""
        _put("first", "v1")
        _put("second", "v2")
        _get("first")  # access first again
        keys = list(llm_cache._cache.keys())
        self.assertEqual(keys[-1], "first")  # most recently used is last

    def test_put_updates_existing_key(self):
        _put("k", "old")
        _put("k", "new")
        result = _get("k")
        self.assertEqual(result, "new")

    def test_stats_track_hits_and_misses(self):
        _put("x", "val")
        _get("x")   # hit
        _get("y")   # miss
        _get("x")   # hit
        stats = get_cache_stats()
        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 1)

    def test_stats_hit_rate(self):
        _put("a", "v")
        _get("a")  # hit
        _get("b")  # miss
        stats = get_cache_stats()
        self.assertAlmostEqual(stats["hit_rate"], 0.5)

    def test_invalidate_all_clears_cache(self):
        _put("a", "v1")
        _put("b", "v2")
        invalidate_all()
        self.assertEqual(len(llm_cache._cache), 0)

    def test_entries_in_memory_count(self):
        _put("p", "q")
        _put("r", "s")
        stats = get_cache_stats()
        self.assertEqual(stats["entries_in_memory"], 2)

    def test_ttl_seconds_in_stats(self):
        stats = get_cache_stats()
        self.assertEqual(stats["ttl_seconds"], _TTL_SECONDS)


class TestCachedLlmComplete(unittest.IsolatedAsyncioTestCase):
    """cached_llm_complete — bypass conditions and cache flow."""

    def setUp(self):
        _reset_cache()

    async def test_bypasses_cache_when_skip_cache_true(self):
        """skip_cache=True always calls real LLM and does not populate cache."""
        mock_complete = AsyncMock(return_value="fresh")
        with patch.dict(sys.modules, {"llm_router": MagicMock(llm_complete=mock_complete)}):
            from llm_cache import cached_llm_complete
            long_prompt = "x" * 100
            await cached_llm_complete(long_prompt, skip_cache=True, temperature=0.1)
            await cached_llm_complete(long_prompt, skip_cache=True, temperature=0.1)
            # Called twice — cache not used
            self.assertEqual(mock_complete.call_count, 2)

    async def test_bypasses_cache_for_short_prompt(self):
        """Prompts < 50 chars bypass caching."""
        from unittest.mock import AsyncMock, patch as _patch
        mock_complete = AsyncMock(return_value="result")
        with _patch.dict(sys.modules, {"llm_router": MagicMock(llm_complete=mock_complete)}):
            from llm_cache import cached_llm_complete
            await cached_llm_complete("short", skip_cache=False, temperature=0.1)
            # Short prompt (< 50 chars) → bypass → llm_complete called
            mock_complete.assert_called_once()

    async def test_bypasses_cache_for_high_temperature(self):
        """temperature > 0.3 bypasses caching."""
        mock_complete = AsyncMock(return_value="creative")
        with patch.dict(sys.modules, {"llm_router": MagicMock(llm_complete=mock_complete)}):
            from importlib import reload
            from llm_cache import cached_llm_complete
            long_prompt = "x" * 100
            await cached_llm_complete(long_prompt, temperature=0.5)
            mock_complete.assert_called_once()

    async def test_caches_on_second_call(self):
        """Same prompt twice → second call uses cache, llm_complete called once."""
        mock_complete = AsyncMock(return_value="cached response")
        with patch.dict(sys.modules, {"llm_router": MagicMock(llm_complete=mock_complete)}):
            from llm_cache import cached_llm_complete
            long_prompt = "a" * 100
            r1 = await cached_llm_complete(long_prompt, temperature=0.1)
            r2 = await cached_llm_complete(long_prompt, temperature=0.1)
            self.assertEqual(r1, r2)
            mock_complete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
