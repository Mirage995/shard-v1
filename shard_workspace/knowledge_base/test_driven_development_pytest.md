```markdown
# test driven development pytest — SHARD Cheat Sheet

## Key Concepts
*   **Test-Driven Development (TDD):** A software development process where tests are written before the code.
*   **pytest:** A Python testing framework that simplifies writing and running tests.
*   **Red-Green-Refactor Cycle:** Write a failing test (Red), make it pass (Green), improve the code (Refactor).
*   **Unit Testing:** Testing individual components or functions in isolation.
*   **Assertion:** A statement that verifies whether a condition is true.
*   **Fixture:** A pytest feature to provide a fixed baseline for tests.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improved code quality | Steeper learning curve |
| Reduced debugging time | Initial time investment |
| Clearer requirements | Can feel slow at first |
| Increased confidence in code | Requires a shift in mindset |

## Practical Example
```python
# example.py
def add(x, y):
    return x + y

# test_example.py
import pytest
from example import add

def test_add_positive_numbers():
    assert add(2, 3) == 5

def test_add_negative_numbers():
    assert add(-1, -1) == -2

def test_add_mixed_numbers():
    assert add(2, -2) == 0
```

## SHARD's Take
TDD with pytest encourages writing cleaner, more maintainable code by focusing on testable units. While it demands an upfront investment, the long-term benefits of improved code quality and reduced debugging often outweigh the initial costs.
```