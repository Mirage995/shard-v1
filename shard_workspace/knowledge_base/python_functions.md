# python functions -- SHARD Cheat Sheet

## Key Concepts
* Functions: reusable blocks of code that take arguments and return values
* Function definitions: defined using the `def` keyword, followed by the function name and parameters
* Function calls: invoke a function by its name, passing in required arguments
* Return types: functions can return single values, lists, dictionaries, or other data structures
* Lambda functions: small, anonymous functions defined using the `lambda` keyword
* Higher-order functions: functions that take other functions as arguments or return functions as output

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Code reuse | Complexity in debugging |
| Modularity | Overhead in function calls |
| Readability | Potential for namespace pollution |
| Easier maintenance | Risk of function signature changes |

## Practical Example
```python
def greet(name: str) -> None:
    """Prints a personalized greeting message."""
    print(f"Hello, {name}!")

def calculate_sum(numbers: list[int]) -> int:
    """Returns the sum of a list of numbers."""
    return sum(numbers)

# Example usage:
greet("SHARD")
numbers = [1, 2, 3, 4, 5]
result = calculate_sum(numbers)
print(f"Sum: {result}")
```

## SHARD's Take
Mastering Python functions is essential for any aspiring developer, as they enable code reuse, modularity, and readability. However, it's crucial to balance the benefits of functions with potential drawbacks, such as increased complexity and overhead. By understanding the key concepts and best practices, developers can harness the full power of Python functions to write efficient, maintainable, and scalable code.