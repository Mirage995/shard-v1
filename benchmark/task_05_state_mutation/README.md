# Task 05 — Fix the Data Pipeline

## Obiettivo

Correggere i bug in `pipeline.py` producendo `fixed_pipeline.py`.

La pipeline viene usata in produzione per trasformare batch di dati.
Dopo un po' di utilizzo, i risultati iniziano a non tornare.

## Regole

1. La classe `Pipeline` deve esistere con tutti i metodi originali
2. Ogni metodo deve comportarsi come descritto nella sua docstring
3. La pipeline deve funzionare correttamente anche dopo molte operazioni

## Condizioni di Vittoria

```
pytest test_task5.py -v
```

**Exit code 0** = vittoria.
