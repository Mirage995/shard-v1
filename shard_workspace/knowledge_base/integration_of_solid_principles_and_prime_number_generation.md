# Integration of solid principles and prime number generation — SHARD Cheat Sheet

## Key Concepts
*   **Single Responsibility Principle (SRP):** A class should have only one reason to change, focusing prime generation logic in a dedicated class.
*   **Open/Closed Principle (OCP):** Software entities should be open for extension, but closed for modification, allowing different prime generation algorithms to be added without altering existing code.
*   **Liskov Substitution Principle (LSP):** Subtypes must be substitutable for their base types, ensuring different prime generators can be used interchangeably.
*   **Interface Segregation Principle (ISP):** Clients should not be forced to depend on methods they do not use, defining specific interfaces for different prime generation needs.
*   **Dependency Inversion Principle (DIP):** High-level modules should not depend on low-level modules, both should depend on abstractions, decoupling prime generation logic from its usage.
*   **Prime Number Generation:** Algorithms for efficiently generating prime numbers, such as trial division, Sieve of Eratosthenes, or Miller-Rabin primality test.
*   **Abstraction:** Hiding complex implementation details behind a simplified interface, allowing users to interact with prime generation without understanding the underlying algorithms.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Promotes modularity and maintainability. | Can introduce complexity if SOLID principles are over-applied. |
| Enables easy switching between different prime generation algorithms. | May require more upfront design and planning. |
| Improves testability by isolating prime generation logic. | Potential performance overhead due to abstraction layers. |
| Enhances code reusability across different parts of the application. |  |

## Practical Example
```python
from abc import ABC, abstractmethod

class PrimeGenerator(ABC):
    @abstractmethod
    def generate_primes(self, limit: int) -> list[int]:
        pass

class SieveOfEratosthenes(PrimeGenerator):
    def generate_primes(self, limit: int) -> list[int]:
        primes = [True] * (limit + 1)
        primes[0] = primes[1] = False
        for i in range(2, int(limit**0.5) + 1):
            if primes[i]:
                for j in range(i*i, limit + 1, i):
                    primes[j] = False
        return [i for i, is_prime in enumerate(primes) if is_prime]

class PrimeService:
    def __init__(self, generator: PrimeGenerator):
        self.generator = generator

    def get_primes(self, limit: int) -> list[int]:
        return self.generator.generate_primes(limit)

# Usage
sieve_generator = SieveOfEratosthenes()
prime_service = PrimeService(sieve_generator)
primes = prime_service.get_primes(100)
print(primes)

# Example of extending with a different algorithm (Open/Closed Principle)
class TrialDivision(PrimeGenerator):
    def generate_primes(self, limit: int) -> list[int]:
        primes = []
        for num in range(2, limit + 1):
            is_prime = True
            for i in range(2, int(num**0.5) + 1):
                if num % i == 0:
                    is_prime = False
                    break
            if is_prime:
                primes.append(num)
        return primes

trial_generator = TrialDivision()
prime_service_trial = PrimeService(trial_generator)
primes_trial = prime_service_trial.get_primes(100)
print(primes_trial)
```

## SHARD's Take
Applying SOLID principles to prime number generation leads to more maintainable and extensible code. By decoupling the prime generation logic from its usage, we can easily swap algorithms or add new ones without affecting other parts of the application. This approach promotes code reusability and testability, ultimately resulting in a more robust system.