# visitor pattern double dispatch python -- SHARD Cheat Sheet

## Key Concepts
* Visitor Pattern: allows adding new operations to existing object structures without modifying them
* Double Dispatch: a technique to resolve the correct method to call based on the runtime types of two objects
* Object-Oriented Programming: a programming paradigm that organizes software design around data, or objects, rather than functions and logic
* Polymorphism: the ability of an object to take on multiple forms, depending on the context in which it is used
* Encapsulation: the idea of bundling data and methods that operate on that data within a single unit

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Allows for adding new operations without modifying existing code | Can be complex to implement, especially with double dispatching |
| Enables more flexibility in programming | Requires careful planning to avoid issues with method overriding |
| Improves code reusability and maintainability | Can lead to tighter coupling between classes if not implemented carefully |

## Practical Example
```python
from abc import ABC, abstractmethod

class Shape(ABC):
    @abstractmethod
    def accept(self, visitor):
        pass

class Circle(Shape):
    def __init__(self, radius):
        self.radius = radius

    def accept(self, visitor):
        visitor.visit_circle(self)

class Rectangle(Shape):
    def __init__(self, width, height):
        self.width = width
        self.height = height

    def accept(self, visitor):
        visitor.visit_rectangle(self)

class ShapeVisitor:
    def visit_circle(self, circle):
        print(f"Circle with radius {circle.radius}")

    def visit_rectangle(self, rectangle):
        print(f"Rectangle with width {rectangle.width} and height {rectangle.height}")

# Create shapes and visitor
circle = Circle(5)
rectangle = Rectangle(3, 4)
visitor = ShapeVisitor()

# Apply visitor pattern
circle.accept(visitor)
rectangle.accept(visitor)
```

## SHARD's Take
The visitor pattern is a powerful tool for adding new operations to existing object structures without modifying them, but its implementation can be complex, especially when combined with double dispatching. By carefully planning and using object-oriented programming principles, developers can effectively utilize the visitor pattern to improve code reusability and maintainability. With practice and experience, the visitor pattern can become a valuable addition to any programmer's toolkit.