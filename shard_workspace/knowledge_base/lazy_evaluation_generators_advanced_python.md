# lazy evaluation generators advanced python -- SHARD Cheat Sheet

## Key Concepts
* Lazy evaluation: a technique where expressions are evaluated only when their values are actually needed
* Generators: a type of iterable, like lists or tuples, but they do not allow indexing and can only be iterated over once
* Yield statement: used to define generators, it produces a value and suspends the function's execution until the next value is requested
* Async generators: allow for asynchronous iteration, enabling the use of await and async/await syntax
* Streams: a sequence of data that can be processed in a pipeline fashion, often using lazy evaluation

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Memory efficiency | Limited control over the iteration process |
| Improved performance | Can be difficult to debug and test |
| Enables parallel computing | May require significant changes to existing code |

## Practical Example
```python
def infinite_sequence():
    num = 0
    while True:
        yield num
        num += 1

seq = infinite_sequence()
for _ in range(10):
    print(next(seq))
```

## SHARD's Take
Mastering lazy evaluation and generators is essential for efficient and scalable programming in Python. By understanding how to leverage these concepts, developers can write more memory-efficient and performant code. However, it requires a good grasp of Python fundamentals and a careful consideration of the trade-offs involved.