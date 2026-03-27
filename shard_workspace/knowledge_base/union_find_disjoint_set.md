```markdown
# union find disjoint set — SHARD Cheat Sheet

## Key Concepts
*   **Disjoint Set:** A collection of sets where each element belongs to exactly one set.
*   **Union Find (DSU):** A data structure that efficiently tracks a collection of disjoint sets.
*   **MakeSet(x):** Creates a new set containing only element x.
*   **Find(x):** Returns the representative (or leader) of the set containing element x.
*   **Union(x, y):** Merges the sets containing elements x and y into a single set.
*   **Path Compression:** Optimizes Find by flattening the tree structure, making subsequent Find operations faster.
*   **Union by Rank/Size:** Optimizes Union by attaching the shorter tree to the taller tree, minimizing tree height.
*   **Representative (Leader):** A designated element that represents the entire set.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficiently tracks set membership. | Can be less intuitive to understand than other data structures. |
| Supports fast union and find operations (near-constant time with optimizations). | Not suitable for problems requiring set splitting or element removal. |
| Useful for solving connectivity problems and Kruskal's algorithm. | Space complexity can be O(n) where n is the number of elements. |
| Relatively simple to implement. | Performance heavily relies on path compression and union by rank/size. |

## Practical Example
```python
class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # Path compression
        return self.parent[x]

    def union(self, x, y):
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            if self.rank[root_x] < self.rank[root_y]:
                self.parent[root_x] = root_y
            elif self.rank[root_x] > self.rank[root_y]:
                self.parent[root_y] = root_x
            else:
                self.parent[root_y] = root_x
                self.rank[root_x] += 1

# Example usage:
uf = UnionFind(5)
uf.union(0, 1)
uf.union(2, 3)
print(uf.find(0) == uf.find(1))  # True
print(uf.find(0) == uf.find(2))  # False
uf.union(1, 2)
print(uf.find(0) == uf.find(2))  # True
```

## SHARD's Take
Union Find is a powerful tool for managing disjoint sets and determining connectivity. Its optimized implementations, particularly with path compression and union by rank, provide near-constant time complexity for find and union operations. This makes it indispensable for algorithms like Kruskal's and solving various network-related problems.
```