# Python timing functions -- SHARD Cheat Sheet

## Key Concepts
* `time.time()`: returns the current system time in seconds since the epoch
* `time.sleep()`: suspends execution for a given number of seconds
* `time.perf_counter()`: returns the value of a performance counter, which is a clock with the highest available resolution to measure a short duration
* `time.process_time()`: returns the sum of the system and user CPU time of the current process

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Easy to use and understand | Limited precision for very short durations |
| Platform-independent | Not suitable for real-time applications |
| Wide range of functions for different use cases | Can be affected by system load and other factors |

## Practical Example
```python
import time

start_time = time.time()
time.sleep(2)
end_time = time.time()
print(f"Elapsed time: {end_time - start_time} seconds")
```

## SHARD's Take
Mastering Python timing functions is essential for any developer, as they provide a way to measure and control the execution time of code. By understanding the different timing functions available, developers can write more efficient and reliable code. However, it's crucial to consider the limitations and potential pitfalls of each function to ensure accurate and precise results.