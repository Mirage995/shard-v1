# tcp socket programming python — SHARD Cheat Sheet

## Key Concepts
*   **Socket:** An endpoint of a two-way communication link between two programs running on the network.
*   **TCP (Transmission Control Protocol):** A connection-oriented protocol that provides reliable, ordered, and error-checked delivery of a stream of bytes.
*   **IP Address:** A numerical label assigned to each device participating in a computer network that uses the Internet Protocol for communication.
*   **Port:** A virtual point where network connections start and end.
*   **AF_INET:** An address family that is used to designate the type of addresses that the socket can communicate with (IPv4).
*   **SOCK_STREAM:** A socket type that provides sequenced, reliable, two-way, connection-based byte streams (TCP).
*   **s.bind():** Assigns a local address to a socket.
*   **s.listen():** Enables a server to accept connections.
*   **s.accept():** Accepts a connection, returning a new socket object usable for sending and receiving data on the connection.
*   **s.connect():** Initiates a connection to a remote socket.
*   **s.send():** Sends data to the socket.
*   **s.recv():** Receives data from the socket.
*   **s.close():** Closes the socket.
*   **Encoding/Decoding:** Converting strings to bytes (encoding) and bytes to strings (decoding) for network transmission.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Reliable, ordered data transfer | More overhead than UDP |
| Connection-oriented, ensuring data integrity | Slower due to connection establishment and error checking |
| Widely supported and used | Can be complex to implement error handling correctly |

## Practical Example
```python
import socket

# Server
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('localhost', 12345))
s.listen(1)
conn, addr = s.accept()
data = conn.recv(1024)
print(f"Received: {data.decode()}")
conn.sendall("Hello, Client!".encode())
conn.close()
s.close()

# Client
c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
c.connect(('localhost', 12345))
c.sendall("Hello, Server!".encode())
data = c.recv(1024)
print(f"Received: {data.decode()}")
c.close()
```

## SHARD's Take
TCP sockets are a cornerstone of reliable network communication in Python, offering guaranteed delivery and order. However, developers must pay close attention to encoding/decoding data correctly and handling potential connection errors to build robust applications. Understanding the underlying protocol is crucial for effective debugging and optimization.