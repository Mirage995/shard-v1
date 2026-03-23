# Task 04 — Fix the Banking Module

## Obiettivo

Correggere i bug in `bank.py` producendo `fixed_bank.py`.

Il modulo gestisce conti bancari ed e' usato in produzione.
Alcuni utenti segnalano saldi errati.

## Regole

1. La classe `Bank` deve esistere con tutti i metodi originali
2. I saldi devono sempre essere corretti
3. Non deve essere possibile creare denaro dal nulla o farlo sparire

## Condizioni di Vittoria

```
pytest test_task4.py -v
```

**Exit code 0** = vittoria.
