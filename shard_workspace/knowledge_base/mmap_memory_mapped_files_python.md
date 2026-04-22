# mmap memory mapped files python -- SHARD Cheat Sheet

## Key Concepts
* Memory-mapped files: a way to map a file on disk to a region of memory, allowing for efficient access and manipulation of large files
* `mmap` module: a Python module that provides an interface to memory-mapped files
* File descriptor: a small integer that represents an open file, used to create a memory map
* Memory map modes: read-only (`mmap.ACCESS_READ`), read-write (`mmap.ACCESS_WRITE`), and copy-on-write (`mmap.ACCESS_COPY`)

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient data processing | Limited control over memory management |
| Simulating large datasets | Potential for memory leaks if not used carefully |
| Reducing memory usage | Requires careful handling of file descriptors and memory maps |

## Practical Example
```python
import mmap
import os

# Create a sample file
with open('sample.txt', 'wb') as f:
    f.write(b'Hello, world!')

# Open the file and create a memory map
with open('sample.txt', 'rb') as f:
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

# Read from the memory map
print(mm.read())

# Close the memory map
mm.close()

# Remove the sample file
os.remove('sample.txt')
```

## SHARD's Take
Mastering `mmap` memory-mapped files in Python is crucial for efficient data processing and simulating large datasets. However, it requires careful handling of file descriptors and memory maps to avoid memory leaks. With practice and experience, developers can harness the power of `mmap` to optimize their code's performance and reduce memory usage.