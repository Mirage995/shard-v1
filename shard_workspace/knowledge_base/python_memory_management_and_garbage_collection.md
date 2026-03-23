# python memory management and garbage collection — SHARD Cheat Sheet

## Key Concepts
- **Reference Counting**: Python uses reference counting to manage memory. Each object has a count of references pointing to it; when this count reaches zero, the object is deallocated.
- **Garbage Collection**: Handles circular references where objects reference each other, preventing them from being deallocated by reference counting alone.
- **Circular References**: Complex data structures involving custom classes that reference each other can lead to memory leaks if not managed properly.
- **Weak Reference**: Allows for creating references that do not increase the object's reference count, useful in breaking cycles without preventing garbage collection.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient memory management through reference counting. | Limited handling of circular references can lead to memory leaks. |
| Automatic deallocation of objects when no longer needed. | Complexity arises with managing circular references, which can be difficult to detect and resolve. |
| Simple implementation and performance benefits for most use cases. | Potential overhead in garbage collection process for complex applications. |

## Practical Example
```python
import gc

class A:
    def __init__(self):
        self.b = B(self)
        print("A created")

    def __del__(self):
        print("A destroyed")

class B:
    def __init__(self, a):
        self.a = a
        print("B created")

    def __del__(self):
        print("B destroyed")

# Create instances of A and B
a = A()

# Break the circular reference manually
a.b.a = None

# Force garbage collection
gc.collect()
```

## SHARD's Take
Python's memory management through reference counting is efficient for most use cases, but handling circular references requires careful consideration. Weak references provide a useful tool to break cycles without preventing garbage collection, making them essential in complex data structures.