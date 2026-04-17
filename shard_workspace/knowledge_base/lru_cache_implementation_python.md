# lru cache implementation python -- SHARD Cheat Sheet

## Key Concepts
* LRU (Least Recently Used) cache: a cache replacement policy that discards the least recently used items first
* Cache replacement policies: strategies for deciding which items to remove from a cache when it reaches its capacity
* Cache hit: when the requested item is found in the cache
* Cache miss: when the requested item is not found in the cache
* Time complexity: the time it takes for an algorithm to complete, often measured in Big O notation

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves system performance by reducing the number of cache misses | Can be complex to implement, especially in multi-threaded environments |
| Reduces the amount of memory needed to store cache items | May not be suitable for all types of data, such as data with a high rate of insertion and deletion |
| Easy to understand and implement for simple use cases | Can be difficult to optimize for large datasets |

## Practical Example
```python
from collections import OrderedDict

class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = OrderedDict()

    def get(self, key):
        if key in self.cache:
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        else:
            return -1

    def put(self, key, value):
        if key in self.cache:
            self.cache.pop(key)
        elif len(self.cache) >= self.capacity:
            self.cache.popitem(last=False)
        self.cache[key] = value

# Example usage:
cache = LRUCache(2)
cache.put(1, 1)
cache.put(2, 2)
print(cache.get(1))  # returns 1
cache.put(3, 3)
print(cache.get(2))  # returns -1
```

## SHARD's Take
The implementation of LRU cache in Python can be achieved using an OrderedDict, which provides an efficient way to store and retrieve items in the order they were last accessed. By using this data structure, developers can create a simple and effective LRU cache that improves system performance by reducing cache misses. However, optimizing the cache for large datasets and multi-threaded environments can be challenging and requires careful consideration of the trade-offs between complexity and performance.