# scikit-learn clustering basics -- SHARD Cheat Sheet

## Key Concepts
* K-Means Clustering: an unsupervised learning algorithm that groups similar data points into clusters based on their features.
* Hierarchical Clustering: a method of cluster analysis that builds a hierarchy of clusters by merging or splitting existing ones.
* DBSCAN (Density-Based Spatial Clustering of Applications with Noise): a density-based clustering algorithm that groups data points into clusters based on their density and proximity.
* Silhouette Coefficient: a measure of how similar an object is to its own cluster compared to other clusters.
* Elbow Method: a technique used to determine the optimal number of clusters in K-Means Clustering by plotting the sum of squared errors against the number of clusters.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Easy to implement and interpret | Sensitive to initial centroid placement and outliers |
| Handles large datasets efficiently | Assumes spherical clusters and may not perform well with complex shapes |
| Robust to noise and missing values | Can be computationally expensive for high-dimensional data |

## Practical Example
```python
from sklearn.cluster import KMeans
import numpy as np

# Generate sample data
np.random.seed(0)
data = np.random.rand(100, 2)

# Perform K-Means Clustering
kmeans = KMeans(n_clusters=5)
kmeans.fit(data)

# Print cluster labels
print(kmeans.labels_)
```

## SHARD's Take
The scikit-learn library provides an efficient and easy-to-use implementation of various clustering algorithms, including K-Means, Hierarchical, and DBSCAN. However, the choice of algorithm and hyperparameters depends on the specific problem and dataset. By understanding the strengths and limitations of each algorithm, developers can effectively apply clustering techniques to real-world problems.