# circuit breaker pattern python — SHARD Cheat Sheet

## Key Concepts
*   **Circuit Breaker:** Prevents an application from repeatedly trying to execute an operation that's likely to fail, allowing it to rest and potentially recover.
*   **Open State:** The circuit breaker immediately fails all requests when the failure threshold is met.
*   **Closed State:** The circuit breaker allows requests to pass through, monitoring for failures.
*   **Half-Open State:** After a timeout, the circuit breaker allows a limited number of test requests to pass through to check if the service has recovered.
*   **Failure Threshold:** The number of failures that must occur within a specified time period to trip the circuit.
*   **Recovery Timeout:** The amount of time the circuit breaker remains in the open state before transitioning to the half-open state.
*   **State Management:** Storing and updating the circuit breaker's state (Open, Closed, Half-Open).
*   **Error Classification:** Identifying which errors should trigger the circuit breaker.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves system resilience and fault tolerance. | Adds complexity to the codebase. |
| Prevents cascading failures. | Requires careful configuration of thresholds and timeouts. |
| Enables graceful degradation of service. | Can mask underlying problems if not properly monitored. |
| Reduces latency by avoiding calls to failing services. | May require external storage for distributed state (e.g., Redis). |

## Practical Example

```python
import time
import random

class CircuitBreaker:
    def __init__(self, failure_threshold, recovery_timeout):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "CLOSED"
        self.failure_count = 0
        self.last_failure_time = None

    def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                try:
                    result = func(*args, **kwargs)
                    self.reset()
                    return result
                except Exception as e:
                    self.record_failure()
                    raise e
            else:
                raise Exception("Circuit Breaker Open")
        else:
            try:
                result = func(*args, **kwargs)
                self.reset()
                return result
            except Exception as e:
                self.record_failure()
                raise e

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            print("Circuit Breaker OPEN")

    def reset(self):
        self.failure_count = 0
        self.state = "CLOSED"
        print("Circuit Breaker CLOSED")

# Example usage:
def unreliable_service():
    if random.random() < 0.5:
        raise Exception("Service failed")
    return "Service successful"

breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=5)

for _ in range(10):
    try:
        result = breaker.call(unreliable_service)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(1)
```

## SHARD's Take
Circuit breakers are essential for building resilient systems, preventing cascading failures and improving overall stability.  Effective implementation requires a clear understanding of error types and appropriate configuration of failure thresholds and recovery timeouts. Consider using libraries like `pybreaker` for more robust features.