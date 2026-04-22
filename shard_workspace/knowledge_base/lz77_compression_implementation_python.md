# lz77 compression implementation python -- SHARD Cheat Sheet

## Key Concepts
* LZ77 compression algorithm: a lossless compression technique that replaces repeated patterns in data with a reference to the previous occurrence
* Sliding window: a buffer that stores the most recently processed data, used to find repeated patterns
* Dictionary: a data structure that stores the locations of previously seen patterns, used to compress data
* String matching: the process of finding repeated patterns in data, used in LZ77 compression

## Pro & Contro
| Pro | Contro |
|-----|--------|
| High compression ratio | Complex implementation |
| Fast compression and decompression | Limited to compressing sequential data |
| Simple to understand | Not suitable for compressing random or encrypted data |

## Practical Example
```python
def lz77_compress(data):
    compressed = []
    window_size = 4096
    window = ""

    for i in range(len(data)):
        for j in range(min(window_size, i), 0, -1):
            if data[i-j:i] in window:
                compressed.append((j, data[i]))
                break
        else:
            compressed.append((0, data[i]))
        window += data[i]
        if len(window) > window_size:
            window = window[1:]

    return compressed

def lz77_decompress(compressed):
    decompressed = ""
    for length, char in compressed:
        if length > 0:
            decompressed += decompressed[-length] + char
        else:
            decompressed += char
    return decompressed

# Example usage:
data = "ABCABCABC"
compressed = lz77_compress(data)
print(compressed)
decompressed = lz77_decompress(compressed)
print(decompressed)
```

## SHARD's Take
The LZ77 compression algorithm is a simple yet effective technique for compressing sequential data. While it has a high compression ratio and fast compression and decompression times, its implementation can be complex and it is limited to compressing sequential data. With practice and experience, developers can master the LZ77 compression algorithm and apply it to a variety of real-world applications.