# python probability basics -- SHARD Cheat Sheet

## Key Concepts
* Probability distributions: statistical functions that describe the likelihood of different outcomes
* Random variables: variables whose possible values are determined by chance events
* Probability density functions: functions that describe the probability of a continuous random variable
* Conditional probability: the probability of an event occurring given that another event has occurred
* Bayes' theorem: a mathematical formula for updating probabilities based on new evidence

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Allows for modeling and analysis of uncertain events | Can be computationally intensive for complex problems |
| Enables prediction and decision-making under uncertainty | Requires a strong understanding of mathematical concepts |
| Has numerous applications in fields like machine learning and statistics | Can be sensitive to assumptions and model parameters |

## Practical Example
```python
import numpy as np

# Define a probability distribution (e.g. normal distribution)
mean = 0
stddev = 1
distribution = np.random.normal(mean, stddev, 1000)

# Calculate the probability of a specific event (e.g. x > 0)
probability = np.sum(distribution > 0) / len(distribution)
print("Probability:", probability)
```

## SHARD's Take
Mastering Python probability basics is essential for working with uncertain data and making informed decisions. By understanding key concepts like probability distributions and conditional probability, developers can build more robust and accurate models. With practice and experience, Python probability basics can become a powerful tool for solving real-world problems.