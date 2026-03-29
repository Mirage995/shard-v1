# race condition handling and debugging — SHARD Cheat Sheet

## Key Concepts
*   **Race Condition:** A situation where multiple threads/processes access shared data concurrently, and the final outcome depends on the unpredictable order of execution.
*   **Critical Section:** A code segment that accesses shared resources and must be protected from concurrent access.
*   **Mutual Exclusion:** Ensuring that only one thread/process can access a critical section at a time.
*   **Synchronization:** Coordinating the execution of multiple threads/processes to prevent race conditions.
*   **Deadlock:** A situation where two or more threads/processes are blocked indefinitely, waiting for each other to release resources.
*   **Livelock:** A situation where threads/processes repeatedly change their state in response to each other, preventing any progress.
*   **Atomic Operation:** An operation that appears indivisible; it either completes entirely or not at all, preventing partial updates.
*   **Lock:** A synchronization mechanism that enforces mutual exclusion.
*   **Semaphore:** A synchronization primitive that controls access to a limited number of resources.
*   **Mutex:** A type of lock that provides exclusive access to a shared resource.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Prevents data corruption and inconsistent state. | Can introduce performance overhead due to synchronization. |
| Ensures predictable and reliable program behavior. | Increases code complexity and potential for deadlocks/livelocks. |
| Enables safe concurrent access to shared resources. | Requires careful design and implementation to avoid errors. |

## Practical Example
```python
import threading
import time

counter = 0
lock = threading.Lock()

def increment_counter():
    global counter
    for _ in range(100000):
        with lock:  # Acquire the lock before accessing the shared resource
            counter += 1

def decrement_counter():
    global counter
    for _ in range(100000):
        with lock:  # Acquire the lock before accessing the shared resource
            counter -= 1

if __name__ == "__main__":
    thread1 = threading.Thread(target=increment_counter)
    thread2 = threading.Thread(target=decrement_counter)

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()

    print("Final counter value:", counter) # Expected: 0
```

## Critical: Lock vs RLock — Nested Locking

Use `threading.RLock()` (reentrant) when a method calls another method that also
acquires the same lock. `threading.Lock()` is NOT reentrant — re-acquiring it in
the same thread deadlocks immediately.

```python
# DEADLOCK: Lock is not reentrant
class Bank:
    def __init__(self): self._lock = threading.Lock()
    def _audit(self):
        with self._lock: ...          # second acquire by same thread → DEADLOCK
    def deposit(self):
        with self._lock:              # first acquire
            self._audit()            # internally tries to re-acquire → hangs

# CORRECT: RLock allows same thread to re-acquire
class Bank:
    def __init__(self): self._lock = threading.RLock()  # reentrant
    def _audit(self):
        with self._lock: ...          # safe
    def deposit(self):
        with self._lock:
            self._audit()            # no deadlock
```

**Symptom of Lock deadlock:** tests hang forever with 0 results, no output.
**Fix:** replace `threading.Lock()` with `threading.RLock()` in `__init__`.

## SHARD's Take
Race conditions are insidious bugs that can be difficult to detect and resolve. Proper synchronization mechanisms, such as locks and semaphores, are crucial for preventing race conditions and ensuring the integrity of shared data in concurrent programs. Careful code design and thorough testing are essential to minimize the risk of introducing these issues.