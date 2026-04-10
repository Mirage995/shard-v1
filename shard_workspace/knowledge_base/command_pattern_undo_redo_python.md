# command pattern undo redo python -- SHARD Cheat Sheet

## Key Concepts
* Command Pattern: a design pattern that encapsulates a request or action as a separate object, allowing for flexible and extensible implementation of undo and redo functionality.
* Memento Pattern: a design pattern that captures the internal state of an object, enabling the creation of snapshots for undo and redo purposes.
* Stack Data Structure: a linear data structure that follows the Last-In-First-Out (LIFO) principle, ideal for implementing undo and redo stacks.
* Undo/Redo Stacks: a mechanism for storing and managing commands or actions, allowing for efficient undo and redo operations.
* Command Interface: a common interface for all commands, defining methods for execution, undo, and redo.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Decouples sender and receiver | Increases complexity with additional classes |
| Enables flexible and extensible implementation | Requires careful management of command objects |
| Supports undo and redo functionality | Can lead to memory issues if not properly implemented |

## Practical Example
```python
from abc import ABC, abstractmethod

class Command(ABC):
    @abstractmethod
    def execute(self):
        pass

    @abstractmethod
    def undo(self):
        pass

class ConcreteCommand(Command):
    def __init__(self, receiver):
        self.receiver = receiver

    def execute(self):
        self.receiver.action()

    def undo(self):
        self.receiver.undo_action()

class Receiver:
    def action(self):
        print("Performing action")

    def undo_action(self):
        print("Undoing action")

class Invoker:
    def __init__(self):
        self.commands = []

    def add_command(self, command):
        self.commands.append(command)

    def execute_commands(self):
        for command in self.commands:
            command.execute()

    def undo_commands(self):
        for command in reversed(self.commands):
            command.undo()

# Usage
receiver = Receiver()
command = ConcreteCommand(receiver)
invoker = Invoker()
invoker.add_command(command)
invoker.execute_commands()
invoker.undo_commands()
```

## SHARD's Take
The command pattern is a powerful tool for implementing undo and redo functionality, but its effectiveness relies on careful design and management of command objects. By decoupling senders and receivers, the command pattern enables flexible and extensible implementation, making it a valuable addition to any developer's toolkit. However, it requires a thorough understanding of the pattern's intricacies to avoid increased complexity and potential memory issues.