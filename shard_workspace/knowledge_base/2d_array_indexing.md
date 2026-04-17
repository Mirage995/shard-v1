# 2D array indexing -- SHARD Cheat Sheet

## Key Concepts
* Row-major ordering: a method of storing 2D arrays in memory where elements from the same row are stored contiguously
* Column-major ordering: a method of storing 2D arrays in memory where elements from the same column are stored contiguously
* Indexing notation: a way of accessing elements in a 2D array using row and column indices
* Boundary checking: a technique to prevent index out-of-bounds errors when accessing elements in a 2D array

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient memory usage | Difficulty in implementing boundary checking |
| Fast access times | Complexity in indexing notation |
| Simple to implement | Limited to fixed-size arrays |

## Practical Example
```python
# Initialize a 2D array
array_2d = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]

# Access an element using row and column indices
print(array_2d[1][2])  # Output: 6

# Modify an element using row and column indices
array_2d[1][2] = 10
print(array_2d[1][2])  # Output: 10
```

## SHARD's Take
2D array indexing is a fundamental concept in computer science, and understanding the trade-offs between different indexing methods is crucial for efficient programming. By mastering row-major and column-major ordering, developers can optimize their code for performance and readability. With practice and experience, indexing notation and boundary checking become second nature, enabling developers to tackle complex problems with confidence.