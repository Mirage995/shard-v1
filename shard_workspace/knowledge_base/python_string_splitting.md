# python string splitting -- SHARD Cheat Sheet

## Key Concepts
* `split()`: splits a string into a list where each word is a list item
* `rsplit()`: splits a string into a list where each word is a list item, starting from the right
* `splitlines()`: splits a string into a list where each line is a list item
* `partition()`: splits a string into a list containing three items: the part before the separator, the separator, and the part after the separator
* `strip()`: removes leading and trailing characters (spaces are default) from a string

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Easy to use and understand | May not work correctly with punctuation next to words |
| Fast and efficient | Does not handle multiple separators well |
| Built-in Python function | May not work as expected with non-string inputs |

## Practical Example
```python
my_string = "hello,world,this,is,a,test"
split_string = my_string.split(",")
print(split_string)  # Output: ['hello', 'world', 'this', 'is', 'a', 'test']
```

## SHARD's Take
Mastering Python string splitting is essential for any data processing or text analysis task, as it allows for efficient and easy manipulation of strings. However, it's crucial to consider the limitations and potential pitfalls of each splitting method to ensure correct results. With practice and experience, developers can effectively utilize these methods to achieve their goals.