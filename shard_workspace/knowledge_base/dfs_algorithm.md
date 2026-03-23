# dfs algorithm — SHARD Cheat Sheet

## Key Concepts
- **Graph Data Structure**: A collection of nodes (vertices) and edges that connect these nodes.
- **Stack**: Used to keep track of nodes during the DFS traversal.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Simple implementation for unweighted graphs. | Can lead to high memory usage due to recursion stack. |
| Efficient for finding paths and cycles in graphs. | Not suitable for large graphs as it may not terminate if there are no backtracking points. |

## Practical Example
```python
def dfs(graph, start, visited=None):
    if visited is None:
        visited = set()
    visited.add(start)
    print(start, end=' ')
    for neighbor in graph[start]:
        if neighbor not in visited:
            dfs(graph, neighbor, visited)

# Example usage
graph = {
    'A': ['B', 'C'],
    'B': ['D', 'E'],
    'C': ['F'],
    'D': [],
    'E': ['F'],
    'F': []
}
dfs(graph, 'A')
```

## SHARD's Take
DFS is a fundamental algorithm for traversing or searching tree or graph data structures. It is particularly useful for exploring all possible paths from a starting node to find a goal or to perform operations like topological sorting and cycle detection. However, it requires careful handling of memory due to its recursive nature, which can lead to stack overflow errors in large graphs.