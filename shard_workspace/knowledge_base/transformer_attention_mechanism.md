```markdown
# transformer attention mechanism — SHARD Cheat Sheet

## Key Concepts
*   **Attention Mechanism:** Allows the model to focus on different parts of the input sequence when processing it.
*   **Self-Attention:** Attention mechanism applied to a single sequence to relate different positions of the same sequence.
*   **Queries, Keys, Values:** Input sequences are transformed into these three components to compute attention weights.
*   **Scaled Dot-Product Attention:** A specific implementation of attention that scales the dot product of queries and keys.
*   **Multi-Head Attention:** Multiple attention mechanisms are run in parallel and their outputs concatenated.
*   **Positional Encoding:** Adds information about the position of tokens in the sequence, as transformers are permutation-invariant.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Captures long-range dependencies effectively. | Computationally expensive, especially for long sequences. |
| Allows parallel processing of the input sequence. | Can be difficult to interpret and debug. |
| Improves model performance in various NLP tasks. | Requires careful tuning of hyperparameters. |

## Practical Example
```python
import torch
import torch.nn.functional as F

def scaled_dot_product_attention(query, key, value, mask=None):
    d_k = query.size(-1)
    scores = torch.matmul(query, key.transpose(-2, -1)) / torch.sqrt(torch.tensor(d_k, dtype=torch.float32))
    if mask is not None:
        scores = scores.masked_fill(mask == 0, float('-inf'))
    attention_weights = F.softmax(scores, dim=-1)
    output = torch.matmul(attention_weights, value)
    return output

# Example usage
query = torch.randn(1, 5, 64) # (batch_size, seq_len, d_k)
key = torch.randn(1, 10, 64)  # (batch_size, seq_len, d_k)
value = torch.randn(1, 10, 64) # (batch_size, seq_len, d_v)

output = scaled_dot_product_attention(query, key, value)
print(output.shape) # Expected output: torch.Size([1, 5, 64])
```

## SHARD's Take
The transformer attention mechanism is a powerful tool for capturing relationships within sequences. Its ability to weigh the importance of different parts of the input makes it crucial for tasks like machine translation and text summarization. Understanding the underlying principles and variations is essential for effective model design and optimization.
```