# Task 02 — The Ghost Bug

## Obiettivo

Fixare `buggy_pipeline.py` producendo `fixed_pipeline.py`.

Il codice sembra corretto a una lettura statica. **Ogni funzione, presa singolarmente, e' ragionevole.** I bug emergono solo dalle INTERAZIONI tra le funzioni a runtime.

Un LLM stateless che legge il codice dira' "sembra ok" e produrra' una copia quasi identica. Poi crashera'.

## I 5 Bug Fantasma

| # | Funzione | Bug | Sintomo Runtime |
|---|----------|-----|-----------------|
| 1 | `validate_readings` | Usa `copy()` (shallow) invece di `deepcopy()`. Muta i dict originali aggiungendo la key `"valid"`. | La seconda chiamata vede dati gia' mutati. |
| 2 | `calibrate_values` | Modifica i dict in-place. Se chiamata due volte, applica l'offset due volte. | Valori che driftano ad ogni chiamata. |
| 3 | `aggregate_by_group` | Include readings invalidi nel calcolo delle medie (hanno ancora `"value"`). | Medie corrotte da valori fuori range. |
| 4 | `detect_anomalies` | Accede a `reading["calibrated_value"]` ma la key e' `"value"`. | `KeyError: 'calibrated_value'` |
| 5 | `generate_report` | Accede a `data['avg']` e `a['z']` ma le key sono `"average"` e `"z_score"`. | `KeyError: 'avg'` |

## Perche Un LLM Stateless Fallisce

- Bug 1 e 2 sono **invisibili** senza eseguire il codice. Richiedono ragionamento sulla mutabilita'.
- Bug 4 e 5 crashano immediatamente ma il messaggio di errore non dice *dove* fixare, solo *cosa* e' andato storto.
- Bug 3 non crasha — produce risultati silenziosamente sbagliati. Solo il test dei valori attesi lo cattura.

L'agente DEVE:
1. Tentare di eseguire il codice
2. Leggere il traceback
3. Capire la root cause
4. Fixare
5. Re-eseguire per scoprire il bug successivo (fix one → reveal next)

## Condizioni di Vittoria

```
pytest test_task2.py -v
```

**Exit code 0** = vittoria.

### Gruppi di Test (16 test)

1. **NoCrash** (3 test) — la pipeline non deve crashare
2. **BugFixes** (5 test) — ogni bug specifico deve essere fixato
3. **SemanticCorrectness** (6 test) — i valori devono essere matematicamente corretti
4. **Structure** (2 test) — mantenere l'architettura modulare, niente try/except che sopprimono errori

## Il Pattern "Fix One, Reveal Next"

Questo task e' progettato come una catena:

```
Bug 4 (KeyError) → fix → Bug 5 (KeyError) → fix → Pipeline runs →
Bug 3 (wrong averages) → fix → Bug 1 (mutation) → fix → Bug 2 (idempotency) → fix → VICTORY
```

Ogni fix rivela il bug successivo. Senza il feedback loop, l'agente deve indovinare tutti e 5 i bug dalla lettura del codice. Con il loop, li scopre uno alla volta.

## File

| File | Ruolo |
|------|-------|
| `buggy_pipeline.py` | Il codice buggato. **Non modificare.** |
| `test_task2.py` | I test. **Non modificare.** |
| `fixed_pipeline.py` | Creato dall'agente. L'unico file scrivibile. |
