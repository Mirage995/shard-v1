# bloom filter probabilistic membership python -- SHARD Cheat Sheet

## Key Concepts
* Bloom Filter: a space-efficient probabilistic data structure used to test whether an element is a member of a set
* Hash Functions: used to map elements to indices in the Bloom filter
* False Positive Rate: the probability of a false positive result
* False Negative Rate: the probability of a false negative result, which is zero for Bloom filters
* Probability Theory: underlying mathematical framework for Bloom filters

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Space-efficient | False positives possible |
| Fast lookup and insertion | Requires careful choice of hash functions and size |
| Suitable for large-scale data applications | Not suitable for applications requiring exact membership testing |

## Practical Example
```python
import mmh3
from bitarray import bitarray

class BloomFilter:
    def __init__(self, size, hash_functions):
        self.size = size
        self.hash_functions = hash_functions
        self.bit_array = bitarray(size)
        self.bit_array.setall(0)

    def add(self, element):
        for seed in range(self.hash_functions):
            index = mmh3.hash(element, seed) % self.size
            self.bit_array[index] = 1

    def lookup(self, element):
        for seed in range(self.hash_functions):
            index = mmh3.hash(element, seed) % self.size
            if self.bit_array[index] == 0:
                return False
        return True

# Example usage:
bf = BloomFilter(100, 5)
bf.add("apple")
print(bf.lookup("apple"))  # True
print(bf.lookup("banana"))  # False
```

## SHARD's Take
The Bloom filter is a powerful probabilistic data structure for efficient approximate membership testing, but its effectiveness relies on careful tuning of parameters and hash functions. Mastering Bloom filters and their variants requires a deep understanding of the underlying probability theory and hash functions. With proper implementation, Bloom filters can be a valuable tool in large-scale data applications.