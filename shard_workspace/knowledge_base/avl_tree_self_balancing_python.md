# avl tree self balancing python -- SHARD Cheat Sheet

## Key Concepts
* AVL Tree: A self-balancing binary search tree that ensures the height of the tree remains relatively small by rotating nodes when the balance factor becomes too large.
* Balance Factor: A measure of the balance of a node in the tree, calculated as the height of the left subtree minus the height of the right subtree.
* Rotation Operations: Left and right rotations are used to balance the tree when the balance factor becomes too large.
* Amortized Rotation Cost: The average cost of rotation operations over a sequence of insertions and deletions.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Ensures efficient search, insertion, and deletion operations | Increased complexity due to self-balancing mechanism |
| Maintains a balanced tree, reducing the risk of worst-case scenarios | Higher overhead due to rotation operations |
| Suitable for applications with frequent insertions and deletions | May not be the best choice for applications with infrequent updates |

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

    def insert(self, key):
        self.root = self._insert(self.root, key)

    def _insert(self, node, key):
        if not node:
            return Node(key)
        elif key < node.key:
            node.left = self._insert(node.left, key)
        else:
            node.right = self._insert(node.right, key)

        node.height = 1 + max(self._height(node.left), self._height(node.right))
        balance = self._balance(node)

        if balance > 1 and key < node.left.key:
            return self._right_rotate(node)
        if balance < -1 and key > node.right.key:
            return self._left_rotate(node)
        if balance > 1 and key > node.left.key:
            node.left = self._left_rotate(node.left)
            return self._right_rotate(node)
        if balance < -1 and key < node.right.key:
            node.right = self._right_rotate(node.right)
            return self._left_rotate(node)

        return node

    def _height(self, node):
        if not node:
            return 0
        return node.height

    def _balance(self, node):
        if not node:
            return 0
        return self._height(node.left) - self._height(node.right)

    def _left_rotate(self, node):
        temp = node.right
        node.right = temp.left
        temp.left = node

        node.height = 1 + max(self._height(node.left), self._height(node.right))
        temp.height = 1 + max(self._height(temp.left), self._height(temp.right))

        return temp

    def _right_rotate(self, node):
        temp = node.left
        node.left = temp.right
        temp.right = node

        node.height = 1 + max(self._height(node.left), self._height(node.right))
        temp.height = 1 + max(self._height(temp.left), self._height(temp.right))

        return temp

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
Understanding the amortized rotation cost in AVL trees is crucial for optimizing database query performance. The self-balancing mechanism ensures efficient search, insertion, and deletion operations, but may introduce additional complexity. By leveraging AVL trees, developers can create scalable and efficient data storage solutions.