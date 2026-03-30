# Task 14 — Boundary Check (OOD)

## Obiettivo

Fixare `analyzer.py` producendo `fixed_analyzer.py`.

Il codice funziona su sequenze standard. I bug emergono sui casi limite:
lista con un elemento, lista vuota, primo e ultimo elemento nella ricerca di picchi.

## I 3 Bug

| # | Funzione | Bug | Sintomo |
|---|----------|-----|---------|
| 1 | `compute_changes` | `range(len(series))` poi accede a `series[i+1]` | `IndexError` sull'ultimo elemento |
| 2 | `find_local_peaks` | `range(len(data))` con accesso a `data[i-1]` e `data[i+1]` | i=0: `data[-1]` e' l'ultimo elemento (accesso circolare silenzioso, risultato sbagliato); i=len-1: `IndexError` |
| 3 | `find_local_peaks` | Iterazione include primo e ultimo indice | Il primo e ultimo elemento non hanno 2 vicini — non possono essere picchi per definizione |

## Perche Un LLM Fallisce

- Bug 1: il codice sembra corretto a lettura statica. Crasha solo su input con >= 1 elemento.
- Bug 2: in Python `data[-1]` e' legale e non crasha — il modello considera corretto il codice.
  Il test `test_first_element_not_peak` cattura il risultato silenziosamente sbagliato.
- Bug 3: conseguenza diretta di 2 — se il range viene fixato a (1, len-1), i casi limite si risolvono.

## Pattern Atteso nel Diff

```python
# compute_changes
- for i in range(len(series)):
+ for i in range(len(series) - 1):

# find_local_peaks
- for i in range(len(data)):
+ for i in range(1, len(data) - 1):
```

## Condizioni di Vittoria

```
pytest test_task14.py -v
```

26 test totali — exit code 0.
