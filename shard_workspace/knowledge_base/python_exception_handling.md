# python exception handling -- SHARD Cheat Sheet

## Key Concepts
* **EAFP (Easier to Ask Forgiveness than Permission)**: Attempt operations and handle exceptions rather than checking preconditions—the Pythonic way
* **Catch Narrow Exceptions**: Always catch specific exception types instead of broad catches to avoid masking unexpected errors
* **Try-Except Block**: Use try-except blocks to handle exceptions and ensure code robustness
* **Custom Exceptions**: Define custom exceptions to handle specific error scenarios and improve program customization
* **Exception Hierarchy**: Understand the Python exception hierarchy to effectively catch and handle exceptions

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves code robustness | Can be verbose if not used judiciously |
| Enhances error handling | May mask unexpected errors if not implemented correctly |
| Allows for custom error handling | Requires a good understanding of the exception hierarchy |

## Practical Example
```python
try:
    result = 10 / 0
except ZeroDivisionError:
    print("Cannot divide by zero!")
except TypeError:
    print("Invalid type for division")
else:
    print("Division successful")
finally:
    print("Division attempt completed")
```

## SHARD's Take
Python exception handling is crucial for writing robust programs, and understanding the differences between syntax errors and exceptions is essential for effective error management. By using try-except blocks, catching narrow exceptions, and defining custom exceptions, developers can ensure their code is more reliable and maintainable. Effective exception handling is a key aspect of Python programming that can make a significant difference in the overall quality of the code.