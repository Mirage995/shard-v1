# neural network backpropagation python — SHARD Cheat Sheet

## Key Concepts
*   **Neural Network:** A computational model inspired by the structure and function of biological neural networks.
*   **Backpropagation:** An algorithm for training neural networks by iteratively adjusting the weights based on the error between predicted and actual outputs.
*   **Forward Propagation:** The process of feeding input data through the network to generate a prediction.
*   **Loss Function:** A function that quantifies the difference between the network's predictions and the actual target values.
*   **Gradient Descent:** An optimization algorithm used to minimize the loss function by iteratively adjusting the network's weights in the direction of the negative gradient.
*   **Activation Function:** A function applied to the output of each neuron to introduce non-linearity into the network.
*   **Weights:** Parameters that determine the strength of the connections between neurons.
*   **Learning Rate:** A hyperparameter that controls the step size during gradient descent.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Enables training of complex neural networks. | Can be computationally expensive. |
| Automates weight adjustment for optimal performance. | Sensitive to hyperparameter tuning (learning rate, etc.). |
| Foundation for many deep learning applications. | Prone to getting stuck in local minima. |

## Practical Example
```python
import numpy as np

# Simple example: one input, one output, one weight
def sigmoid(x):
  return 1 / (1 + np.exp(-x))

def sigmoid_derivative(x):
  return x * (1 - x)

# Input and output data
X = np.array([[0.1]])
y = np.array([[0.9]])

# Initialize weight
weight = 0.5

# Learning rate
learning_rate = 0.1

# Forward propagation
input_layer = X
weighted_sum = input_layer * weight
output_layer = sigmoid(weighted_sum)

# Calculate loss
error = y - output_layer

# Backpropagation
d_output = error * sigmoid_derivative(output_layer)
d_weight = input_layer * d_output

# Update weight
weight += learning_rate * d_weight

print("Updated weight:", weight)
```

## SHARD's Take
Backpropagation, while mathematically involved, is essential for training neural networks. A clear understanding of the chain rule and gradient descent is crucial for implementing it correctly. Start with simple examples and gradually increase complexity to avoid common pitfalls.