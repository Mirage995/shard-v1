# immutable data structures python -- SHARD Cheat Sheet

## Key Concepts
* namedtuple: a factory function for creating tuple subclasses with named fields
* tuple: an immutable collection of objects that can be used as dictionary keys
* frozenset: an immutable set of unique elements that can be used as dictionary keys
* immutable data structures: data structures that cannot be modified once created, ensuring data integrity and preventing data corruption

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Prevents data corruption | Can be challenging to implement with complex data relationships |
| Ensures data integrity | May require additional memory to store immutable copies of data |
| Improves code readability | Can be less efficient than mutable data structures in certain scenarios |

## Practical Example
```python
from collections import namedtuple

# Create a namedtuple class
Person = namedtuple('Person', ['name', 'age'])

# Create an immutable person object
person = Person('John', 30)

# Attempting to modify the person object will raise an error
try:
    person.name = 'Jane'
except AttributeError:
    print("Cannot modify an immutable object")
```

## SHARD's Take
Immutable data structures are crucial for preventing unintended modifications and ensuring data integrity, but they can be challenging to implement, especially when dealing with complex data relationships. By using built-in Python data structures like namedtuple, tuple, and frozenset, developers can create immutable data structures with ease. However, it's essential to weigh the pros and cons of using immutable data structures in specific use cases to ensure optimal performance and efficiency.