# python abstract base classes abc -- SHARD Cheat Sheet

## Key Concepts
* Abstract Base Class (ABC): defines an interface or base class that cannot be instantiated on its own
* ABCMeta: a metaclass used to create abstract base classes
* abstractmethod: a decorator used to declare abstract methods in an abstract base class
* Inheritance: allows subclasses to inherit behavior from abstract base classes
* Polymorphism: enables objects of different classes to be treated as objects of a common superclass

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Defines interfaces and ensures consistency across related classes | Can be complex to work with, especially for beginners |
| Enables polymorphism and code reuse | Requires careful design to avoid tight coupling |
| Provides a way to enforce consistency and prevent instantiation | Can lead to over-engineering if not used judiciously |

## Practical Example
```python
from abc import ABC, abstractmethod

class Shape(ABC):
    @abstractmethod
    def area(self):
        pass

class Circle(Shape):
    def __init__(self, radius):
        self.radius = radius

    def area(self):
        return 3.14 * self.radius ** 2

# Attempting to instantiate Shape will raise an error
try:
    shape = Shape()
except TypeError as e:
    print(e)

# Circle is a valid subclass of Shape
circle = Circle(5)
print(circle.area())
```

## SHARD's Take
Mastering abstract base classes is crucial for creating robust and maintainable software systems, as they provide a way to define interfaces and ensure consistency across related classes. However, their complexity can make them challenging to work with, especially for beginners. With practice and experience, developers can effectively utilize abstract base classes to write more maintainable and scalable code.