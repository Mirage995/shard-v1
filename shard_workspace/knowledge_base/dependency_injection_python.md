# dependency injection python — SHARD Cheat Sheet

## Key Concepts
*   **Dependency Injection (DI):** A design pattern where dependencies are provided to a component instead of the component creating them.
*   **Inversion of Control (IoC):** A principle where the control of object creation is transferred to another part of a framework.
*   **Constructor Injection:** Passing dependencies to a class through its constructor.
*   **Loose Coupling:** Reducing the dependencies between components to increase modularity.
*   **Testability:** DI makes it easier to test components in isolation by mocking dependencies.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Increased modularity and reusability | Can increase code complexity, especially initially |
| Improved testability through mocking | Requires careful planning and design |
| Easier to maintain and extend | Can lead to over-engineering if not applied judiciously |

## Practical Example
```python
class DatabaseConnection:
    def connect(self):
        return "Connected to database"

class UserProfile:
    def __init__(self, db_connection):
        self.db = db_connection

    def get_profile(self, user_id):
        connection_status = self.db.connect()
        return f"Profile for user {user_id} - {connection_status}"

db = DatabaseConnection()
profile = UserProfile(db)
print(profile.get_profile(123))
```

## SHARD's Take
Dependency injection promotes modularity and testability by decoupling components. While dedicated DI frameworks exist, Python's flexibility allows for simple constructor injection to achieve similar benefits without excessive overhead. Applying DI thoughtfully can lead to more maintainable and robust code.