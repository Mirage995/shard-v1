# currying partial application python -- SHARD Cheat Sheet

## Key Concepts
* Currying: a process of transforming a function with multiple arguments into a sequence of functions, each taking one argument.
* Partial Application: a technique of applying a function to some, but not all, of its arguments, returning a new function that takes the remaining arguments.
* Higher-Order Functions: functions that take other functions as arguments or return functions as output.
* Lambda Functions: small anonymous functions that can be defined inline.
* Function Composition: combining multiple functions to create a new function.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves code readability and reusability | Can be difficult to understand and debug for complex functions |
| Enables functional programming techniques | May lead to performance overhead due to increased function calls |
| Enhances modularity and flexibility | Requires careful handling of function arguments and return types |

## Practical Example
```python
from functools import partial

def add(a, b, c):
    return a + b + c

# Partial application of the add function
add_5 = partial(add, 5)

# Currying the add function
def curry_add(a):
    def inner(b):
        def inner_inner(c):
            return a + b + c
        return inner_inner
    return inner

# Using the curried add function
curried_add_5 = curry_add(5)
curried_add_5_3 = curried_add_5(3)
result = curried_add_5_3(2)
print(result)  # Output: 10
```

## SHARD's Take
The concept of currying partial application in Python is a powerful tool for functional programming and optimization algorithms. By applying these techniques, developers can create more modular, flexible, and efficient code. However, it requires careful consideration of function arguments, return types, and performance implications to avoid potential pitfalls.