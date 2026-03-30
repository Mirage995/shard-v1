# git internals object model — SHARD Cheat Sheet

## Key Concepts
*   **Blob:** Represents the content of a file.
*   **Tree:** Represents a directory, containing blobs and other trees.
*   **Commit:** Represents a snapshot of the repository at a specific point in time.
*   **SHA-1 Hashing:** Used to uniquely identify each object based on its content.
*   **Content-Addressable Filesystem:** Stores objects based on their SHA-1 hash.
*   **Packfile:** A compressed archive containing multiple objects.
*   **Delta Compression:** Stores objects as differences from other objects to save space.
*   **Directed Acyclic Graph (DAG):** Represents the commit history.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient storage through content-addressing and delta compression. | Can be complex to understand and debug. |
| Data integrity ensured by SHA-1 hashing. | Requires familiarity with low-level concepts. |
| Enables powerful version control features like branching and merging. |  Direct manipulation of objects is generally discouraged. |

## Practical Example
```python
import hashlib
import zlib

# Create a blob object
content = b"This is the content of my file."
header = f"blob {len(content)}\0".encode('utf-8')
store = header + content
sha1_hash = hashlib.sha1(store).hexdigest()

# Simulate object storage (in-memory)
object_store = {sha1_hash: zlib.compress(store)}

print(f"Blob hash: {sha1_hash}")
```

## SHARD's Take
Understanding Git's object model provides valuable insights into how Git manages and stores data, enabling more effective troubleshooting and custom scripting. While direct manipulation is rarely necessary, grasping the underlying principles empowers developers to better utilize Git's features and optimize repository performance.