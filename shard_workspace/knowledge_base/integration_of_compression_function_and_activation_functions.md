# Integration of compression function and activation functions — SHARD Cheat Sheet

## Key Concepts
*   **Activation Function:** A function that introduces non-linearity to the output of a neuron.
*   **Compression Function:** A function that reduces the size or complexity of data.
*   **ReLU:** A simple activation function that outputs the input directly if it is positive, otherwise, it outputs zero.
*   **Sigmoid:** An activation function that outputs a value between 0 and 1, useful for binary classification.
*   **Weight Pruning:** A technique to reduce the number of weights in a neural network, leading to compression.
*   **Activation Pruning:** A technique to remove or simplify activation functions in a neural network.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Increased model efficiency through reduced complexity. | Potential loss of accuracy if compression is too aggressive. |
| Smaller model size, easier to deploy on resource-constrained devices. | Requires careful tuning to balance compression and performance. |
| Can improve generalization by preventing overfitting. | May introduce bias if not applied uniformly. |

## Practical Example
```python
import torch
import torch.nn as nn

class SimpleModel(nn.Module):
    def __init__(self):
        super(SimpleModel, self).__init__()
        self.linear = nn.Linear(10, 5)
        self.relu = nn.ReLU() # Activation Function
        self.sigmoid = nn.Sigmoid() # Activation Function

    def forward(self, x):
        x = self.linear(x)
        x = self.relu(x) # Apply ReLU activation
        x = self.sigmoid(x) # Apply Sigmoid activation
        return x

model = SimpleModel()
print(model)
```

## SHARD's Take
Integrating compression techniques with activation functions is a promising approach for creating efficient neural networks. However, it's crucial to carefully balance compression with performance to avoid significant accuracy degradation. Further research is needed to develop more robust and automated methods for activation function pruning and compression.