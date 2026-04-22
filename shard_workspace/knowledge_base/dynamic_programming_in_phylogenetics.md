# dynamic programming in phylogenetics -- SHARD Cheat Sheet

## Key Concepts
* Phylogenetic trees: graphical representations of evolutionary relationships between organisms
* Dynamic programming: method for solving complex problems by breaking them down into smaller subproblems
* Sequence alignment: process of comparing and aligning DNA or protein sequences to identify similarities and differences
* Maximum parsimony: method for reconstructing phylogenetic trees by minimizing the number of evolutionary changes
* Maximum likelihood: method for reconstructing phylogenetic trees by maximizing the probability of observing the data given the tree

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Dynamic programming can efficiently solve complex phylogenetic problems | Requires careful formulation of the problem and selection of parameters |
| Can handle large datasets and complex evolutionary models | Computationally intensive and may require significant computational resources |
| Allows for the integration of multiple sources of data and prior knowledge | May be sensitive to the choice of parameters and prior distributions |

## Practical Example
```python
import numpy as np

def phylogenetic_distance(seq1, seq2):
    m = len(seq1)
    n = len(seq2)
    dp = np.zeros((m+1, n+1))
    
    for i in range(m+1):
        dp[i, 0] = i
    for j in range(n+1):
        dp[0, j] = j
    
    for i in range(1, m+1):
        for j in range(1, n+1):
            cost = 0 if seq1[i-1] == seq2[j-1] else 1
            dp[i, j] = min(dp[i-1, j] + 1, dp[i, j-1] + 1, dp[i-1, j-1] + cost)
    
    return dp[m, n]

# Example usage:
seq1 = "ATCG"
seq2 = "ATGC"
distance = phylogenetic_distance(seq1, seq2)
print("Phylogenetic distance:", distance)
```

## SHARD's Take
Dynamic programming is a powerful tool for solving complex phylogenetic problems, but its application requires careful consideration of the problem formulation, parameter selection, and computational resources. By integrating multiple sources of data and prior knowledge, dynamic programming can provide a robust and efficient framework for reconstructing phylogenetic trees and analyzing evolutionary relationships. However, its sensitivity to parameter choices and prior distributions must be carefully evaluated to ensure reliable results.