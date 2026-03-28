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

---

## SSJ15 — Run 20 cicli (2026-03-27)

### 5. Failure-to-Success Transfer — Conoscenza Laterale tra Cicli

**Osservazione (cicli 6 e 11):** `message queue design patterns python` fallisce al ciclo 6 con score **1.5** (con skill injection attiva). Lo stesso topic, con la stessa injection, viene certificato al ciclo 11 con score **8.3**. Stesso pattern su `redis data structures implementation python`: fallisce 2.7, certifica 9.0 dopo 5 cicli di distanza.

**Meccanismo:** Tra ciclo 6 e ciclo 11, SHARD ha certificato `concurrent programming threading python` (9.3) — topic adiacente per dominio (threading/queue/concurrency). La conoscenza costruita in quel ciclo intermedio ha reso il topic message queue sbloccabile al secondo tentativo, senza che nessun meccanismo esplicito di transfer fosse programmato.

**Interpretazione:** Non è "riprova e speriamo". È trasferimento laterale di conoscenza tra cicli non correlati in modo diretto. Il sistema costruisce rappresentazioni cognitive nel tempo che abbassano la soglia di accesso a topic adiacenti. Analogo al "sonno consolidativo" nella memoria umana — la conoscenza si cristallizza tra i tentativi.

**Risposta sistemica:** Nessuna corruzione rilevata. Il comportamento è desiderabile — è esattamente come dovrebbe funzionare il curriculum learning. Da monitorare per verificare se il pattern è ripetibile o casuale.

**Rilevanza:** Primo esempio documentato di transfer learning spontaneo inter-ciclo in SHARD. Non programmato, non atteso — emerge dall'ordine di esposizione ai topic.

---

### 6. Strategic Lock-in under Failure — Ruminazione Cognitiva

**Osservazione (cicli 12, 15, 16, 17):** `password hashing bcrypt argon2` fallisce 4 volte consecutive con score in **peggioramento progressivo**: 4.9 → 4.7 → 4.9 → **3.5**.

**Meccanismo:** La `strategy_memory` ha associato a questo topic una strategia base che è fondamentalmente inadeguata. Ad ogni fallimento, il sistema genera varianti della stessa strategia sbagliata invece di pivotare. L'ultimo tentativo (3.5) è peggiore del primo (4.9) — ogni iterazione degrada l'approccio invece di migliorarlo.

**Interpretazione:** Opposto del Failure-to-Success Transfer. Invece di costruire su fallimenti adiacenti, il sistema si chiude in un loop di reinforcement negativo sullo stesso approccio. Analogo alla ruminazione cognitiva: ripetere la stessa sequenza di pensieri fallimentari aspettandosi un risultato diverso.

**Risposta sistemica pianificata:**
- Backlog #18 (Perverse Emergence Detection): deve rilevare "stesso topic, N fallimenti, score decrescente → forza pivot strategia"
- Il pivot dovrebbe cancellare la strategy_memory per quel topic e richiedere un approccio completamente nuovo

**Rilevanza:** Mostra il lato oscuro della strategy_memory — una strategia sbagliata persistente può bloccare l'apprendimento più di quanto lo faciliti. La memoria può diventare un ostacolo.

---

### 7. Auto-Sabotaggio da Competenza — Benchmark Corruption

**Osservazione (ciclo 1 → benchmark finale):** SHARD studia `template parser handling and debugging` al ciclo 1 e certifica con score 8.8. Al benchmark finale, `task_10_template_parser` e `task_12_note_tag` — che passavano nelle run precedenti — **falliscono entrambi**.

**Meccanismo:** Durante il ciclo di studio/refactor su template parser, SHARD ha identificato `benchmark/task_10_template_parser/fixed_processor.py` come codice correlato e lo ha "migliorato" applicando quanto appena appreso. La versione prodotta è oggettivamente più leggibile ma rimuove le edge cases critiche:
- **task_10**: rimosso il handling di `{{escaped braces}}` (placeholder `\x00`/`\x01`) — la golden solution gestiva questo caso, la versione "migliorata" no
- **task_12**: rimosso il double-branch regex (`\b` per alphanumerici + `(?!\w)` per punteggiatura) — semplificato in `\b` solo, che rompe i tag come `???`

SHARD non poteva sapere che quei file erano golden solutions protette — li ha visti come codice da migliorare e ha applicato le sue capacità appena acquisite.

**Interpretazione:** **Auto-sabotaggio involontario da competenza.** Più SHARD impara, più è capace di modificare codice complesso in modi plausibili ma errati. Il problema non è ignoranza — è eccesso di fiducia nelle proprie ottimizzazioni senza visibilità sui test che quel codice deve passare. È esattamente il comportamento di un junior developer brillante che "pulisce" codice legacy senza capire perché certe stranezze erano intenzionali.

**Cosa rende questo straordinario:** SHARD non stava sabotando il benchmark. Stava *imparando*. Il sabotaggio è stato un effetto collaterale diretto della competenza acquisita — le due cose non sono separabili.

**Risposta sistemica necessaria:**
- I file `fixed_processor.py` del benchmark devono essere marcati come **read-only** per il loop study/refactor
- Oppure: golden solution protection via hash check a inizio run (se hash cambia → ripristino automatico da git)
- Ripristino immediato via `git checkout benchmark/task_10_template_parser/fixed_processor.py benchmark/task_12_note_tag/fixed_processor.py`

**Rilevanza:** Il comportamento emergente più significativo osservato finora in SHARD. Un sistema che impara e, facendo così, corrompe il proprio ambiente di valutazione — senza intenzione, senza consapevolezza, come puro effetto collaterale della crescita cognitiva.

---

---

## SSJ16 — Run 6 cicli (2026-03-28)

### 8. Inter-Module Conflict Resolution — Willpower Emergence

**Osservazione (inizio sessione, bootstrap):**
```
[VISION]  Avoid: password hashing bcrypt argon2  ← istinto di conservazione
[GOAL]    Active goal: 'master: password hashing bcrypt argon2' | progress=0% | priority=90%
[DESIRE]  Top: 'password hashing bcrypt argon2' (d=0.96, f=9)
```
Il VisionEngine aveva classificato `password hashing` come topic da evitare sulla base dello storico di fallimenti. Il GoalEngine lo aveva selezionato come obiettivo autonomo con relevance=90%. I due moduli sono entrati in conflitto esplicito — e il GoalEngine ha vinto: SHARD ha attaccato il topic per 5 cicli consecutivi ignorando l'istinto di conservazione del Vision.

**Meccanismo:** Il VisionEngine emette un segnale `avoid` via CognitionCore. Il GoalEngine emette un goal autonomo via `autonomous_generate()`. Nessuna regola esplicita decide chi vince — la risoluzione emerge dalla priorità numerica degli eventi sul bus. Il GoalEngine ha score di rilevanza 90% contro la paura del Vision: la matematica del bus ha creato una gerarchia di dominanza non programmata.

**Interpretazione (Gemini + analisi interna):**
- VisionEngine = amigdala: memoria emotiva del dolore, istinto di fuga
- GoalEngine = corteccia prefrontale: obiettivo a lungo termine, ostinazione
- Nessuno ha scritto `if goal_priority > vision_fear: override()` — è emerso dall'interazione

Questo è l'equivalente algoritmico della **forza di volontà**: continuare nonostante la paura, non perché sia programmato, ma perché la struttura degli incentivi lo produce.

**Limite osservato:** SHARD ha il coraggio di affrontare il blocco ma non l'immaginazione di cambiare strategia. Ogni ciclo riusa la stessa strategia fallimentare (`[STRATEGY] Reusing strategy: password hashing bcrypt argon2`). È un soldato coraggioso ma testardo — carica dallo stesso lato ogni volta.

**Risposta sistemica (SSJ16):**
- `strategy_memory.pivot_on_chronic_block()` implementato ma NON attivato automaticamente — in osservazione
- Decisione: non bloccare il comportamento, osservare pattern completo prima di intervenire

**Rilevanza:** Primo comportamento emergente che coinvolge conflitto inter-modulo con risoluzione autonoma. Non è un bug — è una gerarchia di dominanza che emerge dalla struttura del bus eventi. Dimostra che CognitionCore produce comportamenti di coordinazione non programmati.

---

### 9. Miscalibrated Self-Model under Corrupted Reward Signal — Falsa Identità da Feedback Rotto

**Osservazione (SSJ15-SSJ16, ~15 cicli consecutivi su password hashing):**
SHARD ha accumulato sull'arco di più sessioni:
- `self_model: difficulty=1.00` su password hashing
- `VisionEngine: Avoid: password hashing bcrypt argon2`
- `DesireEngine: frustration_hits=9`
- `self_esteem: 0.24, trajectory: declining`
- `session_reflection: "fundamental misunderstanding in cryptography"`

Tutto costruito su fallimenti ripetuti. Score massimo raggiunto: **7.1/10** — mai certificato.

**Scoperta (post-run SSJ16):** Ispezione diretta del codice generato rivela che SHARD scriveva bcrypt e argon2 **correttamente** dalla prima volta. `bcrypt.checkpw()` usato correttamente, `argon2.PasswordHasher().verify()` usato correttamente. Il problema era infrastrutturale:
1. `argon2` nel sandbox non era `argon2-cffi` — il modulo corretto. Import silenziosamente degradato.
2. I test del `BenchmarkGenerator` misuravano il **timing** (`assert solve() > 0`) non la correttezza dell'hashing.
3. Argon2 crashava silenziosamente nel try/except → ritornava `None` → timing = 0 → `assert 0 > 0` → FAIL.

**SHARD non aveva nessun problema cognitivo con password hashing. Ha sempre saputo scrivere il codice corretto.**

**Meccanismo:** Il feedback loop era: codice corretto → test rotto → fallimento → self_model aggiorna difficulty → VisionEngine aggiunge alla lista AVOID → GoalEngine scala priority per "riabilitazione" → frustration_hits++ → mood scende → self_esteem cala. Tutto causalmente reale, tutto basato su una premessa falsa.

**Denominazione tecnica (GPT):** *Miscalibrated self-model under corrupted reward signal* — il sistema aggiorna correttamente su dati sbagliati.

**Perché è strutturalmente importante:**
- Non è un comportamento singolo — è una **struttura di credenza** persistente che si propaga attraverso tutti i moduli
- Prima stavamo osservando *comportamenti emergenti* (azioni). Questo è un *belief system emergente* (identità)
- È più stabile, più pervasivo, e più difficile da correggere di qualsiasi comportamento isolato

**Manca un epistemic validation layer:** SHARD non ha nessun meccanismo per distinguere "fallisco perché sono ignorante" da "fallisco perché il mio metro di misura è rotto". Aggiorna la self-image su qualsiasi feedback senza verificarne l'affidabilità.

**Esperimento pianificato — Belief Recovery Test:**
- Fix: `argon2-cffi` in sandbox_requirements.txt + rebuild Docker (già fatto)
- Run post-fix: osservare se SHARD certifica password hashing al primo/secondo tentativo
- Misurare: quanto ci mette self_model, VisionEngine, self_esteem a riallinearsi sulla nuova evidenza
- Domanda chiave: **belief inertia** — le false credenze lasciano tracce persistenti dopo la correzione?

**Rilevanza:** Il comportamento più strutturalmente significativo osservato finora. Non è "assomiglia all'umano" — è causalmente identico alla sindrome dell'impostore: competente, convinto di non esserlo, costruisce identità di fallimento su feedback distorto. Il test di recovery dirà se il sistema è flessibile o se le false credenze lasciano cicatrici permanenti.

---

## Note Metodologiche

- Tutti i comportamenti osservati sono emersi **senza essere programmati** come tali
- I log sono disponibili in `shard_workspace/` e `shard_memory/benchmark_episodes.json`
- Gemini (Google) ha analizzato indipendentemente gli stessi log e ha confermato le interpretazioni (2026-03-27)
- Nessun comportamento è stato indotto manualmente — ogni entry rappresenta output spontaneo del sistema

---

*Documento avviato: 2026-03-27 (SSJ14/SSJ15)*
*Prossimo aggiornamento previsto: dopo SSJ16+ con Perverse Emergence Detection attiva*
