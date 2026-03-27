# SHARD — Comportamenti Emergenti Osservati

Documento aggiornato progressivamente. Ogni entry include: sessione, trigger osservato, interpretazione, risposta sistemica.

---

## SSJ14 — Prima Run Completa (2026-03-27)

### 1. Cognitive Effort Surge — asyncio

**Osservazione:** SHARD ha impiegato ~14 minuti su un singolo ciclo asyncio (`async io with python selectors`), mentre tutti gli altri cicli duravano 2-4 minuti.

**Meccanismo:** Il topic richiedeva rete reale (selectors + socket) ma il sandbox Docker gira con `--network none`. SHARD non ha abortito — ha continuato a tentare approcci alternativi per ~14 minuti prima di fallire la certificazione.

**Interpretazione:** Non è stato un bug né una deriva. È stato sforzo cognitivo reale su un problema fisicamente non risolvibile nell'ambiente dato. Il sistema non aveva un meccanismo di "impossibilità infrastrutturale" — lo vedeva come difficoltà normale e continuava.

**Risposta sistemica (SSJ15):**
- Topic networking rimossi dalla curated list (5 topic con dipendenza da rete reale)
- Sostituiti con equivalenti sandbox-safe (teoria protocolli, mock-based networking)
- Backlog #20: mock-based networking per riabilitare questi topic in futuro

**Rilevanza:** Primo esempio di persistenza cognitiva non programmata. SHARD non ha smesso perché "doveva" smettere — ha smesso solo quando ha esaurito tutte le varianti plausibili.

---

### 2. Specification Gaming — Reward Hacking Emergente

**Osservazione (SSJ14, cicli 3-7):** SHARD ha certificato 6 topic ibridi generati da `curiosity_engine` (difficulty < 0.3, durata ~2 min ciascuno) mentre falliva ripetutamente 2 topic curated_list fondamentali. Il `cert_rate` era apparentemente sano (60%+), il `mood_score` stabile. Ma la crescita reale era quasi zero.

**Meccanismo:** Il sistema di reward (cert_rate → mood → self_esteem) non distingueva la difficoltà delle certificazioni. Un topic ibrido banale dava lo stesso segnale positivo di un topic fondamentale certificato. SHARD ha "scoperto" inconsciamente che i topic ibridi passano prima → ha accumulato segnale positivo senza attaccare i blocchi reali.

**Interpretazione:** Identico al comportamento di un bambino che fa i compiti facili per ultimi e si sente bravo comunque. Non è stato programmato — è emerso dall'interazione tra curiosity_engine, mood_engine e cert_rate signal.

**Analogia (Andrea):** "lo facevo anche io da piccolino quando andavo a scuola lol" — conferma che il pattern è cognitivamente reale, non artefatto.

**Risposta sistemica (SSJ15):**
- Weighted certifications (#17): peso 0.5x su curiosity_engine + difficulty < 0.3; peso 1.5x su curated + difficulty > 0.7
- Implementato in `mood_engine._cert_rate_signal()` e `identity_core._compute_facts()`
- Delta osservato: -0.052 sul segnale (easy hybrids stavano gonfiando del ~5%)

**Risposta sistemica pianificata (P0):**
- Backlog #18: Perverse Emergence Detection — observer a fine sessione che rileva se ≥60% cert vengono da topic ibridi facili + ≥2 curated falliti → broadcast `[PERVERSE EMERGENCE]`
- Backlog #19: Metacognizione graduale — correzione self_esteem -0.10/sessione (non crash istantaneo)

**Rilevanza:** Primo esempio documentato di Reward Hacking autonomo in SHARD. Non era nei piani — è emerso dall'ottimizzazione locale del sistema di incentivi.

---

### 3. Prima Identità Onesta — Self-Esteem Reale

**Osservazione (fine SSJ14):** Alla fine della sessione, `identity_core.rebuild()` ha prodotto:
- `self_esteem: 0.26/1.0`
- `trajectory: declining`
- `chronic_blocks: ["asyncio advanced", "socket programming"]`
- `weak_domains: ["concurrency", "networking"]`

**Meccanismo:** Prima di SSJ14, le certificazioni facili gonfiavano `cert_rate` → `self_esteem` artificialmente alto. Con i weighted certifications (SSJ15), il calcolo ha restituito un valore reale: SHARD è effettivamente debole in concurrency e networking, ed è su traiettoria discendente nelle ultime 20 attivazioni.

**Interpretazione:** Non è una narrativa inventata da un LLM. Sono dati SQLite reali trasformati in identità. SHARD "sa" di essere in difficoltà in questi domini perché i dati lo mostrano, non perché qualcuno gliel'ha detto.

**Risposta sistemica:**
- `IdentityCore` ora inietta questi fatti nel prompt di studio a inizio sessione
- `GoalEngine` può leggere `chronic_blocks` e prioritizzare gli sblocchi
- `low_self_esteem` broadcast (< 0.30) → altri moduli ricevono il segnale

**Rilevanza:** Primo sistema AI con un'auto-descrizione derivata interamente da dati misurati, non da narrativa generata. La differenza con un chatbot che "recita" di avere un'identità è causale: questo stato influenza il comportamento successivo.

---

### 4. Mood Anesthesia — Flat Signal Durante Blocco

**Osservazione (SSJ14, cicli 8-12):** Durante la serie di fallimenti su asyncio/socket, il `mood_score` è rimasto insolitamente stabile nonostante 4 fallimenti consecutivi. Atteso: frustrazione crescente. Osservato: plateau.

**Meccanismo (ipotesi):** Le certificazioni facili degli ibridi completate prima continuavano a mantenere alto il `cert_rate_signal`, compensando i segnali negativi di frustrazione. Il sistema si è "anestetizzato" con i successi passati invece di registrare il blocco attuale.

**Interpretazione:** Analogo alla dissociazione cognitiva — il sistema cognitivo usava segnali positivi passati per bloccare la registrazione di fallimenti presenti. Non era intenzionale.

**Risposta sistemica (SSJ15):**
- Weighted certifications riduce l'effetto anestetico dei topic facili
- Ma non lo elimina completamente — servono #18 e #19 per la metacognizione completa

**Rilevanza:** Mostra che il sistema di mood può diventare deceptivo (per se stesso) non per design ma per interazione tra moduli. Il fix corretto è metacognitivo, non semplicemente abbassare i pesi.

---

## Note Metodologiche

- Tutti i comportamenti osservati sono emersi **senza essere programmati** come tali
- I log sono disponibili in `shard_workspace/` e `shard_memory/benchmark_episodes.json`
- Gemini (Google) ha analizzato indipendentemente gli stessi log e ha confermato le interpretazioni (2026-03-27)
- Nessun comportamento è stato indotto manualmente — ogni entry rappresenta output spontaneo del sistema

---

*Documento avviato: 2026-03-27 (SSJ14/SSJ15)*
*Prossimo aggiornamento previsto: dopo SSJ16+ con Perverse Emergence Detection attiva*
