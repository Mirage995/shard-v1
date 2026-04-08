# dynamic programming -- SHARD Cheat Sheet

## Key Concepts
* Optimal Substructure: breaking down problems into smaller subproblems with optimal solutions
* Overlapping Subproblems: subproblems that recur multiple times in a problem, requiring efficient solutions
* Memoization: storing solutions to subproblems to avoid redundant calculations
* Tabulation: storing solutions to subproblems in a table for efficient lookup
* Divide and Conquer: breaking down problems into smaller subproblems and solving them recursively

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient solution to complex problems | Difficult to identify optimal substructure and overlapping subproblems |
| Avoids redundant calculations | Requires extra memory for memoization or tabulation |
| Improves performance by reducing computational time | Can be challenging to implement and debug |

## Practical Example
```python
def fibonacci(n, memo = {}):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    elif n not in memo:
        memo[n] = fibonacci(n-1, memo) + fibonacci(n-2, memo)
    return memo[n]

print(fibonacci(10))  # calculates the 10th Fibonacci number using memoization
```

## SHARD's Take
Dynamic programming is a powerful technique for solving complex problems, but its abstract nature and the need for a strategic approach can make it challenging to grasp. By understanding key concepts like optimal substructure, overlapping subproblems, and memoization, developers can unlock efficient solutions to a wide range of problems. With practice and experience, dynamic programming can become a valuable tool in any developer's toolkit.