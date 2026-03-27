```markdown
# caching strategies lru cache — SHARD Cheat Sheet

## Key Concepts
*   **Cache:** A high-speed data storage layer that stores a subset of data to serve future requests faster.
*   **LRU (Least Recently Used):** A cache eviction policy that removes the least recently accessed items first.
*   **Cache Hit:** When the requested data is found in the cache.
*   **Cache Miss:** When the requested data is not found in the cache, requiring retrieval from the original source.
*   **Cache Capacity:** The maximum number of items the cache can hold.
*   **Time Complexity:** Typically O(1) for both get and put operations, assuming a good hash function and doubly linked list implementation.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Simple to implement | Can be inefficient if access patterns are not truly "least recently used" |
| Fast access times (O(1)) | Doesn't account for frequency of access (unlike LFU) |
| Effective for many common use cases | Can be susceptible to "cache pollution" if a large number of unique items are accessed briefly |

## Practical Example
```python
from collections import OrderedDict

class LRUCache:

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = OrderedDict()

    def get(self, key: int) -> int:
        if key not in self.cache:
            return -1
        else:
            self.cache.move_to_end(key)  # Move to end (most recently used)
            return self.cache[key]

    def put(self, key: int, value: int) -> None:
        if key in self.cache:
            self.cache[key] = value
            self.cache.move_to_end(key)
        else:
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False) # Remove the least recently used item

# Example Usage
cache = LRUCache(2)
cache.put(1, 1)
cache.put(2, 2)
print(cache.get(1))       # returns 1
cache.put(3, 3)    # evicts key 2
print(cache.get(2))       # returns -1 (not found)
cache.put(4, 4)    # evicts key 1
print(cache.get(1))       # returns -1 (not found)
print(cache.get(3))       # returns 3
print(cache.get(4))       # returns 4
```

## SHARD's Take
LRU cache is a valuable tool for improving performance by storing frequently accessed data. Its simplicity and generally good performance make it a popular choice, but it's essential to consider its limitations and whether it aligns with the specific access patterns of the data being cached. Alternative caching strategies like LFU might be more suitable in certain scenarios.
```