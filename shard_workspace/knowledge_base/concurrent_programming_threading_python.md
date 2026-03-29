# concurrent programming threading python — SHARD Cheat Sheet

## Key Concepts
*   **Thread:** A lightweight unit of execution within a process, sharing the same memory space.
*   **Concurrency:** The ability of a program to manage multiple tasks seemingly simultaneously.
*   **Global Interpreter Lock (GIL):** A mutex that allows only one thread to hold control of the Python interpreter at any given time.
*   **I/O-bound:** Tasks that spend more time waiting for input/output operations than performing computations.
*   **CPU-bound:** Tasks that spend more time performing computations than waiting for I/O.
*   **Thread Synchronization:** Mechanisms (locks, semaphores, etc.) to coordinate access to shared resources among threads.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves responsiveness for I/O-bound tasks | GIL limits true parallelism for CPU-bound tasks in CPython |
| Relatively simple to implement for basic concurrency | Can introduce race conditions and deadlocks if not managed carefully |
| Threads share memory space, facilitating data sharing | Requires careful synchronization to avoid data corruption |

## Practical Example
```python
import threading
import time

def task(name):
    print(f"Thread {name}: starting")
    time.sleep(1)  # Simulate I/O-bound operation
    print(f"Thread {name}: finishing")

if __name__ == "__main__":
    threads = []
    for i in range(3):
        t = threading.Thread(target=task, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join() # Wait for all threads to complete

    print("All threads finished")
```

## Lock vs RLock — Critical Distinction

**`threading.Lock()`** — NOT reentrant. If a thread that already holds the lock tries to acquire it again, it DEADLOCKS immediately.

**`threading.RLock()`** — Reentrant. The same thread can acquire the lock multiple times. Releases only when acquired/released counts balance.

```python
# DEADLOCK — Lock not reentrant
class Foo:
    def __init__(self):
        self._lock = threading.Lock()
    def _internal(self):
        with self._lock:      # DEADLOCK: caller already holds the lock
            ...
    def method(self):
        with self._lock:
            self._internal()  # tries to re-acquire — blocks forever

# CORRECT — use RLock for methods that call other locked methods
class Foo:
    def __init__(self):
        self._lock = threading.RLock()  # reentrant
    def _internal(self):
        with self._lock:      # OK: same thread can acquire again
            ...
    def method(self):
        with self._lock:
            self._internal()  # safe
```

**Rule:** if a class has private helper methods that acquire `self._lock` AND those helpers are called from within other locked methods, use `RLock`.

## Deadlock Prevention

1. **Single global lock** + `RLock`: simplest, but serializes all operations.
2. **Per-resource locks** + consistent ordering: higher throughput, but requires
   always acquiring locks in the same order (e.g., alphabetical by key) to avoid
   circular dependencies.

```python
# Per-account locking with consistent ordering (avoids deadlock in transfer)
class Bank:
    def __init__(self):
        self.accounts = {}
        self._locks = {}          # per-account lock
        self._meta_lock = threading.Lock()  # protects accounts/locks dicts

    def _get_lock(self, account_id):
        with self._meta_lock:
            if account_id not in self._locks:
                self._locks[account_id] = threading.Lock()
            return self._locks[account_id]

    def transfer(self, src, dst, amount):
        # Acquire locks in consistent order to prevent deadlock
        first, second = sorted([src, dst])
        with self._get_lock(first):
            with self._get_lock(second):
                ...
```

## SHARD's Take
Threading in Python is useful for I/O-bound tasks where the GIL's limitations are less impactful. However, for CPU-bound tasks, consider multiprocessing to bypass the GIL and achieve true parallelism. Careful synchronization is always necessary to prevent race conditions when using threads.

**For classes with nested locking (helpers called from within locked methods): always use `RLock`, not `Lock`.** This is the most common source of deadlocks in object-oriented code.