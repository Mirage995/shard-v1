# strategy pattern runtime behavior python -- SHARD Cheat Sheet

## Key Concepts
* Strategy Pattern: defines a family of algorithms, encapsulates each one, and makes them interchangeable.
* Context Class: encapsulates algorithm execution and delegates work to strategy objects.
* Strategy Object: defines interchangeable algorithms and enables runtime behavior changes.
* Interchangeable Algorithms: allows for client-side algorithm selection and makes applications more flexible.
* Context-Class Independence: ensures that the context class is decoupled from specific strategy objects.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Enables runtime behavior changes | Can be challenging to implement due to interchangeable algorithms and context-class independence |
| Makes applications more flexible | Requires careful design and planning to avoid integration issues |
| Allows for client-side algorithm selection | Can lead to increased complexity if not managed properly |

## Practical Example
```python
from abc import ABC, abstractmethod

# Strategy Interface
class PaymentStrategy(ABC):
    @abstractmethod
    def pay(self, amount):
        pass

# Concrete Strategy 1
class CreditCardStrategy(PaymentStrategy):
    def pay(self, amount):
        print(f"Paying ${amount} using credit card")

# Concrete Strategy 2
class PayPalStrategy(PaymentStrategy):
    def pay(self, amount):
        print(f"Paying ${amount} using PayPal")

# Context Class
class PaymentContext:
    def __init__(self, payment_strategy):
        self.payment_strategy = payment_strategy

    def set_payment_strategy(self, payment_strategy):
        self.payment_strategy = payment_strategy

    def pay(self, amount):
        self.payment_strategy.pay(amount)

# Client code
payment_context = PaymentContext(CreditCardStrategy())
payment_context.pay(100)

payment_context.set_payment_strategy(PayPalStrategy())
payment_context.pay(200)
```

## SHARD's Take
The strategy pattern is a powerful tool for enabling runtime behavior changes and making applications more flexible. However, its implementation can be challenging due to the need for interchangeable algorithms and context-class independence. By carefully designing and planning the strategy pattern, developers can create more flexible and maintainable software systems.