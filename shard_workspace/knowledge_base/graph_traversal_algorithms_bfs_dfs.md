# graph traversal algorithms bfs dfs -- SHARD Cheat Sheet

## Key Concepts
* **Graph Data Structure**: A collection of nodes (vertices) and edges that connect these nodes.
* **Stack**: Used to keep track of nodes during the DFS traversal.
* **Queue**: Used to keep track of nodes during the BFS traversal.
* **Breadth-First Search (BFS)**: Explores nodes in a graph level by level, starting from a given source node.
* **Depth-First Search (DFS)**: Explores nodes in a graph by traversing as far as possible along each branch before backtracking.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Simple implementation for unweighted graphs. | Can lead to high memory usage due to recursion stack. |
| Efficient for finding shortest paths in unweighted graphs. | May not be suitable for very large graphs due to memory constraints. |
| Useful for cycle detection, topological sorting, and backtracking. | Can be slower than other algorithms for very large graphs. |

## Practical Example
```python
from collections import deque

def bfs(graph, source):
    visited = set()
    queue = deque([source])
    visited.add(source)
    
    while queue:
        node = queue.popleft()
        print(node, end=" ")
        
        for neighbor in graph[node]:
            if neighbor not in visited:
                queue.append(neighbor)
                visited.add(neighbor)

def dfs(graph, source):
    visited = set()
    stack = [source]
    visited.add(source)
    
    while stack:
        node = stack.pop()
        print(node, end=" ")
        
        for neighbor in graph[node]:
            if neighbor not in visited:
                stack.append(neighbor)
                visited.add(neighbor)

# Example usage:
graph = {
    'A': ['B', 'C'],
    'B': ['A', 'D', 'E'],
    'C': ['A', 'F'],
    'D': ['B'],
    'E': ['B', 'F'],
    'F': ['C', 'E']
}

print("BFS Traversal: ")
bfs(graph, 'A')
print("\nDFS Traversal: ")
dfs(graph, 'A')
```

## SHARD's Take
Graph traversal algorithms, particularly BFS and DFS, are fundamental techniques in computer science that can be challenging to implement correctly, but are crucial for efficiently exploring interconnected data and powering various applications. By understanding the trade-offs between these algorithms, developers can choose the most suitable approach for their specific use case. With practice and experience, implementing these algorithms becomes more intuitive, enabling the creation of more efficient and robust applications.