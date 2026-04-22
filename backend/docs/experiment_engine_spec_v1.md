# SHARD Experiment Engine — Spec v1.0

**Data:** 2026-04-11  
**Status:** Blueprint — da implementare nel prossimo sprint  
**Dipende da:** #34 (arxiv research mode, hypothesis generation in SYNTHESIZE)

---

## Obiettivo

Quando SHARD genera un'hypothesis in research mode (confidence >= 0.6, falsifiable=True),
deve poterla testare autonomamente: tradurre `minimum_experiment` in codice Python,
eseguirlo in sandbox Docker, misurare il risultato reale e aggiornare `confidence`
con un dato empirico invece di una stima LLM.

---

## Componenti

### 1. ExperimentDesignPhase
- **File:** `backend/experiment_phases.py` (nuovo)
- **Trigger:** `research_mode=True` AND `hypothesis.falsifiable=True` AND `hypothesis.confidence >= 0.6`
- **Input:** `ctx.structured['hypothesis']` (statement, domain_from, domain_to, minimum_experiment, confidence)
- **Output:** `ctx.experiment_code: str`
- **Comportamento:** chiama `ctx.agent._generate_experiment_code(hypothesis)` — LLM con vincoli hard:
  - Zero download, zero network calls
  - Librerie consentite: numpy, sklearn, torch CPU, scipy, pandas
  - Dataset: generati sinteticamente inline
  - Output obbligatorio: `print('RESULT:', round(float(score), 4))`
  - Max 130 secondi di esecuzione
  - Codice autonomamente eseguibile
- **Gate fallisce:** setta `ctx.experiment_status = "SKIPPED"` e ritorna (non blocca pipeline)

### 2. ExperimentSandboxPhase
- **File:** `backend/experiment_phases.py` (stesso file del punto 1)
- **Trigger:** `ctx.experiment_status != "SKIPPED"`
- **Input:** `ctx.experiment_code`
- **Output:** `ctx.experiment_result: Dict` (stdout, stderr, exit_code, success)
- **Comportamento:** chiama `DockerSandboxRunner.run()` invariato — zero modifiche al runner
- **Parser:** estrae `RESULT: {score}` con regex `r'RESULT:\s*([\d.]+)'`; fallback `INCONCLUSIVE` se pattern non trovato

### 3. ExperimentValidatePhase
- **File:** `backend/experiment_phases.py` (stesso file)
- **Trigger:** `ctx.experiment_result` disponibile
- **Input:** `ctx.experiment_result`, `ctx.structured['hypothesis']`
- **Output:** `ctx.experiment_status: str`, `ctx.hypothesis_confidence_updated: float`
- **Comportamento:**
  - Chiama `ctx.agent._validate_experiment_result(hypothesis, stdout)` — LLM decide CONFIRMED / REFUTED / INCONCLUSIVE
  - Aggiorna `confidence_updated` con valore reale
  - Persiste su DB via `ExperimentStore.store_hypothesis()`

### 4. Layer E (EMPIRICAL) in CognitionCore
- **File:** `backend/cognition/cognition_core.py` (esistente, esteso)
- **Metodo nuovo:** `query_empirical(topic: str) -> Dict`
  - Legge da `ExperimentStore.get_by_topic(topic)` — solo lettura, nessuna LLM call
  - Ritorna hypothesis testate con status e confidence aggiornata
- **Iniezione:** aggiunto in fondo a `relational_context()` con gate esplicito research_mode
- **Budget:** +30-50 token max (1-2 entry per topic), non intacca il target ~500 token nel path normale

### 5. ExperimentStore
- **File:** `backend/experiment_store.py` (nuovo)
- **Funzioni pubbliche:** `store_hypothesis()`, `update_result()`, `get_by_topic()`
- **Pattern:** segue `experiment_cache.py` — lazy import `shard_db`, nessuna logica LLM

---

## Schema DB (da aggiungere a schema.sql)

```sql
CREATE TABLE IF NOT EXISTS research_hypotheses (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    topic                 TEXT NOT NULL,
    statement             TEXT NOT NULL,
    domain_from           TEXT,
    domain_to             TEXT,
    confidence_initial    REAL,
    confidence_updated    REAL,
    status                TEXT,    -- CONFIRMED / REFUTED / INCONCLUSIVE / SKIPPED_TOO_COMPLEX
    experiment_code       TEXT,
    experiment_result     TEXT,    -- JSON: stdout/stderr/exit_code
    falsifiable           INTEGER, -- 0/1
    minimum_experiment    TEXT,
    created_at            TEXT NOT NULL,
    tested_at             TEXT
);
```

---

## Campi nuovi su StudyContext

Da aggiungere in `backend/study_context.py` dopo `benchmark_result`:

```python
experiment_code: Optional[str] = None
experiment_result: Optional[Dict] = None
experiment_status: Optional[str] = None
hypothesis_confidence_updated: Optional[float] = None
```

**IMPORTANTE:** `sandbox_result` (campo esistente) NON viene toccato.
E' proprietà esclusiva di `SandboxPhase` + `CertifyRetryGroup`.

---

## Posizione nel pipeline

```
1.  InitPhase
2.  MapPhase
3.  AggregatePhase
4.  SynthesizePhase           <- hypothesis generata qui
--- NUOVE (no-op se research_mode=False) ---
5.  ExperimentDesignPhase     <- gate: falsifiable=True + confidence>=0.6
6.  ExperimentSandboxPhase    <- DockerSandboxRunner invariato
7.  ExperimentValidatePhase   <- verdict LLM + write DB
--- ESISTENTI INVARIATE ---
8.  StorePhase                <- vede experiment_status in ctx
9.  CrossPollinatePhase
10. MaterializePhase
11. SandboxPhase              <- codegen normale, sandbox_result invariato
12. CertifyRetryGroup
13. PostStudyPhase
```

---

## Dipendenze tra componenti

```
ExperimentDesignPhase
  -> legge:  ctx.structured['hypothesis']
  -> chiama: ctx.agent._generate_experiment_code()
  -> scrive: ctx.experiment_code

ExperimentSandboxPhase
  -> legge:  ctx.experiment_code
  -> chiama: DockerSandboxRunner.run()   <- ZERO modifiche
  -> scrive: ctx.experiment_result

ExperimentValidatePhase
  -> legge:  ctx.experiment_result, ctx.structured['hypothesis']
  -> chiama: ctx.agent._validate_experiment_result()
  -> scrive: ctx.experiment_status, ctx.hypothesis_confidence_updated
  -> chiama: ExperimentStore.store_hypothesis()

Layer E query_empirical()
  -> legge:  ExperimentStore.get_by_topic()   <- solo lettura
  -> nessuna LLM call, nessuna scrittura
```

---

## File toccati

| File | Tipo | Modifica |
|------|------|----------|
| `backend/experiment_phases.py` | NUOVO | ExperimentDesignPhase, SandboxPhase, ValidatePhase |
| `backend/experiment_store.py` | NUOVO | DB access layer per research_hypotheses |
| `backend/schema.sql` | ESISTENTE | Aggiunge tabella research_hypotheses |
| `backend/study_context.py` | ESISTENTE | Aggiunge 4 campi experiment_* |
| `backend/study_agent.py` | ESISTENTE | Aggiunge _generate_experiment_code(), _validate_experiment_result(), wire fasi nel pipeline |
| `backend/cognition/cognition_core.py` | ESISTENTE | Aggiunge query_empirical() + Layer E in relational_context() |

---

## Cosa NON toccare

- `backend/sandbox_runner.py` — DockerSandboxRunner usato invariato
- `SandboxPhase` in `study_phases.py` — non interferisce
- `ctx.sandbox_result` — non sovrascrivere mai
- `CertifyRetryGroup` — repair loop invariato
- `NightRunner` — `--research` flag già in place (#34)
- Ciclo non-research — se `research_mode=False`, tutto è no-op
- `relational_context()` nel path non-research — Layer E non viene chiamato

---

## Ordine di implementazione (prossimo sprint)

1. `schema.sql` — aggiunge `research_hypotheses` (migration idempotente)
2. `experiment_store.py` — persistence layer, testabile standalone
3. Campi `StudyContext` — zero logica, safe
4. `_generate_experiment_code()` in `study_agent.py` — test standalone su hypothesis reale
5. `experiment_phases.py` — ExperimentDesignPhase + ExperimentSandboxPhase
6. `ExperimentValidatePhase` — LLM verdict + write DB
7. Wire nel pipeline `study_agent.py` + test end-to-end
8. Layer E in `cognition_core.py` — last, dipende da DB popolato

---

## Vincolo critico (sandbox)

`minimum_experiment` dall'LLM può contenere istruzioni irrealizzabili in sandbox
(es. "scarica CIFAR-10", "usa GPU"). Il prompt di `_generate_experiment_code()` deve
includere un pre-check: se il minimum_experiment richiede risorse esterne,
`ExperimentDesignPhase` setta `ctx.experiment_status = "SKIPPED_TOO_COMPLEX"`.
Il codice generato deve simulare il principio dell'ipotesi su scala toy con dati sintetici.
