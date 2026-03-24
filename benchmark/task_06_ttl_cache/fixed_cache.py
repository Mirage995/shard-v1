import time


class TTLCache:
    """Key-value store where entries expire after a configurable TTL."""

    def __init__(self, ttl_seconds=60):
        self._store = {}   # key -> (value, expires_at)
        self.ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def set(self, key, value):
        """Insert or overwrite a key with a fresh TTL."""
        self._store[key] = (value, time.time() + self.ttl)

    def get(self, key):
        """Return the value for key, or None if missing or expired."""
        if key not in self._store:
            self._misses += 1
            return None
        value, expires_at = self._store[key]
        if time.time() > expires_at:
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        return value

    def delete(self, key):
        """Remove a key (no-op if not present)."""
        self._store.pop(key, None)

    def clear(self):
        """Remove all entries."""
        self._store.clear()
        self._hits = 0
        self._misses = 0

    @property
    def size(self):
        """Number of *live* entries currently in the cache."""
        now = time.time()
        return sum(1 for _, expires_at in self._store.values() if now <= expires_at)

    @property
    def stats(self):
        return {"hits": self._hits, "misses": self._misses, "size": self.size}

    def evict_expired(self):
        """Manually evict all expired entries (useful for periodic cleanup)."""
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        return len(expired)