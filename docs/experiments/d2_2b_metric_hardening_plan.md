# D2.2B Metric Hardening Plan

## Status

Planning only. No code changes, no benchmark run, no behavioral claim.

## Objective

Rendere le metriche operative meno proxy/log-derived e piu strutturate prima di una validazione piu ampia.

## Rationale

D2.2A ha prodotto `PASS_WEAK`:

- signal ripetibile in ARM_ON;
- `mood_min_mean` migliorato;
- `final_score_mean` leggermente migliore;
- `recovery_success`, `retries_count`, `loop_risk_proxy` e `certification_rank_mean` invariati;
- `benchmark_score` `UNAVAILABLE`.

Il limite principale non e' piu il signal GWT/Mood: D2.1D, D2.1E e D2.2A mostrano che il signal arriva nel ciclo observer. Il limite ora e' la qualita e la risoluzione delle metriche operative. D2.2 full senza metriche piu solide rischia di ripetere un `PASS_WEAK` senza chiarire outcome-level value.

## Experimental Question

Possiamo migliorare la strumentazione delle metriche operative senza cambiare il comportamento di SHARD, cosi che D2.2 full misuri outcome reali invece di proxy fragili?

## Scope

Instrumentation only.

- No behavioral changes.
- No `_WINNER_BIAS` changes.
- No ValenceField changes.
- No stress injection changes.
- No topic sequence or topic handling changes.
- No scoring logic changes.
- No decision logic changes.

## Metrics to Harden

- `benchmark_score` extraction
- `recovery_success` structured field
- `retries_count` structured counter
- `repeated_strategy_count` structured counter
- `strategy_shift` marker
- `certification_verdict` normalized rank
- `final_score` structured extraction
- Topic 2 windowing
- bias provenance field
- fallback provenance field

## Proposed Implementation Strategy

- Aggiungere structured markers nei log/manifest dove gli eventi esistono gia.
- Evitare parsing fragile da stdout quando possibile.
- Non cambiare decision logic.
- Non cambiare scoring logic.
- Non cambiare prompt, stress injection, topic routing o workspace arbitration.
- Far consumare all'analyzer structured fields se presenti.
- Lasciare fallback a log parsing solo quando structured fields sono assenti.
- Marcare metriche non disponibili come `MISSING` o `UNAVAILABLE`, senza inferirle.

Candidate structured fields:

- `observer_window_start_topic`
- `observer_window_found`
- `observer_retries_count`
- `observer_recovery_success`
- `observer_certification_verdict`
- `observer_certification_rank`
- `observer_final_score`
- `observer_benchmark_score`
- `observer_strategy_shift_detected`
- `observer_repeated_strategy_count`
- `workspace_bias_source`
- `winner_module`
- `ignition_failed`
- `fallback_source`

## Validation After Instrumentation

Dopo metric hardening, rieseguire lo stesso protocollo D2.2A come D2.2B validation:

- stesse 2 sequences;
- 2 reps;
- ARM_OFF vs ARM_ON;
- cached MAP/AGG sources;
- zero live DDGS/Brave/Playwright calls durante benchmark;
- subprocess isolation;
- stress injection controllata;
- bias/fallback provenance strutturata.

La D2.2B validation deve confrontare se le metriche strutturate confermano o correggono il `PASS_WEAK` di D2.2A.

## Success Criteria

### PASS_STRONG

- `benchmark_score` o equivalente outcome metric disponibile;
- recovery/retry/strategy/cert metrics strutturate;
- analyzer riduce `MISSING`/`UNAVAILABLE`;
- nessun cambio comportamentale intenzionale;
- D2.2A verdict viene confermato o raffinato con metriche piu affidabili.

### PASS_WEAK

- alcune metriche sono hardenate;
- `benchmark_score` resta unavailable;
- analyzer migliora provenance/windowing ma non risolve tutte le metriche operative.

### FAIL

- instrumentation troppo fragile;
- instrumentation altera il comportamento;
- structured fields non sono emessi dalla pipeline reale;
- analyzer continua a dipendere quasi solo da parsing fragile.

## Risks

- instrumentation invasiva;
- cambiare accidentalmente behavior;
- metriche ancora non emesse dal pipeline reale;
- log schema inconsistente;
- aumento rumore nei manifest;
- discrepanze tra structured fields e log parsing legacy;
- rischio di rendere l'analyzer piu complesso senza aumentare affidabilita.

## Recommendation

Fare D2.2B metric hardening prima del D2.2 full.

D2.2 full senza metriche migliori rischia di ripetere `PASS_WEAK` senza spiegare outcome-level value. D2.2B dovrebbe essere trattato come passaggio intermedio di strumentazione e validazione, non come esperimento di performance generale.

## Claim Boundary

Allowed after a successful D2.2B validation:

```text
D2.2B improves metric reliability for controlled operational validation of calibrated GWT/Mood coupling.
```

Forbidden:

```text
GWT improves SHARD performance.
```
