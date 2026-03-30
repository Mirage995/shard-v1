# Integration of heap data structure and priority queue and implementazione python da zero di un perceptron — SHARD Cheat Sheet

## Key Concepts
*   **Heap:** A tree-based data structure satisfying the heap property: the value of each node is greater than or equal to (in a max-heap) or less than or equal to (in a min-heap) the value of its children.
*   **Priority Queue:** An abstract data type that operates like a queue, but each element has a priority associated with it, and elements are dequeued based on their priority.
*   **Min-Heap:** A heap where the value of each node is less than or equal to the value of its children, making the root the smallest element.
*   **Max-Heap:** A heap where the value of each node is greater than or equal to the value of its children, making the root the largest element.
*   **heapq module:** Python's built-in module for heap-based priority queue implementation.
*   **Perceptron:** A single-layer neural network used for binary classification, learning a linear decision boundary.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient retrieval of highest/lowest priority element (O(1)). | Heap operations (insert, delete) have logarithmic time complexity (O(log n)). |
| `heapq` module provides a simple interface for heap operations in Python. | Implementing a perceptron from scratch requires understanding of linear algebra and gradient descent. |
| Priority queues are versatile for various applications like scheduling and graph algorithms. | Perceptrons are limited to linearly separable data. |

## Practical Example
```python
import heapq

# Priority Queue using heapq (Min-Heap)
class PriorityQueue:
    def __init__(self):
        self._data = []
        self._index = 0  # To handle tie-breaking

    def push(self, item, priority):
        heapq.heappush(self._data, (priority, self._index, item))
        self._index += 1

    def pop(self):
        return heapq.heappop(self._data)[-1]

# Perceptron implementation from scratch
import numpy as np

class Perceptron:
    def __init__(self, learning_rate=0.01, n_iters=1000):
        self.lr = learning_rate
        self.n_iters = n_iters
        self.weights = None
        self.bias = 0

    def fit(self, X, y):
        n_samples, n_features = X.shape
        self.weights = np.zeros(n_features)

        for _ in range(self.n_iters):
            for idx, x_i in enumerate(X):
                linear_output = np.dot(x_i, self.weights) + self.bias
                y_predicted = self.unit_step_func(linear_output)

                update = self.lr * (y[idx] - y_predicted)
                self.weights += update * x_i
                self.bias += update

    def predict(self, X):
        linear_output = np.dot(X, self.weights) + self.bias
        y_predicted = self.unit_step_func(linear_output)
        return y_predicted

    def unit_step_func(self, x):
        return np.where(x>=0, 1, 0)

# Example Usage
if __name__ == '__main__':
    # Priority Queue Example
    pq = PriorityQueue()
    pq.push("Task A", 3)
    pq.push("Task B", 1)
    pq.push("Task C", 2)

    print("Priority Queue:")
    while pq._data:
        print(pq.pop())

    # Perceptron Example
    X = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
    y = np.array([0, 0, 0, 1]) # AND gate

    perceptron = Perceptron()
    perceptron.fit(X, y)
    predictions = perceptron.predict(X)

    print("\nPerceptron Predictions:", predictions)
```

## SHARD's Take
Heaps and priority queues are essential for managing data with varying priorities, and Python's `heapq` module offers a convenient way to implement them. Implementing a perceptron from scratch provides a solid understanding of basic neural network principles, although its limitations should be considered for complex datasets.