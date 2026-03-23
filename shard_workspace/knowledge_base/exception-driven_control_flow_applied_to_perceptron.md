# exception-driven control flow applied to perceptron — SHARD Cheat Sheet

## Key Concepts

- **Exception-Driven Control Flow**: Using exceptions to handle edge cases, errors, or special conditions during perceptron training and inference
- **Perceptron Training Exceptions**: Throwing exceptions when convergence fails, data is non-linearly separable, or numerical instability occurs
- **Validation Exceptions**: Detecting invalid inputs (NaN, infinity, dimension mismatches) and halting execution gracefully
- **Early Stopping via Exceptions**: Using custom exceptions to break training loops when convergence criteria are met or exceeded
- **Gradient Explosion/Vanishing**: Catching numerical overflow/underflow during weight updates in multilayer perceptrons
- **Linear Separability Violation**: Detecting when single-layer perceptron cannot solve the problem (e.g., XOR) and raising appropriate exceptions
- **Bias Initialization Errors**: Handling cases where bias terms cause decision boundary issues
- **Activation Function Domain Errors**: Managing inputs outside valid ranges for activation functions

## Pro & Contro

| Pro | Contro |
|-----|--------|
| Clear separation of error handling from main training logic | Can add performance overhead due to exception handling mechanisms |
| Enables graceful degradation when perceptron encounters unsolvable problems | May obscure control flow if overused, making debugging harder |
| Facilitates early detection of numerical instability (NaN, infinity) | Exception handling can be slower than conditional checks in tight loops |
| Allows for sophisticated convergence monitoring and intervention | Requires careful exception hierarchy design to avoid catching wrong errors |
| Makes code more maintainable by centralizing error conditions | Can lead to "exception-driven programming" anti-pattern if misused |
| Enables automatic fallback strategies (e.g., switch to MLP when SLP fails) | Stack unwinding may lose valuable debugging context |

## Practical Example

```python
class PerceptronConvergenceError(Exception):
    """Raised when perceptron fails to converge within max iterations"""
    pass

class LinearSeparabilityError(Exception):
    """Raised when data is not linearly separable for single-layer perceptron"""
    pass

class NumericalInstabilityError(Exception):
    """Raised when weights or gradients become NaN or infinite"""
    pass

def train_perceptron_with_exceptions(X, y, max_epochs=1000, tolerance=1e-6):
    weights = np.random.randn(X.shape[1])
    bias = 0.0
    
    try:
        for epoch in range(max_epochs):
            errors = 0
            
            for xi, target in zip(X, y):
                # Check for numerical issues
                if np.isnan(weights).any() or np.isinf(weights).any():
                    raise NumericalInstabilityError(
                        f"Weights became unstable at epoch {epoch}: {weights}"
                    )
                
                # Compute prediction
                weighted_sum = np.dot(xi, weights) + bias
                prediction = 1 if weighted_sum >= 0 else 0
                
                # Update weights if misclassified
                if prediction != target:
                    update = (target - prediction)
                    weights += update * xi
                    bias += update
                    errors += 1
            
            # Check convergence
            if errors == 0:
                print(f"Converged at epoch {epoch}")
                return weights, bias
            
            # Check for likely non-linear separability
            if epoch > 100 and errors > len(X) * 0.4:
                raise LinearSeparabilityError(
                    f"High error rate ({errors}/{len(X)}) suggests non-linear data"
                )
        
        # Max iterations reached without convergence
        raise PerceptronConvergenceError(
            f"Failed to converge after {max_epochs} epochs"
        )
    
    except LinearSeparabilityError as e:
        print(f"Caught: {e}")
        print("Falling back to Multilayer Perceptron...")
        return train_mlp_fallback(X, y)
    
    except NumericalInstabilityError as e:
        print(f"Caught: {e}")
        print("Reducing learning rate and reinitializing...")
        return train_perceptron_with_exceptions(X, y, max_epochs)

# Example usage
X_and = np.array([[0,0], [0,1], [1,0], [1,1]])
y_and = np.array([0, 0, 0, 1])
X_xor = np.array([[0,0], [0,1], [1,0], [1,1]])
y_xor = np.array([0, 1, 1, 0])

# AND problem - will converge
weights, bias = train_perceptron_with_exceptions(X_and, y_and)

# XOR problem - will raise LinearSeparabilityError and fallback
weights, bias = train_perceptron_with_exceptions(X_xor, y_xor)
```

## SHARD's Take

Exception-driven control flow in perceptrons provides elegant handling of fundamental limitations like non-linear separability and numerical instability, transforming potential silent failures into explicit, actionable events. This approach is particularly valuable for automated ML pipelines where perceptrons must self-diagnose their applicability and trigger fallback strategies (e.g., switching to MLPs for XOR-like problems). However, the performance cost of exception handling in tight training loops means this pattern should be reserved for epoch-level checks and critical error conditions rather than per-sample validation.

---
*Generated by SHARD Autonomous Learning Engine*