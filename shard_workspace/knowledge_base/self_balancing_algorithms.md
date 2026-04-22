# self balancing algorithms -- SHARD Cheat Sheet

## Key Concepts
* Self-Balancing Binary Search Trees: automatically balance the tree after insertion or deletion to maintain search efficiency
* Balancing Factors: measure the balance of a tree, used to determine when to rotate nodes
* Submodular Function Maximization: a technique for optimizing functions with diminishing returns
* Approximation Algorithms: methods for finding near-optimal solutions to complex problems
* Big O Notation: a measure of an algorithm's time and space complexity

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient search and insertion | Increased complexity in implementation |
| Balanced trees reduce search time | Rotation operations can be costly |
| Suitable for large datasets | May require additional memory for balancing |

## Practical Example
```python
class Node:
    def __init__(self, key):
        self.key = key
        self.left = None
        self.right = None
        self.height = 1

class AVLTree:
    def __init__(self):
        self.root = None

    def height(self, node):
        if node is None:
            return 0
        return node.height

    def balance_factor(self, node):
        if node is None:
            return 0
        return self.height(node.left) - self.height(node.right)

    def insert(self, key):
        if self.root is None:
            self.root = Node(key)
        else:
            self.root = self._insert(self.root, key)

    def _insert(self, node, key):
        if key < node.key:
            if node.left is None:
                node.left = Node(key)
            else:
                node.left = self._insert(node.left, key)
        else:
            if node.right is None:
                node.right = Node(key)
            else:
                node.right = self._insert(node.right, key)

        node.height = 1 + max(self.height(node.left), self.height(node.right))
        balance = self.balance_factor(node)

        if balance > 1:
            if key < node.left.key:
                return self.right_rotate(node)
            else:
                node.left = self.left_rotate(node.left)
                return self.right_rotate(node)
        if balance < -1:
            if key > node.right.key:
                return self.left_rotate(node)
            else:
                node.right = self.right_rotate(node.right)
                return self.left_rotate(node)

        return node

    def left_rotate(self, z):
        y = z.right
        T2 = y.left
        y.left = z
        z.right = T2
        z.height = 1 + max(self.height(z.left), self.height(z.right))
        y.height = 1 + max(self.height(y.left), self.height(y.right))
        return y

    def right_rotate(self, z):
        y = z.left
        T3 = y.right
        y.right = z
        z.left = T3
        z.height = 1 + max(self.height(z.left), self.height(z.right))
        y.height = 1 + max(self.height(y.left), self.height(y.right))
        return y

# Example usage:
tree = AVLTree()
tree.insert(5)
tree.insert(3)
tree.insert(7)
tree.insert(2)
tree.insert(4)
tree.insert(6)
tree.insert(8)
```

## SHARD's Take
Balancing time and space complexity is crucial for efficient software development, and self-balancing algorithms like AVL trees can help achieve this balance. However, implementing these algorithms can be complex and may require additional memory and computational resources. By understanding the trade-offs and limitations of self-balancing algorithms, developers can make informed decisions about when to use them in their applications.