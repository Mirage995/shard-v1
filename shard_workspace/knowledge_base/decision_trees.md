# decision trees -- SHARD Cheat Sheet

## Key Concepts
* Decision Trees: a supervised learning method for classification and regression tasks
* Ensemble Methods: techniques to combine multiple decision trees for improved performance, such as Random Forests and Gradient Boosting
* Gini Index: a measure of impurity in a node, used to determine the best split
* Information Gain: a measure of the reduction in impurity after a split
* Overfitting: a common issue in decision trees, where the model becomes too complex and fits the noise in the data

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Simple to interpret and visualize | Can suffer from overfitting |
| Can handle both classification and regression tasks | Require careful selection of splitting criteria |
| Can be used for feature selection | Can be computationally expensive to train |

## Practical Example
```python
from sklearn.tree import DecisionTreeClassifier
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

# Load iris dataset
iris = load_iris()
X = iris.data
y = iris.target

# Split data into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Train a decision tree classifier
clf = DecisionTreeClassifier(random_state=42)
clf.fit(X_train, y_train)

# Evaluate the model
accuracy = clf.score(X_test, y_test)
print(f"Accuracy: {accuracy:.2f}")
```

## SHARD's Take
Decision trees are a fundamental concept in machine learning, offering a simple and interpretable way to perform classification and regression tasks. However, their implementation can be challenging due to the risk of overfitting, and careful selection of splitting criteria is crucial. By combining decision trees with ensemble methods, such as Random Forests and Gradient Boosting, we can improve their performance and robustness.