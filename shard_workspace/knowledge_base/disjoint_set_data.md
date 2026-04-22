# disjoint set data -- SHARD Cheat Sheet

## Key Concepts
* Disjoint-set data structure: a data structure that keeps track of a set of elements partitioned into a number of non-overlapping (or disjoint) subsets.
* Union operation: merges two subsets into a single subset.
* Find operation: determines the subset to which a particular element belongs.
* Path compression: an optimization technique used to reduce the time complexity of the find operation.
* Union by rank: an optimization technique used to reduce the time complexity of the union operation.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient union and find operations | Can be complex to implement |
| Useful in various applications such as Kruskal's algorithm and network connectivity | May require additional memory to store the disjoint sets |
| Can be optimized using path compression and union by rank | May have a high time complexity if not implemented correctly |

## Practical Example
```python
class DisjointSet:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            if self.rank[root_x] > self.rank[root_y]:
                self.parent[root_y] = root_x
            elif self.rank[root_x] < self.rank[root_y]:
                self.parent[root_x] = root_y
            else:
                self.parent[root_y] = root_x
                self.rank[root_x] += 1

# Example usage:
ds = DisjointSet(5)
ds.union(0, 1)
ds.union(1, 2)
print(ds.find(0) == ds.find(2))  # Output: True
```

## SHARD's Take
The disjoint set data structure is a powerful tool for solving problems that involve partitioning a set of elements into non-overlapping subsets. With its efficient union and find operations, it has numerous applications in computer science. However, its implementation can be complex and requires careful consideration of optimization techniques such as path compression and union by rank.