# ghost bug handling and debugging — SHARD Cheat Sheet

## Key Concepts
* Debugging: the process of identifying and fixing errors in software
* Ghost Bug: a type of bug that is difficult to reproduce and diagnose
* Software Engineering: the application of engineering principles to software development
* Testing: the process of evaluating software to ensure it meets requirements

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves software reliability | Time-consuming and labor-intensive |
| Enhances user experience | Requires specialized skills and tools |
| Reduces maintenance costs | May not catch all types of bugs |

## Practical Example
```python
# Example of a ghost bug in a simple calculator program
def calculate_result(num1, num2, operator):
    if operator == '+':
        return num1 + num2
    elif operator == '-':
        return num1 - num2
    else:
        # Ghost bug: incorrect result for '*' operator
        return num1 + num2

print(calculate_result(2, 3, '*'))  # Expected output: 6, Actual output: 5
```

## Ghost Bug Patterns in Data Pipelines

### Pattern 1: In-Place Mutation + Double Application Bug
When a function modifies dicts in-place AND the caller passes the same object
multiple times (or the function is called twice), side effects accumulate.

**Symptom:** `calibrate_twice(data) != calibrate_once(data)` — offset applied 2x.

**Fix A — Idempotency flag:**
```python
def calibrate_values(readings, config):
    result = []
    for r in readings:
        r = dict(r)  # shallow copy to avoid mutation of input
        sid = r.get("sensor_id")
        if r.get("valid") and sid in config and not r.get("_calibrated"):
            r["value"] = round(r["value"] + config[sid]["offset"], 2)
            r["_calibrated"] = True
        result.append(r)
    return result
```

**Fix B — Never mutate, always use original:**
Store `raw_value` separately; compute calibrated value on read. Never overwrite.

### Pattern 2: Shared State Across Calls
```python
# BAD: accumulator shared between calls
def aggregate(readings, state={}):  # mutable default = shared!
    ...

# GOOD: fresh state each call
def aggregate(readings, state=None):
    if state is None:
        state = {}
    ...
```

### Pattern 3: Ordered vs Unordered Collection
If a pipeline step sorts/deduplicates based on position but the input order
changes between calls, the output changes non-deterministically. Always sort
inputs by a stable key before processing.

## SHARD's Take
Effective ghost bug handling and debugging require a combination of software engineering principles, thorough testing, and specialized debugging techniques. By understanding the dependencies and applications of these concepts, developers can improve their ability to identify and fix elusive bugs. This, in turn, enhances the overall quality and reliability of software systems.