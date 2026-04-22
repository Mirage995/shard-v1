# parametrize fixtures pytest advanced -- SHARD Cheat Sheet

## Key Concepts
* Parametrization: allows multiple sets of inputs to be used for a single test function
* Fixtures: setup and teardown functions that provide a fixed baseline for tests
* Pytest.mark.parametrize: a decorator that enables parametrization of test functions
* Indirect parametrization: allows fixtures to be parametrized indirectly through the use of other fixtures
* IDs: unique identifiers for parametrized tests, useful for debugging and reporting

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Enables efficient testing of multiple scenarios | Can lead to test complexity and maintainability issues if not managed properly |
| Reduces test duplication and improves code reuse | Requires careful consideration of test data and fixture setup |
| Supports data-driven testing and behavior-driven development | Can be challenging to debug and troubleshoot parametrized tests |

## Practical Example
```python
import pytest

@pytest.mark.parametrize("input, expected", [
    ("hello", "HELLO"),
    ("world", "WORLD"),
    ("python", "PYTHON")
])
def test_uppercase(input, expected):
    assert input.upper() == expected
```

## SHARD's Take
Parametrizing fixtures with pytest is a powerful technique for efficient and effective testing, but it requires careful consideration of test data and fixture setup to avoid complexity and maintainability issues. By leveraging indirect parametrization and unique IDs, developers can create robust and scalable test suites that support data-driven testing and behavior-driven development.