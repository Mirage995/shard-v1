# python enum advanced patterns -- SHARD Cheat Sheet

## Key Concepts
* Enum: defining a set of named values to improve code readability
* IntEnum: creating enumerated constants that are also subclasses of int for bitwise operations
* StrEnum: creating enumerated constants that are also subclasses of str for string-based values
* Flag: creating enumerated constants that can be combined using bitwise operations for flags or masks
* EnumDict: creating a dictionary-like object for Enum members for efficient lookup and storage

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves code readability | Can be overused or misused if not properly understood |
| Provides a way to define a set of named values | May not be suitable for complex or dynamic scenarios |
| Enhances maintainability and robustness | Requires careful planning and design to avoid errors |

## Practical Example
```python
from enum import Enum, IntEnum, Flag

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3

class Shape(IntEnum):
    SQUARE = 1
    CIRCLE = 2
    TRIANGLE = 3

class Permission(Flag):
    READ = 1
    WRITE = 2
    EXECUTE = 4

class User:
    def __init__(self, name, permission):
        self.name = name
        self.permission = permission

user = User("John", Permission.READ | Permission.WRITE)
print(user.permission)  # Output: Permission.READ | Permission.WRITE
```

## SHARD's Take
Mastering Python enumerations is crucial for writing robust and maintainable code, as it provides a way to organize and define a set of named values. However, it requires careful planning and design to avoid errors and ensure effective use. By understanding the different types of enums, such as IntEnum, StrEnum, and Flag, developers can leverage their strengths to improve code readability and maintainability.