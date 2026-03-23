# Task 03 — Optimize the Transaction Processor

## Obiettivo

Ottimizzare `legacy_processor.py` producendo `optimized_processor.py`.

Il codice legacy processa 10.000 transazioni finanziarie. Funziona, ma e' lento e brutto: loop manuali, nessun uso di `defaultdict`/`Counter`, aggregazione ridondante.

L'agente deve renderlo **veloce e Pythonico** mantenendo la correttezza al byte.

## Regole

1. La funzione `process_transactions(transactions)` deve esistere
2. Deve restituire un dict con le stesse chiavi e gli stessi valori del legacy
3. Deve essere almeno **30% piu' veloce** del legacy
4. Deve usare pattern Python moderni (defaultdict, Counter, comprehension, etc.)

## Condizioni di Vittoria

```
pytest test_task3.py -v
```

**Exit code 0** = vittoria.

## File

| File | Ruolo |
|------|-------|
| `legacy_processor.py` | Il codice da ottimizzare. **Non modificare.** |
| `test_task3.py` | I test. **Non modificare.** |
| `optimized_processor.py` | Creato dall'agente. L'unico file scrivibile. |
