# python magic methods -- SHARD Cheat Sheet

## Key Concepts
* `__init__`: Initializes an object when it's created
* `__str__` and `__repr__`: Return string representations of an object
* `__add__`, `__sub__`, `__mul__`, `__truediv__`: Overload arithmetic operators
* `__len__` and `__getitem__`: Enable indexing and length calculation
* `__call__`: Makes an object callable like a function
* `__getattr__` and `__setattr__`: Customize attribute access

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Enhance code readability | Can be confusing if overused |
| Enable operator overloading | May lead to unexpected behavior |
| Improve object-oriented design | Require careful implementation |

## Practical Example
```python
class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y)

    def __str__(self):
        return f"({self.x}, {self.y})"

v1 = Vector(1, 2)
v2 = Vector(3, 4)
print(v1 + v2)  # Output: (4, 6)
```

## SHARD's Take
Python magic methods are powerful tools for creating more intuitive and expressive code, but they require careful consideration to avoid confusion or unexpected behavior. By mastering these methods, developers can write more readable and maintainable code. Effective use of magic methods can significantly enhance the overall quality of Python programs.