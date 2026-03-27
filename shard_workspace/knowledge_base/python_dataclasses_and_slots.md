# python dataclasses and slots — SHARD Cheat Sheet

## Key Concepts
*   **Dataclasses:** Classes automatically generating boilerplate code like `__init__`, `__repr__`, and comparison methods.
*   **`__slots__`:** A class attribute limiting instance attributes to those listed, saving memory and preventing dynamic attribute creation.
*   **Type Hints:** Used to define the types of dataclass fields, enabling static analysis and runtime type checking.
*   **`dataclasses.asdict()`:** Converts a dataclass instance into a dictionary.
*   **Inheritance:** Dataclasses and `__slots__` can be used with inheritance, but require careful consideration.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| **Dataclasses:** Reduced boilerplate code, improved readability. | **Dataclasses:** Can be less flexible than regular classes. |
| **`__slots__`:** Memory savings, prevents accidental attribute creation. | **`__slots__`:**  Makes instances less dynamic, multiple inheritance can be complex. |
| **Type Hints:** Improved code maintainability, static analysis. | **Type Hints:** Requires Python 3.6+, adds verbosity. |

## Practical Example
```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class InventoryItem:
    """Class for keeping track of an item in inventory."""
    name: str
    unit_price: float
    quantity_on_hand: int = 0

    def total_cost(self) -> float:
        return self.unit_price * self.quantity_on_hand

@dataclass
class Order:
    items: List[InventoryItem] = field(default_factory=list)

    def total_order_value(self) -> float:
        return sum(item.total_cost() for item in self.items)

item1 = InventoryItem(name="Widget", unit_price=10.0, quantity_on_hand=5)
item2 = InventoryItem(name="Gadget", unit_price=20.0, quantity_on_hand=3)

order = Order(items=[item1, item2])
print(f"Total order value: {order.total_order_value()}")


class Point:
    __slots__ = ('x', 'y')
    def __init__(self, x, y):
        self.x = x
        self.y = y

p = Point(10, 20)
# p.z = 30 # This will raise an AttributeError
```

## SHARD's Take
Dataclasses offer a convenient way to define data-centric classes, reducing boilerplate and improving code clarity.  Using `__slots__` can significantly reduce memory usage, especially when creating many instances, but it comes with trade-offs regarding flexibility and inheritance complexities. Understanding when and how to use these features is crucial for writing efficient and maintainable Python code.