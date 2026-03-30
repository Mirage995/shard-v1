"""llm_cache.py -- LLM response cache (in-memory + SQLite persistence).

Avoids duplicate LLM calls for identical or near-identical prompts.
Useful when night_runner re-studies similar topics or swarm reviewers
get the same boilerplate code in back-to-back sessions.

Cache strategy:
  - Key: MD5(prompt[:2000] + system[:200] + providers_str)
  - TTL: 2 hours (prompts about code/study expire quickly -- content changes)
  - Max entries: 500 (LRU eviction when full)
  - Persistence: SQLite table llm_cache in shard.db (survives restart)

Usage:
    from llm_cache import cached_llm_complete
    result = await cached_llm_complete(prompt, system, ...)
"""
import hashlib
import logging
import time
from collections import OrderedDict

logger = logging.getLogger("shard.llm_cache")

# ── Config ────────────────────────────────────────────────────────────────────

_TTL_SECONDS = 7200      # 2 hours
_MAX_ENTRIES = 500       # in-memory LRU limit
_PROMPT_KEY_LEN = 2000   # chars used for cache key (truncated)
_SYSTEM_KEY_LEN = 200

# ── In-memory LRU cache ───────────────────────────────────────────────────────

_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()  # key -> (expires_at, response)
_hits = 0
_misses = 0


def _make_key(prompt: str, system: str, providers: list[str]) -> str:
    raw = f"{prompt[:_PROMPT_KEY_LEN]}|{system[:_SYSTEM_KEY_LEN]}|{','.join(providers)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _get(key: str) -> str | None:
    global _hits, _misses
    entry = _cache.get(key)
    if entry:
        expires_at, response = entry
        if time.time() < expires_at:
            _cache.move_to_end(key)  # LRU: mark as recently used
            _hits += 1
            return response
        else:
            del _cache[key]  # expired
    _misses += 1
    return None


def _put(key: str, response: str):
    if key in _cache:
        _cache.move_to_end(key)
    _cache[key] = (time.time() + _TTL_SECONDS, response)

    # LRU eviction
    while len(_cache) > _MAX_ENTRIES:
        evicted_key, _ = _cache.popitem(last=False)
        logger.debug("[LLM_CACHE] Evicted key %s", evicted_key[:8])

    # Persist to SQLite (non-fatal)
    _persist(key, response)


# ── SQLite persistence ────────────────────────────────────────────────────────

def _ensure_table():
    try:
        from shard_db import execute
        execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                key        TEXT PRIMARY KEY,
                response   TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
    except Exception as e:
        logger.debug("[LLM_CACHE] Table init failed: %s", e)


def _persist(key: str, response: str):
    try:
        from shard_db import execute
        now = time.time()
        execute("""
            INSERT OR REPLACE INTO llm_cache (key, response, created_at, expires_at)
            VALUES (?, ?, ?, ?)
        """, (key, response, now, now + _TTL_SECONDS))
    except Exception:
        pass  # cache persistence is never critical


def _load_from_db():
    """Load non-expired entries from SQLite into memory at startup."""
    try:
        from shard_db import query
        now = time.time()
        rows = query(
            "SELECT key, response, expires_at FROM llm_cache WHERE expires_at > ? LIMIT ?",
            (now, _MAX_ENTRIES),
        )
        loaded = 0
        for row in rows:
            _cache[row["key"]] = (row["expires_at"], row["response"])
            loaded += 1
        if loaded:
            logger.info("[LLM_CACHE] Loaded %d entries from SQLite", loaded)
    except Exception as e:
        logger.debug("[LLM_CACHE] DB load failed: %s", e)


def _purge_expired_db():
    """Clean up expired entries from SQLite (run at startup)."""
    try:
        from shard_db import execute
        execute("DELETE FROM llm_cache WHERE expires_at <= ?", (time.time(),))
    except Exception:
        pass


# ── Public API ─────────────────────────────────────────────────────────────────

async def cached_llm_complete(
    prompt: str,
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.1,
    providers: list[str] = None,
    skip_cache: bool = False,
) -> str:
    """Drop-in replacement for llm_complete() with caching.

    Cache is bypassed when:
    - skip_cache=True (force fresh call)
    - temperature > 0.3 (creative/varied responses shouldn't be cached)
    - prompt is very short (<50 chars -- probably a one-off)
    """
    from llm_router import llm_complete

    providers = providers or ["Gemini", "Groq", "Claude"]

    # Bypass conditions
    if skip_cache or temperature > 0.3 or len(prompt) < 50:
        return await llm_complete(prompt, system, max_tokens, temperature, providers)

    key = _make_key(prompt, system, providers)
    cached = _get(key)
    if cached is not None:
        logger.debug("[LLM_CACHE] HIT key=%s", key[:8])
        return cached

    # Cache miss -- call real LLM
    response = await llm_complete(prompt, system, max_tokens, temperature, providers)
    _put(key, response)
    return response


def get_cache_stats() -> dict:
    """Stats for /health endpoint."""
    total = _hits + _misses
    return {
        "entries_in_memory": len(_cache),
        "hits": _hits,
        "misses": _misses,
        "hit_rate": round(_hits / total, 3) if total > 0 else 0.0,
        "ttl_seconds": _TTL_SECONDS,
        "max_entries": _MAX_ENTRIES,
    }


def invalidate_all():
    """Clear all cache entries (useful after major code changes)."""
    _cache.clear()
    try:
        from shard_db import execute
        execute("DELETE FROM llm_cache")
    except Exception:
        pass
    logger.info("[LLM_CACHE] All entries invalidated")


# ── Init on import ────────────────────────────────────────────────────────────
try:
    _ensure_table()
    _purge_expired_db()
    _load_from_db()
except Exception:
    pass
