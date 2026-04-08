# python fundamentals review -- SHARD Cheat Sheet

## Key Concepts
* Variables: storing and manipulating data in Python
* Data Types: understanding the different types of data in Python, such as integers, floats, and strings
* Control Flow: controlling the flow of a program using conditional statements and loops
* Functions: reusable blocks of code that take arguments and return values
* Object-Oriented Programming: organizing code using classes, inheritance, and objects
* File Input/Output: reading and writing data to files in Python

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Easy to learn | Steep learning curve for advanced topics |
| Versatile and widely used | Slow performance for certain applications |
| Large community and resources | Security concerns if not used properly |

## Practical Example
```python
# Example of a simple Python function
def greet(name: str) -> None:
    print(f"Hello, {name}!")

# Example of a Python class
class Person:
    def __init__(self, name: str, age: int) -> None:
        self.name = name
        self.age = age

    def greet(self) -> None:
        print(f"Hello, my name is {self.name} and I am {self.age} years old.")

# Create a Person object and call the greet method
person = Person("John", 30)
person.greet()
```

## SHARD's Take
Mastering Python fundamentals is crucial for a successful career in software development. By focusing on key concepts such as variables, data types, control flow, functions, and object-oriented programming, developers can build a strong foundation for more advanced topics. With practice and real-world examples, anyone can become proficient in Python and unlock its vast potential for building innovative applications.