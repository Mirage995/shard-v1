# python object oriented -- SHARD Cheat Sheet

## Key Concepts
* Classes: define custom data types with attributes and methods
* Objects: instances of classes, with their own set of attributes and methods
* Inheritance: allows classes to inherit properties and behavior from parent classes
* Polymorphism: ability of an object to take on multiple forms, depending on the context
* Encapsulation: hiding internal implementation details and exposing only necessary information
* Abstraction: representing complex systems in a simplified way, focusing on essential features

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Code reusability and modularity | Increased complexity and overhead |
| Easier maintenance and extension | Steeper learning curve |
| Improved readability and understandability | Potential for over-engineering |

## Practical Example
```python
class Vehicle:
    def __init__(self, brand, model):
        self.brand = brand
        self.model = model

    def honk(self):
        print("Honk!")

class Car(Vehicle):
    def __init__(self, brand, model, year):
        super().__init__(brand, model)
        self.year = year

    def lock_doors(self):
        print("Doors locked.")

my_car = Car("Toyota", "Corolla", 2015)
my_car.honk()  # Output: Honk!
my_car.lock_doors()  # Output: Doors locked.
```

## SHARD's Take
Mastering object-oriented programming in Python is crucial for a successful career in software development, as it enables developers to create reusable, modular, and maintainable code. However, it requires a deep understanding of concepts such as inheritance, polymorphism, and encapsulation. With practice and experience, developers can harness the power of object-oriented programming to build complex and efficient systems.