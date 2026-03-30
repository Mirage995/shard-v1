# Task 13 — Config Parser (OOD)

## Obiettivo

Fixare `parser.py` producendo `fixed_parser.py`.

Il parser sembra funzionare su input semplici. I bug emergono su input reali:
URL con colonne, whitespace intorno a chiavi/valori, righe vuote, commenti, chiavi mancanti.

## I 4 Bug

| # | Funzione | Bug | Sintomo |
|---|----------|-----|---------|
| 1 | `parse_line` | `split(':')` senza maxsplit | "http://host:8080" diventa 3 parti, crash su `parts[1]` |
| 2 | `parse_line` | Nessun `.strip()` su key/value | Spazi nelle chiavi: `" host"` invece di `"host"` |
| 3 | `load_config` | Nessun skip per righe vuote o commenti | `IndexError` su righe vuote, commenti parsati come chiavi |
| 4 | `get_setting` | `config[key]` invece di `.get()` | `KeyError` quando la chiave non esiste, `default` ignorato |

## Perche Un LLM Fallisce

- Bug 1: solo con valori che contengono `:` (URL, timestamp). Input semplici passano.
- Bug 3: solo con input multi-riga con righe vuote o commenti. Non visibile su input puliti.
- Bug 4: solo quando si cerca una chiave assente. Il parametro `default` esiste ma non viene usato.

## Pattern Atteso nel Diff

```
- parts = line.split(":")
+ parts = line.split(":", 1)

- key = parts[0]
- value = parts[1]
+ key = parts[0].strip()
+ value = parts[1].strip()

+ if not line.strip() or line.strip().startswith("#"):
+     continue

- return config[key]
+ return config.get(key, default)
```

## Condizioni di Vittoria

```
pytest test_task13.py -v
```

16 test totali — exit code 0.
