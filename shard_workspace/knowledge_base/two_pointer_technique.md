# two pointer technique — SHARD Cheat Sheet

## Key Concepts
*   **Two Pointers:** Using two index variables to traverse a data structure (usually an array or linked list) simultaneously.
*   **Left & Right Pointers:** One pointer starts from the beginning, and the other from the end, moving towards each other.
*   **Fast & Slow Pointers:** One pointer moves faster than the other, useful for cycle detection.
*   **Sliding Window:** A technique using two pointers to define a "window" that moves across the data.
*   **Sorted Data:** Two pointers are particularly effective when the data is sorted, enabling efficient searching and comparison.

## Pro & Contro
| Pro                                                        | Contro                                                                 |
| :--------------------------------------------------------- | :--------------------------------------------------------------------- |
| Efficient: Reduces time complexity from O(n^2) to O(n).    | Requires sorted data or specific problem structures for optimal use. |
| Space Efficient: Often operates in-place, minimizing memory usage. | Can be tricky to implement correctly, especially with edge cases. |
| Versatile: Applicable to various problems like searching, sorting, and string manipulation. | Not suitable for all problems; may not be the most intuitive approach for some. |

## Practical Example
```python
def two_sum_sorted(nums, target):
    """Finds two numbers in a sorted array that add up to the target."""
    left, right = 0, len(nums) - 1
    while left < right:
        current_sum = nums[left] + nums[right]
        if current_sum == target:
            return [left, right]
        elif current_sum < target:
            left += 1
        else:
            right -= 1
    return None  # No such pair found

# Example usage:
nums = [2, 7, 11, 15]
target = 9
result = two_sum_sorted(nums, target)
print(f"Indices: {result}") # Output: Indices: [0, 1]
```

## SHARD's Take
The two-pointer technique is a powerful optimization strategy for array and string manipulation, especially when dealing with sorted data. Understanding its variations, like fast/slow pointers and sliding windows, allows for efficient problem-solving. However, it's crucial to recognize its limitations and choose the appropriate technique based on the problem's constraints.