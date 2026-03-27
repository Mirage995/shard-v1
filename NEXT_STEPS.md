# SHARD — Next Steps
Last updated: 2026-03-27 (SSJ14)

---

## Stato attuale

SSJ14 completato. CognitionCore bus completo con 14 cittadini bidirezionali.
Moduli attivi: MoodEngine, IdentityCore, SkillLibrary, HebbianUpdater, SelfModelTracker, PrerequisiteChecker.
Comportamenti emergenti osservati: fobia asyncio, comfort zone, curiosità paradossale sotto fallimento, predittore calibrato.

---

## Priority 1 — Strategic Forgetting (MemoryPruner)

ChromaDB (inner_thoughts/conversations) e session_reflections.jsonl crescono indefinitamente.
Dopo N sessioni il context injection si riempie di rumore.

**Fix:**
- `MemoryPruner` a fine sessione: rimuove record ChromaDB con score basso o duplicati semantici
- `session_reflections.jsonl`: tieni ultime 10 + 5 con contenuto più diverso (diversity sampling)
- Soglia: record > 90 giorni o rilevanza < 0.3 → candidato pruning

---

## Priority 2 — Curiosity loop fix

`update_curiosity()` dopo `skill_certified` alza la pull sullo stesso topic invece che su topic adiacenti.
Risultato osservato: SHARD ri-studia ciò che sa già (union find 3× di fila).

**Fix:** in `update_curiosity`, azzerare pull se topic già certificato nel capability_graph.
Alzarla invece sui topic semanticamente vicini via GraphRAG `extends`/`improves`.

---

## Priority 3 — Coverage 60%+

Stima attuale ~50%. Moduli non coperti: night_runner, swarm_engine, session_orchestrator.
Test suite: 448 pass, 5 skip, 0 fail (ultimo run 2026-03-24).

---

## Priority 4 — Capability Graph consolidation

~175 capability. Soglia critica per emergenza ~300-400.
`capability_consolidator.py`: embed → cluster → merge sinonimi → gerarchia.

---

## Priority 5 — ROI Benchmark run completo

N run con provider diversi (Claude, Gemini, Groq/LLaMA), statistiche comparative documentate.
Obiettivo: dimostrare valore architettura multi-provider vs singolo modello.

---

## Note tecniche accumulate

### Comportamenti emergenti osservati (run 2026-03-27)
- Fobia da asyncio: VISION lo ha inserito in avoid_domains dopo 3+ fallimenti
- Comfort zone: union find selezionato 3× di fila via curiosity_driven
- Curiosità paradossale: curiosity_pull saliva dopo fallimento (Zeigarnik effect)
- Predittore calibrato: SelfModelTracker predice 0.0 su asyncio dopo storia negativa

### Architettura cross-modulo (SSJ14)
- mood_shift broadcast → 5 moduli reagiscono autonomamente
- identity_updated → 2 moduli adattano il baseline predittivo
- frustrated mood → hebbian decay → reset pattern di fallimento
- skill_certified → skill_library salva → curriculum suggestions disponibili
