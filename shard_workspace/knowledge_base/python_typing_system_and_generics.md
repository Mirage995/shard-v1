# python typing system and generics — SHARD Cheat Sheet

## Key Concepts
* Type Hints: Specify expected types for function parameters and return values
* Static Type Checkers: Identify potential errors before runtime using type hints
* Type Aliases: Simplify complex type signatures and improve code readability
* Typing Module: Add type hints to code for enhanced clarity and static analysis
* Generics: Create reusable type definitions for flexible coding
* Protocols: Define structural subtyping interfaces for better code structure

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves code readability | Steep learning curve |
| Catches errors early | Additional overhead for simple projects |
| Enhances code maintainability | Not enforced at runtime by default |

## Practical Example
```python
from typing import List, TypeVar, Generic

T = TypeVar('T')

class Stack(Generic[T]):
    def __init__(self):
        self.items: List[T] = []

    def push(self, item: T) -> None:
        self.items.append(item)

    def pop(self) -> T:
        return self.items.pop()

# Create a stack of integers
int_stack = Stack[int]()
int_stack.push(1)
int_stack.push(2)

# Create a stack of strings
str_stack = Stack[str]()
str_stack.push("hello")
str_stack.push("world")
```

## SHARD's Take
Python's typing system is a powerful tool for improving code quality, but it can be complex to master. Starting with simple type hints and gradually introducing more advanced features like generics and protocols can help developers catch errors early and improve code maintainability. By focusing on practical benefits, developers can harness the full potential of Python's typing system.