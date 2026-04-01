# Integration of @responsestatus annotation and setter injection -- SHARD Cheat Sheet

## Key Concepts
*   **@ResponseStatus**:  Annotation in Spring MVC to specify the HTTP status code for a controller method or exception handler.
*   **Setter Injection**: A type of dependency injection where dependencies are injected via setter methods.
*   **Dependency Injection (DI)**: A design pattern that allows for loose coupling of software components.
*   **HTTP Status Codes**: Standard codes indicating the result of an HTTP request (e.g., 200 OK, 404 Not Found).
*   **Exception Handling**: Mechanisms to manage and respond to errors during program execution.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Simplifies setting HTTP status codes for specific scenarios. |  Annotations are compile-time constants, so dynamic values from setter injection cannot directly populate `@ResponseStatus`. |
|  Centralized exception handling with specific status codes. | Requires careful design to avoid conflicts between annotation-based and programmatically set status codes. |
| Improves code readability by declaring status codes directly in the controller. | Can lead to less flexible status code assignment if complex logic is needed. |

## Practical Example

```java
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.stereotype.Component;

@Component
public class ErrorConfig {
    private HttpStatus notFoundStatus = HttpStatus.NOT_FOUND;

    public void setNotFoundStatus(HttpStatus notFoundStatus) {
        this.notFoundStatus = notFoundStatus;
    }

    public HttpStatus getNotFoundStatus() {
        return this.notFoundStatus;
    }
}

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class MyController {

    @Autowired
    private ErrorConfig errorConfig;

    @GetMapping("/items/{id}")
    public String getItem(@PathVariable String id) {
        if ("invalid".equals(id)) {
            throw new ResponseStatusException(errorConfig.getNotFoundStatus(), "Item not found");
        }
        return "Item: " + id;
    }
}
```

## SHARD's Take
Directly injecting values into `@ResponseStatus` is not possible due to its compile-time nature. Instead, use setter injection to configure a bean with the desired status code, and then use that bean within a `ResponseStatusException` to dynamically set the HTTP status. This approach provides flexibility while adhering to the intended use of `@ResponseStatus`.