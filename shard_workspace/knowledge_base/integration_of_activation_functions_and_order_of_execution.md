# Integration of activation functions and order of execution — SHARD Cheat Sheet

## Key Concepts

- **Activation Functions**: Non-linear transformations applied to neuron outputs that enable neural networks to learn complex patterns beyond linear relationships
- **Forward Pass Order**: Input → Linear transformation (weights × inputs + bias) → Activation function → Next layer
- **Backward Pass Order**: Loss gradient → Activation derivative → Weight gradient computation → Previous layer (via chain rule)
- **Layer-wise Execution**: Activation functions execute sequentially per layer during forward propagation, with each layer's output becoming the next layer's input
- **Sigmoid (σ)**: Squashes values to (0,1), typically used in output layers for binary classification; derivative: σ(x)(1-σ(x))
- **ReLU**: max(0,x) - computationally efficient, prevents vanishing gradients in deep networks, commonly used in hidden layers
- **Softmax**: Converts logits to probability distribution for multiclass classification, always used in final layer; requires special handling in backprop
- **Linear/Identity**: f(x)=x, used in regression output layers, no non-linearity introduced
- **Gradient Flow**: Activation function derivatives directly impact how gradients propagate backward; poor choices cause vanishing/exploding gradients
- **Computational Graph**: Execution order follows directed acyclic graph structure where each node computes activation after receiving all inputs

## Pro & Contro

| Pro | Contro |
|-----|--------|
| Non-linear activations enable learning complex, non-linear decision boundaries | Poor activation choice can cause vanishing gradients (sigmoid/tanh in deep networks) |
| ReLU accelerates training with simple computation and sparse activation | ReLU can cause "dying neurons" when outputs become permanently zero |
| Clear execution order (forward then backward) simplifies implementation and debugging | Different activations require different learning rates and initialization strategies |
| Softmax provides interpretable probability outputs for classification | Softmax computation can be numerically unstable without proper normalization |
| Modular design allows mixing different activations per layer based on task requirements | Activation function choice significantly impacts convergence speed and final performance |
| Derivative computation during backprop is local and parallelizable | Some activations (sigmoid) saturate, causing near-zero gradients in extreme ranges |

## Practical Example

```python
import numpy as np

# Forward pass with proper execution order
class NeuralLayer:
    def __init__(self, input_size, output_size, activation='relu'):
        self.W = np.random.randn(input_size, output_size) * 0.01
        self.b = np.zeros((1, output_size))
        self.activation = activation
        
    def forward(self, X):
        # Step 1: Linear transformation
        self.X = X
        self.Z = np.dot(X, self.W) + self.b
        
        # Step 2: Apply activation function
        if self.activation == 'relu':
            self.A = np.maximum(0, self.Z)
        elif self.activation == 'sigmoid':
            self.A = 1 / (1 + np.exp(-self.Z))
        elif self.activation == 'softmax':
            exp_Z = np.exp(self.Z - np.max(self.Z, axis=1, keepdims=True))
            self.A = exp_Z / np.sum(exp_Z, axis=1, keepdims=True)
        else:  # linear
            self.A = self.Z
        return self.A
    
    def backward(self, dA, learning_rate=0.01):
        # Step 1: Compute activation derivative
        if self.activation == 'relu':
            dZ = dA * (self.Z > 0)
        elif self.activation == 'sigmoid':
            sig = self.A
            dZ = dA * sig * (1 - sig)
        else:  # linear or softmax (handled separately)
            dZ = dA
        
        # Step 2: Compute weight gradients
        m = self.X.shape[0]
        dW = np.dot(self.X.T, dZ) / m
        db = np.sum(dZ, axis=0, keepdims=True) / m
        dX = np.dot(dZ, self.W.T)
        
        # Step 3: Update weights
        self.W -= learning_rate * dW
        self.b -= learning_rate * db
        
        return dX

# Example: 3-layer network execution order
X = np.random.randn(100, 784)  # 100 samples, 784 features (MNIST)
layer1 = NeuralLayer(784, 128, 'relu')
layer2 = NeuralLayer(128, 64, 'relu')
layer3 = NeuralLayer(64, 10, 'softmax')

# Forward pass (strict order)
h1 = layer1.forward(X)      # Input → ReLU
h2 = layer2.forward(h1)     # Hidden1 → ReLU
output = layer3.forward(h2) # Hidden2 → Softmax

# Backward pass (reverse order)
dh2 = layer3.backward(output - y_true)  # Start from output
dh1 = layer2.backward(dh2)              # Propagate to hidden2
dx = layer1.backward(dh1)               # Propagate to hidden1
```

## SHARD's Take

The integration of activation functions follows a strict sequential order that mirrors the computational graph structure: forward propagation applies activations layer-by-layer after linear transformations, while backpropagation computes derivatives in exact reverse order using the chain rule. This deterministic execution order is fundamental—violating it breaks gradient flow and prevents learning. The choice of activation function at each layer creates a delicate balance: ReLU in hidden layers for gradient stability and computational efficiency, sigmoid/softmax in output layers for probabilistic interpretation, but each choice constrains the optimization landscape and requires careful consideration of derivative behavior during backpropagation.

---
*Generated by SHARD Autonomous Learning Engine*