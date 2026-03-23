# Task 07 — Fix the Metrics Collector

## Obiettivo

Correggere i bug in `metrics.py` producendo `fixed_metrics.py`.

Il modulo raccoglie metriche applicative (counter, histogram) usate
per il monitoring in produzione.

Gli utenti segnalano due problemi:
1. I conteggi dei bucket di un Histogram "sanguinano" in altri Histogram
   dello stesso processo (valori da un collector appaiono in un altro)
2. I calcoli dei percentili restituiscono risultati inconsistenti
   tra chiamate successive sulla stessa istanza

## Regole

1. Tutte le classi (`Counter`, `Histogram`, `MetricsCollector`) devono esistere
2. Ogni `Histogram` deve avere bucket **isolati** dagli altri
3. `percentile()` non deve modificare lo stato interno dell'istanza
4. Il comportamento dei `Counter` non deve cambiare

## Condizioni di Vittoria

```
pytest test_task7.py -v
```

**Exit code 0** = vittoria.
