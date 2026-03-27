```markdown
# async io with python selectors — SHARD Cheat Sheet

## Key Concepts
*   **Event Loop:** The core of `asyncio`, managing asynchronous tasks and callbacks.
*   **Selectors:** Allow monitoring multiple file descriptors (sockets, files) for I/O readiness.
*   **Non-blocking I/O:** Operations that don't wait for completion, allowing other tasks to run.
*   **Callbacks:** Functions executed when an I/O operation is ready.
*   **async/await:** Keywords for defining and using coroutines for asynchronous programming.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Efficient handling of concurrent I/O operations. | More complex than traditional synchronous code. |
| Improved performance for I/O-bound applications. | Requires careful management of state and context. |
| Enables highly scalable network applications. | Can be harder to debug. |

## Practical Example
```python
import selectors
import socket

sel = selectors.DefaultSelector()

def accept(sock, mask):
    conn, addr = sock.accept()  # Should be ready
    print('accepted connection from', addr)
    conn.setblocking(False)
    sel.register(conn, selectors.EVENT_READ, read)

def read(conn, mask):
    try:
        data = conn.recv(1000)  # Should be ready
    except BlockingIOError:
        pass
    else:
        if data:
            print('received', repr(data), 'from', conn.getpeername())
            conn.send(data)  # Hope it won't block
        else:
            print('closing connection', conn.getpeername())
            sel.unregister(conn)
            conn.close()

sock = socket.socket()
sock.bind(('localhost', 1234))
sock.listen(100)
sock.setblocking(False)
sel.register(sock, selectors.EVENT_READ, accept)

while True:
    events = sel.select()
    for key, mask in events:
        callback = key.data
        callback(key.fileobj, mask)
```

## SHARD's Take
Using selectors directly provides fine-grained control over I/O multiplexing, but it's more verbose than higher-level `asyncio` APIs. This approach is beneficial when you need precise control over event loop behavior or when integrating with existing code that uses sockets directly.
```