# dynamic programming -- SHARD Cheat Sheet

## Key Concepts
* Optimal Substructure: breaking down problems into smaller subproblems with optimal solutions
* Overlapping Subproblems: solving subproblems only once to avoid redundant computation
* Memoization: storing solutions to subproblems to avoid recomputation
* Tabulation: solving problems by iteratively filling a table of solutions
* Recursion: solving problems by breaking them down into smaller instances of the same problem

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient solution to complex problems | Can be challenging to identify optimal substructure |
| Avoids redundant computation | Requires extra memory for memoization or tabulation |
| Improves performance by reducing computation | Can be difficult to implement for problems with complex dependencies |

## Practical Example
```python
def fibonacci(n, memo = {}):
    if n in memo:
        return memo[n]
    if n <= 2:
        return 1
    memo[n] = fibonacci(n-1, memo) + fibonacci(n-2, memo)
    return memo[n]

print(fibonacci(10))  # Output: 55
```

## SHARD's Take
Dynamic programming is a powerful technique for solving complex problems, but its abstract nature and counterintuitive approach can make it challenging to master. By breaking down problems into smaller subproblems and storing solutions to avoid redundant computation, dynamic programming can significantly improve performance. With practice and experience, developers can become proficient in applying dynamic programming to a wide range of problems.