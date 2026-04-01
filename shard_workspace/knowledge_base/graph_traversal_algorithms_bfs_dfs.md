# graph traversal algorithms bfs dfs -- SHARD Cheat Sheet

## Key Concepts
* **Graph Data Structure**: A collection of nodes (vertices) and edges that connect these nodes.
* **Breadth-First Search (BFS)**: Explores all nodes at a given depth before moving to the next depth level.
* **Depth-First Search (DFS)**: Explores as far as possible along each branch before backtracking.
* **Queue and Stack Data Structures**: Used to keep track of nodes during BFS and DFS traversals, respectively.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Simple implementation for unweighted graphs. | Can lead to high memory usage due to recursion stack. |
| Efficient for finding shortest paths and detecting cycles. | May not be suitable for very large graphs due to memory constraints. |

## Practical Example
```python
from collections import deque

def bfs(graph, start_node):
    visited = set()
    queue = deque([start_node])
    visited.add(start_node)
    
    while queue:
        node = queue.popleft()
        print(node, end=" ")
        
        for neighbor in graph[node]:
            if neighbor not in visited:
                queue.append(neighbor)
                visited.add(neighbor)

def dfs(graph, start_node):
    visited = set()
    stack = [start_node]
    visited.add(start_node)
    
    while stack:
        node = stack.pop()
        print(node, end=" ")
        
        for neighbor in graph[node]:
            if neighbor not in visited:
                stack.append(neighbor)
                visited.add(neighbor)

# Example graph represented as an adjacency list
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
Graph traversal algorithms, particularly DFS and BFS, are crucial for efficiently exploring complex data structures. Understanding their characteristics and applications is essential for choosing the right algorithm for a specific use case. By mastering these algorithms, developers can tackle a wide range of problems in computer science and related fields.