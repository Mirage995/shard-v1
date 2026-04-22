# spectral methods in network epidemiology -- SHARD Cheat Sheet

## Key Concepts
* Spectral graph theory: studies the properties of graphs using eigenvalues and eigenvectors of adjacency or Laplacian matrices
* Network epidemiology: applies mathematical models to understand the spread of diseases in populations
* Eigendecomposition: factorization of a matrix into eigenvalues and eigenvectors, useful for analyzing network structure
* Spectral clustering: technique for grouping similar nodes in a network based on spectral properties
* Epidemic threshold: critical value of the basic reproduction number that determines whether a disease will spread or die out

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Reveals underlying network structure | Computationally intensive for large networks |
| Identifies key nodes and communities | Assumes linear dynamics, may not capture nonlinear effects |
| Predicts epidemic spread and threshold | Requires accurate estimation of model parameters |

## Practical Example
```python
import networkx as nx
import numpy as np

# Create a sample network
G = nx.erdos_renyi_graph(100, 0.1)

# Compute adjacency matrix
A = nx.to_numpy_array(G)

# Perform eigendecomposition
eigenvalues, eigenvectors = np.linalg.eig(A)

# Identify key nodes using eigenvector centrality
centrality = np.abs(eigenvectors[:, 0])
key_nodes = np.argsort(centrality)[::-1]

print("Key nodes:", key_nodes[:10])
```

## SHARD's Take
The application of spectral methods to network epidemiology can provide valuable insights into the spread of diseases, but careful consideration of the underlying network structure and model assumptions is crucial. By identifying key nodes and communities, spectral methods can inform targeted interventions and mitigation strategies. However, computational intensity and potential nonlinear effects must be addressed to ensure accurate predictions.