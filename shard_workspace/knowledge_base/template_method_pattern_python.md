# template method pattern python -- SHARD Cheat Sheet

## Key Concepts
* Template Method Pattern: a behavioral design pattern that defines the skeleton of an algorithm in a method, deferring some steps to subclasses.
* Abstract Class: a class that cannot be instantiated and is designed to be inherited by other classes.
* Concrete Class: a class that implements the template method pattern by providing the implementation for the abstract methods.
* Hook Method: a method that is intended to be overridden by subclasses to provide a way to customize the algorithm.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Provides a way to define an algorithm's skeleton | Can be inflexible if not designed carefully |
| Allows for code reuse | Can lead to tight coupling between classes |
| Enables customization through hook methods | Can make the code harder to understand if overused |

## Practical Example
```python
from abc import ABC, abstractmethod

class Game(ABC):
    def play(self):
        self.initialize()
        self.start()
        self.end()

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def end(self):
        pass

class ChessGame(Game):
    def initialize(self):
        print("Setting up the board")

    def start(self):
        print("Starting the game")

    def end(self):
        print("Checking for checkmate")

chess = ChessGame()
chess.play()
```

## SHARD's Take
The template method pattern is a powerful tool for defining algorithms with customizable steps, but it requires careful design to avoid inflexibility and tight coupling. By using abstract classes and hook methods, developers can create flexible and reusable code. However, overusing this pattern can lead to complex and hard-to-understand code.