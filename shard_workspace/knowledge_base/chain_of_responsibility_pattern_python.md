# chain of responsibility pattern python -- SHARD Cheat Sheet

## Key Concepts
* Chain of Responsibility: a design pattern that allows an object to pass a request to a series of handlers, each of which can choose to handle the request or pass it to the next handler.
* Handler: an object that can handle a request or pass it to the next handler in the chain.
* Request: an object that represents the request being handled by the chain of responsibility.
* Client: an object that initiates the request and sends it to the first handler in the chain.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Decouples the sender and receiver of a request | Can lead to complex chains of handlers |
| Allows for flexible and dynamic handling of requests | Can make it difficult to debug and test the chain |
| Enables multiple handlers to handle a single request | Can lead to performance issues if the chain is too long |

## Practical Example
```python
from abc import ABC, abstractmethod

class Handler(ABC):
    @abstractmethod
    def set_next(self, handler):
        pass

    @abstractmethod
    def handle(self, request):
        pass

class ConcreteHandler(Handler):
    def __init__(self):
        self.next_handler = None

    def set_next(self, handler):
        self.next_handler = handler

    def handle(self, request):
        if self.next_handler:
            return self.next_handler.handle(request)
        return None

class RequestHandler(ConcreteHandler):
    def handle(self, request):
        if request == "specific_request":
            return "Handling specific request"
        return super().handle(request)

class Client:
    def __init__(self, handler):
        self.handler = handler

    def send_request(self, request):
        return self.handler.handle(request)

# Create handlers
handler1 = RequestHandler()
handler2 = RequestHandler()

# Set next handler in chain
handler1.set_next(handler2)

# Create client and send request
client = Client(handler1)
print(client.send_request("specific_request"))
```

## SHARD's Take
The Chain of Responsibility pattern is a powerful tool for handling complex requests in a flexible and dynamic way. However, it requires careful consideration of the trade-offs between decoupling, flexibility, and performance. By using this pattern, developers can create robust and scalable systems that can handle a wide range of requests and scenarios.