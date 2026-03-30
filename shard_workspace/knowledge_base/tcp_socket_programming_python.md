# tcp socket programming python — SHARD Cheat Sheet

## Key Concepts
*   **Socket:** An endpoint for network communication.
*   **TCP (Transmission Control Protocol):** A reliable, connection-oriented protocol.
*   **IP Address:** A numerical label assigned to each device participating in a computer network.
*   **Port:** A virtual point where network connections start and end.
*   **Server:** A program that listens for incoming connections.
*   **Client:** A program that initiates a connection to a server.
*   **`socket.socket()`:** Creates a new socket object.
*   **`socket.bind()`:** Assigns a socket to a specific address and port.
*   **`socket.listen()`:** Enables a server socket to accept connections.
*   **`socket.connect()`:** Establishes a connection to a server.
*   **`socket.sendall()`:** Sends data through the socket.
*   **`socket.recv()`:** Receives data from the socket.
*   **`socket.close()`:** Closes the socket connection.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Reliable, ordered data transfer | More overhead than UDP |
| Connection-oriented, ensuring data delivery | Requires connection establishment and teardown |
| Widely supported and used | Can be more complex to implement than UDP |

## Practical Example

```python
import socket

# Server
def server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('localhost', 12345))
    s.listen(1)
    conn, addr = s.accept()
    with conn:
        print('Connected by', addr)
        while True:
            data = conn.recv(1024)
            if not data:
                break
            conn.sendall(data)
    s.close()

# Client
def client():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('localhost', 12345))
    s.sendall(b'Hello, server!')
    data = s.recv(1024)
    print('Received', repr(data))
    s.close()

if __name__ == "__main__":
    import threading
    server_thread = threading.Thread(target=server)
    server_thread.daemon = True # Allow main thread to exit even if server is running
    server_thread.start()

    client()
```

## SHARD's Take
TCP sockets provide a reliable way to establish network communication in Python. Understanding the core functions like `bind`, `listen`, `connect`, `sendall`, and `recv` is crucial for building client-server applications. Proper error handling and resource management (closing sockets) are essential for robust applications.