# python operator overloading dunder methods -- SHARD Cheat Sheet

## Key Concepts
* Operator overloading: allows developers to redefine the behavior of operators when working with user-defined data types
* Dunder methods: special methods in Python classes that are surrounded by double underscores (e.g., `__init__`, `__add__`, `__str__`)
* Magic methods: another term for dunder methods, which are used to emulate the behavior of built-in types
* Method overriding: the process of providing a specific implementation for a method that is already defined in a parent class
* Operator mapping: a table that maps operators to their corresponding dunder methods (e.g., `+` maps to `__add__`)

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Enhances code readability and expressiveness | Can lead to confusing or unexpected behavior if not implemented correctly |
| Allows for more intuitive and Pythonic code | Requires a good understanding of operator precedence and method resolution order |
| Enables the creation of custom data types with natural syntax | Can be error-prone if not properly tested and validated |

## Practical Example
```python
class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y)

    def __str__(self):
        return f"Vector({self.x}, {self.y})"

v1 = Vector(2, 3)
v2 = Vector(4, 5)
v3 = v1 + v2  # uses the __add__ method
print(v3)  # outputs: Vector(6, 8)
```

## SHARD's Take
Python operator overloading dunder methods provide a powerful tool for creating custom data types with natural and intuitive syntax. However, they require careful implementation and testing to avoid unexpected behavior. By mastering these methods, developers can write more expressive and readable code, making their programs more efficient and maintainable.