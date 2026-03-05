# completa lo studio sul Perceptrone. Scrivi, esegui e testa nella Sandbox un perceptrone neurale in Python da zero (senza usare scikit-learn o librerie di machine learning). Fagli imparare la logica di una porta AND o OR. Valuta i risultati." — SHARD Cheat Sheet

## Key Concepts
* Una rete neurale con un solo strato nascosto, utilizzato per classificazione binaria
* La matematica di backpropagation per ottimizzare la rete neurale
* La funzione di attivazione sigmoid utilizzata nella rete neurale
* La rete neurale artificiale come modello di intelligenza artificiale per classificazione binaria

## Pro & Contro
| Pro | Contro |
|-----|--------|
| La rete neurale può imparare complesse relazioni tra variabili | La rete neurale può essere difficile da interpretare e debuggere |
| La rete neurale può essere utilizzata per classificazione binaria | La rete neurale richiede una grande quantità di dati di addestramento |
| La rete neurale può essere utilizzata per prevedere valori continui | La rete neurale può essere instabile e richiede una ottimizzazione costante |

## Practical Example
```python
import numpy as np

class Perceptrone:
    def __init__(self, alpha=0.1, beta=0.1):
        self.alpha = alpha
        self.beta = beta
        self.weights = np.random.rand(2, 1)
        self.bias = np.random.rand(1)

    def sigmoid(self, x):
        return 1 / (1 + np.exp(-x))

    def forward(self, x):
        return self.sigmoid(np.dot(x, self.weights) + self.bias)

    def backprop(self, x, y, error):
        d_weights = self.alpha * np.dot(x.T, (2 * error * self.sigmoid(np.dot(x, self.weights) + self.bias) - self.sigmoid(np.dot(x, self.weights) + self.bias) * (y - self.sigmoid(np.dot(x, self.weights) + self.bias))))
        d_bias = self.alpha * np.sum(2 * error * self.sigmoid(np.dot(x, self.weights) + self.bias) - self.sigmoid(np.dot(x, self.weights) + self.bias) * (y - self.sigmoid(np.dot(x, self.weights) + self.bias)), axis=0)
        return d_weights, d_bias

    def train(self, x, y, epochs=1000):
        for _ in range(epochs):
            error = np.mean((self.forward(x) - y) ** 2)
            d_weights, d_bias = self.backprop(x, y, 2 * (self.forward(x) - y))
            self.weights -= self.alpha * d_weights
            self.bias -= self.beta * d_bias

# Utilizzo del perceptrone per una porta AND
x_and = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
y_and = np.array([0, 0, 0, 1])
perceptrone = Perceptrone()
perceptrone.train(x_and, y_and)
print(perceptrone.forward(x_and))
```

## SHARD's Take
La rete neurale artificiale è un modello di intelligenza artificiale che utilizza la matematica di backpropagation per ottimizzare la rete neurale, permettendole di imparare complesse relazioni tra variabili e prevedere valori continui. Tuttavia, la rete neurale può essere difficile da interpretare e debuggere, e richiede una grande quantità di dati di addestramento.