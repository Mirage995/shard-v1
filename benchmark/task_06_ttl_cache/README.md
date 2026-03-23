# Task 06 — Fix the TTL Cache

## Obiettivo

Correggere i bug in `cache.py` producendo `fixed_cache.py`.

Il modulo è un cache in-memory con TTL (Time To Live) usato in produzione
per memorizzare risposte API costose.

Gli utenti segnalano due problemi:
1. Dopo la scadenza del TTL, viene restituito il vecchio valore invece di `None`
2. La proprietà `size` riporta un numero più alto del previsto

## Regole

1. La classe `TTLCache` deve esistere con tutti i metodi originali
2. `get()` deve restituire `None` (non il vecchio valore) se la chiave è scaduta
3. `size` deve contare solo le entry **non scadute**
4. Il comportamento delle entry non scadute non deve cambiare

## Condizioni di Vittoria

```
pytest test_task6.py -v
```

**Exit code 0** = vittoria.
