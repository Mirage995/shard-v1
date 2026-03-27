# trie data structure — SHARD Cheat Sheet

## Key Concepts
*   **Trie (Prefix Tree):** A tree-like data structure used for efficient retrieval of strings based on prefixes.
*   **Node:** Each node in a trie represents a character, and the path from the root to a node represents a prefix.
*   **Root Node:** The top-most node in the trie, representing an empty string.
*   **Children:** Each node can have multiple children, each representing a different character.
*   **End of Word:** A flag indicating that a node represents the end of a valid word.
*   **Prefix Search:** Tries are optimized for searching words by their prefixes.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient prefix-based search (autocomplete, spell checking). | Can be space-inefficient, especially with large alphabets or long strings. |
| Fast retrieval of words with a common prefix. | Insertion and deletion can be complex. |
| Supports ordered traversal of words. | Not suitable for all types of string searching. |

## Practical Example
```python
class TrieNode:
    def __init__(self):
        self.children = {}
        self.is_end_of_word = False

class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word):
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end_of_word = True

    def search(self, word):
        node = self.root
        for char in word:
            if char not in node.children:
                return False
            node = node.children[char]
        return node.is_end_of_word

    def starts_with(self, prefix):
        node = self.root
        for char in prefix:
            if char not in node.children:
                return False
            node = node.children[char]
        return True

# Example Usage
trie = Trie()
trie.insert("apple")
print(trie.search("apple"))   # True
print(trie.search("app"))     # False
print(trie.starts_with("app")) # True
```

## SHARD's Take
Tries excel in scenarios requiring prefix-based searches, offering significant speed advantages over other data structures. However, the memory overhead associated with storing each character in a separate node must be carefully considered. The trade-off between speed and space is crucial when deciding whether to implement a trie.