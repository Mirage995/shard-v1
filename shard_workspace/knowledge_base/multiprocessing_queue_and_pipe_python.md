# multiprocessing queue and pipe python -- SHARD Cheat Sheet

## Key Concepts
* Multiprocessing Queue: a First-In-First-Out (FIFO) data structure for inter-process communication
* Multiprocessing Pipe: a unidirectional or bidirectional pipe for inter-process communication
* ProcessPoolExecutor: a class for parallel execution of callables using multiple processes
* Queue objects sharing: sharing Queue objects between processes using inheritance or inter-process communication

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient parallel processing | Complexity of inter-process communication and synchronization |
| Improved responsiveness | Increased memory usage due to multiple processes |
| Scalability | Difficulty in debugging and testing |

## Practical Example
```python
import multiprocessing
import time

def worker(queue):
    queue.put("Message from worker")

if __name__ == '__main__':
    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=worker, args=(queue,))
    process.start()
    print(queue.get())
    process.join()
```

## SHARD's Take
Mastering multiprocessing and process pools in Python is crucial for efficient parallel processing, but it can be challenging due to the complexity of inter-process communication and synchronization. Understanding the differences between multiprocessing Queue and Pipe, as well as how to properly share Queue objects between processes, is essential for effective use of these tools. By leveraging these concepts, developers can write more efficient and scalable code.