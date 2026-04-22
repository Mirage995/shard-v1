# python generators basics -- SHARD Cheat Sheet

## Key Concepts
* Generators: a type of iterable, like lists or tuples, but they do not allow indexing and can only be iterated over once
* Yield statement: used to define generators, it produces a value and pauses the function until the next value is requested
* Iterator protocol: a protocol that allows objects to be iterated over, it consists of two methods: `__iter__` and `__next__`
* Generator expression: a compact way to create generators, similar to list comprehensions
* Infinite generators: generators that can produce an infinite sequence of values

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Memory efficient | Can only be iterated over once |
| Flexible and customizable | Can be difficult to understand and use |
| Allow for lazy evaluation | May not be suitable for all use cases |

## Practical Example
```python
def infinite_sequence():
    num = 0
    while True:
        yield num
        num += 1

gen = infinite_sequence()
for _ in range(10):
    print(next(gen))
```

## SHARD's Take
Understanding python generators basics is crucial for efficient and effective programming, as they allow for memory-efficient and flexible iteration over sequences of values. Generators are particularly useful when working with large datasets or infinite sequences. By mastering generators, developers can write more efficient and scalable code.