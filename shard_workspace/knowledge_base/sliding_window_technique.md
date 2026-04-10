# sliding window technique -- SHARD Cheat Sheet

## Key Concepts
* Sliding Window Technique: an algorithmic approach to optimize time complexity by dividing the data into subarrays or substrings and processing them in a window-like manner.
* Fixed-Size Window: a type of sliding window with a fixed size, used to solve problems like finding the maximum sum of subarray with K elements.
* Dynamic-Size Window: a type of sliding window with a variable size, used to solve problems like finding the longest substring with unique characters.
* Window Boundaries: the start and end indices of the sliding window, which need to be carefully managed to handle edge cases.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Optimizes time complexity | Can be challenging to implement, especially for dynamic-size windows |
| Reduces the need for redundant calculations | Requires careful management of window boundaries |
| Can be applied to various problems, including array and string processing | May not be suitable for all types of problems, such as those with complex dependencies |

## Practical Example
```python
def max_sum_subarray(arr, k):
    """
    Find the maximum sum of subarray with K elements using the sliding window technique.
    """
    if not arr or k == 0:
        return 0
    
    window_sum = sum(arr[:k])
    max_sum = window_sum
    
    for i in range(k, len(arr)):
        window_sum = window_sum - arr[i - k] + arr[i]
        max_sum = max(max_sum, window_sum)
    
    return max_sum

# Example usage:
arr = [1, 2, 3, 4, 5]
k = 3
print(max_sum_subarray(arr, k))  # Output: 12
```

## SHARD's Take
The sliding window technique is a powerful algorithmic approach that can significantly optimize time complexity, but its implementation can be challenging due to the need to carefully manage the window boundaries and handle edge cases. By mastering the sliding window technique, developers can solve a wide range of problems efficiently and effectively. With practice and experience, the technique can become a valuable tool in any developer's toolkit.