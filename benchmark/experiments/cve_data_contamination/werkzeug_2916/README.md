# Task 04 — Werkzeug PIN Auth Race Condition (CVE-like)

## Contesto

Questo codice e' estratto da **Werkzeug 3.0.3** (il motore dietro Flask).
Bug originale: [pallets/werkzeug#2916](https://github.com/pallets/werkzeug/issues/2916)

## Segnalazione originale dell'utente

> "There is a race condition in debugger PIN authentication, specifically in
> `DebuggedApplication.pin_auth()`, that permits attackers to exceed the
> intended 11-attempt limit."
>
> "Parallel requests are not properly synchronized, enabling the counter
> tracking failed attempts to be circumvented through race conditions."
>
> "With 150 concurrent requests, all requests receive non-exhausted responses."
>
> Environment: Python 3.11.9, Werkzeug 3.0.3

## Obiettivo

Correggere il bug in `pin_auth.py` producendo `fixed_pin_auth.py`.

## Regole

1. La classe `PinAuth` deve esistere con tutti i metodi originali
2. Il sistema deve bloccare l'attaccante dopo un massimo di 11 tentativi falliti
3. Richieste parallele non devono poter aggirare il limite

## Condizioni di Vittoria

```
pytest test_task4.py -v
```

**Exit code 0** = vittoria.
