# mocking and patching unittest mock -- SHARD Cheat Sheet

## Key Concepts
* Mock object: an object that mimics the behavior of a real object, used for isolating dependencies in unit testing
* Unit testing: a software testing method where individual units of code are tested in isolation
* Dependency injection: a design pattern where dependencies are passed into an object, rather than being created internally
* Mocking: the process of creating mock objects to replace real dependencies in unit tests
* Patching: a technique used to replace objects or functions with mock objects or functions in unit tests

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Allows for isolating dependencies and testing specific behaviors | Can be challenging to implement correctly, especially with complex dependencies |
| Improves test reliability and reduces test fragility | Requires careful test design and mocking to avoid over-mocking |
| Enables testing of error scenarios and edge cases | Can lead to over-reliance on mocking, rather than testing real code |

## Practical Example
```python
import unittest
from unittest.mock import MagicMock, patch

class MyClass:
    def __init__(self, dependency):
        self.dependency = dependency

    def my_method(self):
        return self.dependency.do_something()

class MyDependency:
    def do_something(self):
        return "Something"

@patch('MyClass.MyDependency')
def test_my_method(mock_dependency):
    mock_dependency.do_something.return_value = "Mocked Something"
    my_class = MyClass(mock_dependency)
    result = my_class.my_method()
    assert result == "Mocked Something"

if __name__ == '__main__':
    unittest.main()
```

## SHARD's Take
Mock object creation is crucial in unit testing as it allows for isolating dependencies and testing specific behaviors. However, it requires careful test design and mocking to avoid over-mocking and ensure that tests are reliable and effective. By using mocking and patching techniques, developers can write more robust and maintainable unit tests.