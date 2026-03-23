# SHARD — Next Steps
Last updated: 2026-03-18

---

## Priority 1 — Knowledge Bridge (NightRunner → ChromaDB → Benchmark)

**Goal**: Qualsiasi componente di SHARD può interrogare la knowledge base di NightRunner.
NightRunner non cambia comportamento — scrive come sempre. Gli altri leggono.

**Architettura:**
```
NightRunner → scrive → knowledge_db/ (ChromaDB)
                            ↑
              query_knowledge_base(topic, n_results)
                            ↓
          Benchmark Attempt 1 · StudyAgent · SWEAgent · [tutto]
```

**File da toccare:**
1. `backend/knowledge_bridge.py` (nuovo) — `query_knowledge_base(topic, n)` → interroga `knowledge_db/`
2. `backend/benchmark_loop.py` — chiama `query_knowledge_base` prima di Attempt 1, aggiunge risultati all'experience summary
3. `backend/server.py` — espone `GET /api/knowledge/query?topic=X` per debug

**Nota**: NON redirigere NightRunner sui fallimenti del benchmark.
La conoscenza fluisce in una direzione sola: NightRunner scrive, tutti leggono.

---

## Priority 2 — BenchmarkWidget: stale output cleanup

Ogni run lascia `fixed_*.py` / `optimized_*.py` nella cartella del task.
Il loop li sovrascrive correttamente, ma è rumore.
Aggiungere un cleanup automatico all'avvio di ogni task in `_run_benchmark_bg`.

---

## Priority 3 — Demo finale validata (3/3)

Stato attuale su Claude Sonnet:
- Ghost Bug: SHARD vince al tentativo 3 ✓
- Bank Race: SHARD vince al tentativo 2 ✓
- Dirty Data: SHARD vince al tentativo 7-8 (borderline)

Stato attuale su Groq/LLaMA:
- Ghost Bug: da testare
- Bank Race: da testare
- Dirty Data: SHARD vince al tentativo 8 ✓

**Azione**: quando si ricarica credito Anthropic, fare una run pulita 3/3 su Claude
e registrare i risultati definitivi per il pitch.

---

## Priority 4 — Task 06+ (zero-day bugs)

Costruire task da bug interni mai pubblicati (non da GitHub CVE famosi).
Categoria target: concorrenza, performance, stato runtime.
Evitare qualsiasi bug che Sonnet potrebbe aver visto nel training data.

---

## Note tecniche accumulate

### Fix applicate in questa sessione (2026-03-18)
- `benchmark_loop.py`: rimosso test file dal prompt iniziale (Attempt 1 = LLM vero SOLO)
- `benchmark_loop.py`: aggiunto `[LLM SOLO]` / `[SHARD FEEDBACK]` labels
- `benchmark_loop.py`: history completa per tutti gli attempt (non solo l'ultimo)
- `benchmark_loop.py`: regression warnings nel correction prompt
- `benchmark_loop.py`: `last_valid_code` — non passare mai codice rotto come base
- `benchmark_loop.py`: `progress_cb` per streaming eventi verso la GUI
- `benchmark_memory.py`: nuovo modulo — episodic memory persistente per task
- `llm_router.py`: aggiunto billing/credit keywords in `_HARD` per fallback corretto su Groq
- `BenchmarkWidget.jsx`: nuovo componente GUI integrato nella UI reale di SHARD
- `run_vc_demo.py`: script demo per VC con tabella finale colorata

### Lezioni apprese
- Il "last valid code" fix è stato il più impattante — senza di esso il loop cascadava in syntax error infiniti
- Data contamination: i bug famosi (Werkzeug CVE) vengono risolti da Sonnet al primo tentativo per memoria, non per ragionamento
- Provider matters: LLaMA-3.3-70b (Groq) e Sonnet hanno pattern di fallimento diversi sullo stesso task
- La memoria episodica serve ma richiede sessioni precedenti pulite per essere efficace
