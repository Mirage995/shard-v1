# D2.2 Operational Value Validation Plan

## Status

Planning only. No code changes, no benchmark run, no operational claim.

## Experimental Question

Il coupling GWT/Mood calibrato produce valore operativo ripetibile su piu topic/run, oltre al solo effetto debole su `mood_min` osservato in D2.1E?

## Rationale

D2.1D ha validato internal next-cycle signal propagation dopo la calibrazione di `MoodWorkspaceCoupling` per il winner dominante sotto stress, `tensions`.

D2.1E ha prodotto un `PASS_WEAK`:

- il real workspace signal e' presente nel ciclo observer;
- `mood_min` e' meno severo in ARM_ON;
- non sono emersi miglioramenti operativi su `recovery_success`, `retries_count`, `strategy_shift_detected`, `certification_verdict`, `final_score` o `loop_risk_proxy`.

D2.2 deve quindi testare outcome-level value e ripetibilita'. Il punto non e' dimostrare che GWT migliori SHARD in generale, ma verificare se il segnale interno calibrato genera differenze comportamentali ripetibili sotto protocollo controllato.

## Candidate Protocol

Il protocollo candidato deve restare piu ampio di D2.1E ma ancora controllato:

- stesso harness validato in D2.1A/D2.1E;
- cached MAP/AGG sources;
- zero live DDGS/Brave/Playwright calls durante il benchmark;
- subprocess isolation;
- ARM_OFF vs ARM_ON;
- stress injection controllata;
- bias provenance esplicita;
- multiple topic sequences;
- nessun cambio a `_WINNER_BIAS`, ValenceField, stress injection o topic handling durante la run;
- evitare di partire subito troppo grande.

### D2.2A Micro Validation

- 2 topic sequences;
- 2 repliche per sequence;
- 2 arms: ARM_OFF e ARM_ON;
- totale previsto: 8 subprocess, cioe' 2 arms x 2 sequences x 2 reps;
- obiettivo: verificare se il `PASS_WEAK` di D2.1E si ripete fuori dalla singola sequence OOP -> asyncio.

D2.2A dovrebbe essere il primo step operativo: piccolo, replicabile e utile per hardenare analyzer e metriche prima di una validazione piu costosa.

### D2.2 Full Validation

- 3-5 topic sequences;
- 2-3 repliche per sequence;
- costo runtime/API piu alto;
- da eseguire solo se D2.2A mostra un segnale promettente e metriche abbastanza affidabili.

## Candidate Topic Sequences

Ogni sequence mantiene la distinzione:

- Topic 1 = stress inducer;
- Topic 2 = behavioral observer.

Candidate sequences:

1. `python OOP design patterns` -> `asyncio advanced patterns`
2. `sql injection prevention python` -> `python error handling patterns`
3. `python dependency injection patterns` -> `async retry/backoff patterns`

Se le cache per una sequence non esistono, devono essere prefetchate prima del benchmark con una fase separata e tracciata. Questo planning non avvia prefetch, benchmark o browser/network calls.

## Primary Metrics

Metriche operative principali:

- `recovery_success`
- `certification_verdict`
- `final_score`
- `benchmark_score`, se disponibile in modo affidabile
- `retries_count`
- `loop_risk_proxy`
- `repeated_strategy_count`

Queste metriche devono guidare il verdict operativo. Se una metrica non e' estraibile in modo affidabile, deve essere marcata `MISSING` o `UNAVAILABLE`, non inferita.

## Secondary Metrics

Metriche secondarie e diagnostiche:

- `mood_min`
- `mood_recovery_delta`
- `workspace_bias_present`
- `strategy_shift_detected`
- `fallback_provenance`
- `tensions_trace_count`

Le secondary metrics possono supportare un `PASS_WEAK`, ma non bastano da sole per un claim operativo forte.

## Required Analyzer Improvements

Prima di D2.2 servono analyzer improvements mirati:

- bias provenance piu strutturata, non solo log-derived;
- Topic 2 windowing piu robusto;
- retry count strutturato;
- strategy shift marker meno fragile;
- `certification_verdict` e `final_score` extraction piu affidabile;
- `benchmark_score` extraction, se il dato e' disponibile;
- `repeated_strategy_count` esplicito.

ARM_OFF fallback bias deve restare classificato separatamente ed escluso dal GWT signal. ARM_ON workspace bias va trattato come signal/provenance, non come performance.

## Verdict Criteria

### PASS_STRONG

- harness clean;
- ARM_ON migliora almeno 2 primary metrics aggregate;
- nessuna regressione grave sulle primary metrics rimanenti;
- effetto ripetibile su piu sequence/run;
- signal provenance chiara.

### PASS_WEAK

- harness clean;
- ARM_ON migliora secondary metrics o una sola primary metric;
- segnale interessante ma non sufficiente per claim operativo forte;
- provenance e extraction abbastanza leggibili ma non ancora mature.

### FAIL

- harness clean;
- signal presente ma nessun miglioramento operativo aggregato;
- oppure ARM_ON peggiora le metriche principali.

### INCONCLUSIVE

- metriche sparse;
- N insufficiente;
- stochasticity dominante;
- extraction fragile;
- observer cycle non abbastanza informativo.

### CONTAMINATED

- live DDGS/Brave/Playwright calls;
- cache mismatch;
- subprocess failure;
- stress injection missing;
- missing mood samples;
- topic sequence non osservata;
- fallback/provenance non classificabile.

## Risk Register

- costo compute/API;
- runtime lungo;
- stochasticity LLM;
- metriche proxy troppo fragili;
- stress injection artificiale;
- mood sensitivity senza outcome improvement;
- cert rate troppo coarse;
- rischio overfitting al protocollo OOP -> asyncio.

## Recommendation

Non fare subito D2.2 full. Fare prima D2.2A Micro Validation.

D2.2A dovrebbe essere:

- piccolo;
- replicabile;
- orientato a hardenare metriche/analyzer;
- senza claim performance forte.

Solo se D2.2A mostra differenze ripetibili e metriche piu solide ha senso passare a D2.2 Full Validation.

## Allowed Claim

Se D2.2A passa:

> Under a controlled multi-sequence protocol, calibrated GWT/Mood coupling shows repeatable behavioral differences in observer cycles.

## Forbidden Claim

> GWT improves SHARD performance.

Questo claim richiede D2.2 full o esperimenti successivi con N maggiore e outcome-level validation.
