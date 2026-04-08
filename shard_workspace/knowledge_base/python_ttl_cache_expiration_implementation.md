# Python TTL cache expiration implementation -- SHARD Cheat Sheet

## Key Concepts
* TTL Cache: a key-value store where entries expire after a configurable time-to-live
* Cache Decorator: a design pattern that implements caching for functions or methods
* Time-to-Live (TTL): a mechanism for expiring cache entries after a specified time period
* Cache Expiration: the process of removing outdated or invalid cache entries
* Cache Invalidation: the process of removing cache entries that are no longer valid

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves performance by reducing repeated computations | Increases complexity by introducing cache management |
| Optimizes data freshness by expiring outdated cache entries | Requires careful tuning of TTL values to balance performance and data freshness |
| Enhances scalability by reducing load on underlying systems | May introduce additional latency due to cache misses |

## Practical Example
```python
import time
from functools import wraps

class TTLCache:
    def __init__(self, ttl_seconds=60):
        self._store = {}
        self._ttl_seconds = ttl_seconds

    def get(self, key):
        if key in self._store:
            value, expires = self._store[key]
            if time.time() < expires:
                return value
            else:
                del self._store[key]
        return None

    def set(self, key, value):
        expires = time.time() + self._ttl_seconds
        self._store[key] = (value, expires)

def cache(ttl_seconds=60):
    cache_instance = TTLCache(ttl_seconds)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = str(args) + str(kwargs)
            cached_value = cache_instance.get(key)
            if cached_value is not None:
                return cached_value
            else:
                value = func(*args, **kwargs)
                cache_instance.set(key, value)
                return value
        return wrapper
    return decorator

@cache(ttl_seconds=30)
def expensive_computation(x):
    # simulate an expensive computation
    time.sleep(2)
    return x * x

print(expensive_computation(2))  # computes and caches the result
print(expensive_computation(2))  # returns the cached result
```

## SHARD's Take
The implementation of a TTL cache in Python is crucial for optimizing performance in data-intensive applications. A well-designed cache decorator with a time-to-live feature can help balance cache expiration and data freshness. By using a TTL cache, developers can improve the performance and scalability of their applications while ensuring that cache entries remain up-to-date and relevant.