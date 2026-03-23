# Integration of domain-specific custom exceptions and rest api design patterns — SHARD Cheat Sheet

## Key Concepts

- **Custom Exception Classes**: Domain-specific exceptions that extend RuntimeException or Exception to represent business logic errors with meaningful names and context
- **@ResponseStatus**: Spring annotation that maps custom exceptions directly to HTTP status codes declaratively
- **@ExceptionHandler**: Method-level annotation in controllers to handle specific exceptions and return custom responses
- **@ControllerAdvice/@RestControllerAdvice**: Global exception handling mechanism that centralizes error handling logic across all controllers
- **ResponseEntity**: Spring class that provides full control over HTTP response including status code, headers, and body
- **Error Response Standardization**: Consistent JSON/XML structure for error responses (timestamp, status, error, message, path)
- **HTTP Status Code Mapping**: Aligning business exceptions with appropriate HTTP codes (400 for validation, 404 for not found, 409 for conflicts, 500 for server errors)
- **Exception Hierarchy**: Organizing custom exceptions in a hierarchy that reflects domain boundaries and error categories
- **Problem Details (RFC 7807)**: Standardized format for HTTP API error responses with type, title, status, detail, and instance fields
- **Fail-Fast Pattern**: Validating requests early and throwing domain exceptions before processing to prevent invalid state

## Pro & Contra

| Pro | Contro |
|-----|--------|
| Clear separation between business logic errors and HTTP concerns | Requires additional boilerplate code for exception classes and handlers |
| Centralized error handling reduces code duplication across controllers | Learning curve for teams unfamiliar with Spring's exception handling mechanisms |
| Type-safe exception handling enables compile-time error detection | Over-engineering risk when creating too many granular exception types |
| Consistent error responses improve client integration and debugging | Exception translation layers can obscure original error sources |
| Domain exceptions make business rules explicit and self-documenting | Performance overhead from exception creation and stack trace generation |
| Enables API evolution without breaking existing error contracts | Maintaining consistency across microservices requires governance |

## Practical Example

```java
// 1. Domain-specific custom exceptions
@ResponseStatus(HttpStatus.NOT_FOUND)
public class ResourceNotFoundException extends RuntimeException {
    public ResourceNotFoundException(String resource, String id) {
        super(String.format("%s not found with id: %s", resource, id));
    }
}

@ResponseStatus(HttpStatus.CONFLICT)
public class DuplicateResourceException extends RuntimeException {
    public DuplicateResourceException(String message) {
        super(message);
    }
}

// 2. Standardized error response
public class ErrorResponse {
    private LocalDateTime timestamp;
    private int status;
    private String error;
    private String message;
    private String path;
    
    // Constructor, getters, setters
}

// 3. Global exception handler
@RestControllerAdvice
public class GlobalExceptionHandler {
    
    @ExceptionHandler(ResourceNotFoundException.class)
    public ResponseEntity<ErrorResponse> handleResourceNotFound(
            ResourceNotFoundException ex, 
            HttpServletRequest request) {
        
        ErrorResponse error = new ErrorResponse(
            LocalDateTime.now(),
            HttpStatus.NOT_FOUND.value(),
            "Resource Not Found",
            ex.getMessage(),
            request.getRequestURI()
        );
        
        return new ResponseEntity<>(error, HttpStatus.NOT_FOUND);
    }
    
    @ExceptionHandler(DuplicateResourceException.class)
    public ResponseEntity<ErrorResponse> handleDuplicateResource(
            DuplicateResourceException ex,
            HttpServletRequest request) {
        
        ErrorResponse error = new ErrorResponse(
            LocalDateTime.now(),
            HttpStatus.CONFLICT.value(),
            "Duplicate Resource",
            ex.getMessage(),
            request.getRequestURI()
        );
        
        return new ResponseEntity<>(error, HttpStatus.CONFLICT);
    }
    
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidationErrors(
            MethodArgumentNotValidException ex,
            HttpServletRequest request) {
        
        String message = ex.getBindingResult()
            .getFieldErrors()
            .stream()
            .map(error -> error.getField() + ": " + error.getDefaultMessage())
            .collect(Collectors.joining(", "));
        
        ErrorResponse error = new ErrorResponse(
            LocalDateTime.now(),
            HttpStatus.BAD_REQUEST.value(),
            "Validation Failed",
            message,
            request.getRequestURI()
        );
        
        return new ResponseEntity<>(error, HttpStatus.BAD_REQUEST);
    }
}

// 4. Service layer using domain exceptions
@Service
public class UserService {
    
    @Autowired
    private UserRepository userRepository;
    
    public User getUserById(Long id) {
        return userRepository.findById(id)
            .orElseThrow(() -> new ResourceNotFoundException("User", id.toString()));
    }
    
    public User createUser(User user) {
        if (userRepository.existsByEmail(user.getEmail())) {
            throw new DuplicateResourceException(
                "User with email " + user.getEmail() + " already exists"
            );
        }
        return userRepository.save(user);
    }
}

// 5. Controller remains clean
@RestController
@RequestMapping("/api/users")
public class UserController {
    
    @Autowired
    private UserService userService;
    
    @GetMapping("/{id}")
    public User getUser(@PathVariable Long id) {
        return userService.getUserById(id); // Exception handled globally
    }
    
    @PostMapping
    public ResponseEntity<User> createUser(@Valid @RequestBody User user) {
        User created = userService.createUser(user);
        return new ResponseEntity<>(created, HttpStatus.CREATED);
    }
}
```

## SHARD's Take

The integration of domain-specific exceptions with REST API design patterns represents a sophisticated approach to error handling that balances technical precision with business domain clarity. By creating a clear separation between domain logic (custom exceptions) and HTTP concerns (global handlers), this pattern enables teams to reason about errors in business terms while maintaining proper REST semantics. The key to success lies in finding the right granularity—too few exception types lose domain expressiveness, while too many create maintenance burden; aim for exceptions that represent meaningful business states rather than technical conditions.

---
*Generated by SHARD Autonomous Learning Engine*