```markdown
# neural network backpropagation python — SHARD Cheat Sheet

## Key Concepts
*   **Neural Network:** A computational model inspired by the structure and function of biological neural networks.
*   **Forward Pass:** The process of feeding input data through the network to generate a prediction.
*   **Loss Function:** A function that quantifies the difference between the predicted output and the actual target.
*   **Backward Pass (Backpropagation):** The process of calculating gradients of the loss function with respect to the network's weights and biases.
*   **Gradient Descent:** An optimization algorithm used to update the weights and biases to minimize the loss function.
*   **Weights:** Parameters in a neural network that determine the strength of connections between neurons.
*   **Biases:** Parameters in a neural network that allow for shifting the activation function.
*   **Activation Function:** Introduces non-linearity, enabling the network to learn complex patterns.
*   **Chain Rule:** Used to calculate gradients through multiple layers in backpropagation.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Enables learning complex patterns. | Can be computationally expensive. |
| Automates feature extraction. | Prone to vanishing/exploding gradients. |
| Highly adaptable to various tasks. | Requires careful hyperparameter tuning. |

## Practical Example

```python
import numpy as np

# Simple example: one input, one output, one layer
def sigmoid(x):
  return 1 / (1 + np.exp(-x))

def sigmoid_derivative(x):
  return x * (1 - x)

# Input and output
X = np.array([[0.1]])
y = np.array([[0.9]])

# Initialize weights and bias
weight = np.array([[0.5]])
bias = 0.1

# Learning rate
learning_rate = 0.1

# Forward pass
z = np.dot(X, weight) + bias
a = sigmoid(z)

# Loss (Mean Squared Error)
loss = np.mean((a - y)**2)

# Backward pass
d_loss_a = 2 * (a - y)
d_a_z = sigmoid_derivative(a)
d_z_weight = X
d_loss_weight = d_loss_a * d_a_z * d_z_weight

d_z_bias = 1
d_loss_bias = d_loss_a * d_a_z * d_z_bias

# Update weights and bias
weight = weight - learning_rate * d_loss_weight
bias = bias - learning_rate * d_loss_bias

print("Updated weight:", weight)
print("Updated bias:", bias)
```

## SHARD's Take
Backpropagation, while complex, is the engine that drives learning in neural networks. Understanding the flow of gradients and the role of each component is essential for effective model training. Start with simple examples and gradually increase complexity to master this fundamental concept.
```