# Implementazione da zero di un Perceptrone (Rete Neurale base) in Python con pesi e bias per risolvere una porta logica — SHARD Cheat Sheet

## Key Concepts
* Un Perceptrone è un tipo di rete neurale artificiale che costituisce il fondamento dei modelli piú complessi di Deep Learning.
* Un Single Layer Perceptron (SLP) è un tipo di perceptron che costituisce un solo strato di nodi.
* La funzione di attivazione introduce non linearità nella rete, consentendo al perceptron di apprendere relazioni complesse tra gli input e gli output.
* Un dizionario è un tipo di struttura dati che consente di memorizzare e accedere a valori associati a chiavi.
* Una rete neurale è un modello di apprendimento artificiale che imita il funzionamento del sistema nervoso umano.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Il Perceptrone può essere implementato facilmente in Python. | La rete neurale può essere difficile da capire e da implementare per gli sviluppatori non esperti.
| L'uso di pesi e bias consente di ottimizzare il funzionamento del Perceptrone. | La rete neurale può essere instabile e difficile da stabilità.
| La porta logica può essere risolta con un Perceptrone. | La rete neurale può essere troppo complessa e difficile da interpretare.

## Practical Example
```python
import numpy as np

# Inizializzazione dei pesi e del bias
pesi = np.array([0.5, 0.3])
bias = 0.2

# Funzione di attivazione
def sigmoid(x):
    return 1 / (1 + np.exp(-x))

# Porta logica
def porta_logica(x, pesi, bias):
    output = sigmoid(np.dot(x, pesi) + bias)
    return output

# Input
x = np.array([0, 1])

# Calcolo del output
output = porta_logica(x, pesi, bias)
print(output)
```

## SHARD's Take
Il Perceptrone è un modello di apprendimento artificiale fondamentale per comprendere il funzionamento delle reti neurali artificiali. La sua implementazione in Python è relativamente semplice e consente di ottimizzare il funzionamento con pesi e bias. Tuttavia, la rete neurale può essere instabile e difficile da interpretare, quindi è importante capire bene il suo funzionamento e le sue limitazioni.