# Data Contamination Experiments

## Il problema

Questi task usano bug reali da GitHub (CVE, issue pubbliche, PR documentate).

**Risultato**: Sonnet li risolve al primo tentativo — non perché ragioni,
ma perché li ha memorizzati dal training set.

Werkzeug #2916 è una CVE pubblica. Sonnet l'ha vista nel training data.
Non ha "scoperto" la race condition: ha recitato la patch a memoria.

## Lezione

Il valore di SHARD esplode su problemi **Zero-Day**:
- Bug inventati internamente (mai visti dal modello)
- Logica di business proprietaria (non su GitHub)
- Comportamenti runtime imprevedibili (concorrenza, performance, stato)

CVE di librerie famose = training data contaminato = test invalido.

## Come usarlo con i VC

Se un Technical Partner chiede "Perché non testate su bug reali di GitHub?",
apri questa cartella. Dimostri che ci hai pensato, che conosci il problema
e che hai già la risposta: *il vero test è sul codice che il modello non ha mai visto.*
