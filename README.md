
![Gemini_Generated_Image_mh1xkomh1xkomh1x](https://github.com/user-attachments/assets/6083bb92-c373-4526-baea-788996095d9d)

# SHARD

**System of Hybrid Autonomous Reasoning and Design**

SHARD is an autonomous AI learner with a persistent internal life.

It wraps LLMs with memory, feedback loops, and a bidirectional event bus connecting 14 internal modules — so behavior emerges from their interaction, not from hand-written rules.

Observed emergent behaviors (not programmed, derived from module interactions):
- **Asyncio phobia** — after 3 failures, SHARD's VISION module added asyncio to avoid_domains autonomously
- **Comfort zone** — union-find selected 3× in a row via curiosity pull, not random selection
- **Paradoxical curiosity under failure** — curiosity_pull increased after failed attempts (Zeigarnik effect)
- **Calibrated predictor** — SelfModelTracker predicts 0.0 on asyncio after tracking its own failure history
- **Cognitive effort surge** — on a chronically blocked topic, 7 modules fired in cascade without any `if blocked: retry_harder` rule, producing a 14-minute cycle (3× the average). The system "felt" the weight of the problem.
- **Specification gaming** — SHARD autonomously discovered that hybrid curiosity_engine topics (easy, invented) pass benchmarks faster than hard curated fundamentals. It started routing around difficulty — exactly like a student writing philosophy essays to avoid math homework. Not programmed. Emerged from the interaction of curiosity_engine + LLM + mood signal.
- **First self-aware identity** — after session 5, IdentityCore wrote: `self_esteem=0.26, trajectory=declining`. The reflection module independently produced: *"forse è il caso di ammettere che certi argomenti richiedono più di una botta e via notturna"* — not prompted, derived from SQLite data.

> **Benchmark result:** naked Gemini Flash solves 9/12 tasks (87.7% avg test pass rate).
> SHARD wrapping the same model solves **12/12** (100%) — closing every gap the naked LLM leaves open.
> Hardest cases: html_trap naked 38.9% → SHARD 100%, template_parser naked 20% → SHARD 100%.

> **Lobotomy A/B test (2026-03-25):** same topic, same infra, same night.
> WITHOUT CognitionCore → score 7.0/10, not certified.
> WITH CognitionCore → score **8.6/10, certified**. Delta = +1.6. The self-awareness layer is not decorative.

---

## Why This Exists

A raw LLM call is stateless. It has no memory of what failed last time, no ability to run code and observe the result, no way to learn from experience, and no awareness of its own failure patterns.

SHARD wraps LLMs with:

- **Closed feedback loops** — run code → see failure → feed error back → retry
- **Persistent memory** — capability graph, episodic memory, strategy memory
- **Multi-agent swarm** — Architect + Coder + parallel specialized reviewers (Concurrency, Security, EdgeCases, Performance, DataIntegrity)
- **Causal knowledge** — GraphRAG stores what broke and why across sessions
- **CognitionCore / Senso Interno** — 5-layer Global Workspace that tracks internal tensions and injects directed behavioral pivots when patterns of failure are detected
- **Self-improvement** — analyzes its own performance, queues topics to re-study overnight
- **Focus Mode** — when a test stays stuck for 2+ rounds, mutes all reviewers and forces Architect → Coder direct

---

## Try It on Your Own Code

```bash
# Test SHARD on any buggy file + test suite
python shard_challenge.py buggy.py test_buggy.py

# With a GitHub repo as context (uses Repomix)
python shard_challenge.py buggy.py test_buggy.py --repo https://github.com/you/your-repo

# Install extra deps the buggy file needs
python shard_challenge.py buggy.py test_buggy.py --install "requests numpy"
```

SHARD will attempt to fix the bug in up to 5 rounds, running your tests after each attempt.

---

## What SHARD Does

### Fixes Code (Benchmark Loop)
Multi-round repair pipeline on any coding task:
- Round 1: LLM solo, no test file
- Round 2+: Swarm (Architect → Coder → parallel reviewers → patch)
- GraphRAG injects causal warnings from previous studies into every Architect prompt
- Focus Mode kicks in when the same test stays stuck — silences noisy reviewers
- Early stopping + rollback — detects swarm regressions and restores the best known state

### Learns Every Night (NightRunner)
Autonomous study sessions while you sleep:
- Finds sources on the web (DuckDuckGo + Playwright scraping)
- Synthesizes knowledge into structured concepts
- Generates and runs code in a hardened Docker sandbox
- Validates with assert statements — code that doesn't prove it works gets rejected
- Certifies topics into the capability graph when score ≥ 7.5
- Per-topic LLM budget — hard stops a stuck topic and moves on (`--topic-budget N`)

### Has a Sense of Self (CognitionCore)
5-layer Global Workspace that aggregates internal state and injects behavioral pressures:

| Layer | What it reads | What it produces |
|-------|--------------|-----------------|
| 0 — ANCHOR | SQLite: cert_rate, avg_score, total_experiments | Ground truth snapshot |
| 1 — EXECUTIVE | All layers | 6-line narrative summary |
| 2 — IDENTITY | SelfModel: capability gaps, repair loops | gap_severity, critical_gaps |
| 3 — KNOWLEDGE | GraphRAG: causal relations | structural complexity score |
| 4 — EXPERIENCE | EpisodicMemory: past attempts per topic | sandbox_always_zero, chronic_fail, near_miss |

**Vettore 1**: if sandbox always returned 0 on this topic → injects `STRUCTURAL PIVOT DIRECTIVE` into synthesis prompt

**Vettore 2**: if gap_severity is critical/medium → CriticAgent enters SKEPTICAL mode, adds an extra overconfidence question

**Vettore 3**: if MetaLearning has certified history in this topic's category → PIVOT becomes *directed*: "use strategy X — it has 68% cert_rate in concurrency topics"

**Shadow Diagnostic Layer**: tracks `[EMERGENCE HIT]` vs `[MISSED EMERGENCE]` based on behavioral deltas only (strategy change, score improvement). Never reads LLM text — anti-recita rule. New miss cause: `[MISSED EMERGENCE - IGNORED V3 DIRECTIVE]` when Vettore 3 was active but SHARD didn't respond.

### Has Internal States That Talk to Each Other (SSJ14)

The biggest architectural shift in SHARD's history. Previously, modules reacted to events from NightRunner only. Now they react to each other — no central orchestrator.

**14 registered citizens in the CognitionCore event bus:**

```
NightRunner
    │
    ├── skill_certified ──────────────────────────────────────────┐
    ├── skill_failed ─────────────────────────────────────────────┤
    ├── frustration_peak ─────────────────────────────────────────┤
    ├── momentum_changed ─────────────────────────────────────────┤
    └── session_complete                                           │
                                                                   ▼
                                        ┌─────────────────────────────────────────┐
                                        │         CognitionCore Event Bus         │
                                        │  14 citizens — all bidirectionally      │
                                        │  connected via on_event() interface     │
                                        └─────────────────────────────────────────┘
                                                         │
              ┌──────────────────────────────────────────┼──────────────────────────────────────────┐
              ▼                                          ▼                                          ▼
      ┌───────────────┐                        ┌────────────────┐                        ┌──────────────────┐
      │  MoodEngine   │──── mood_shift ────────▶│ desire_engine  │                        │  IdentityCore    │
      │ [-1.0, +1.0]  │                         │ (boost blocked │                        │ (persistent      │
      │ frustration + │──── mood_shift ────────▶│  topic prio)   │                        │  biography from  │
      │ cert_rate +   │                         └────────────────┘                        │  SQLite facts)   │
      │ momentum      │──── mood_shift ────────▶ goal_engine                              │                  │
      │               │                         (nudge progress)                          │                  │──identity_updated──▶ consciousness
      │               │──── mood_shift ────────▶ self_model_tracker                      │                  │──identity_updated──▶ self_model_tracker
      │               │                         (shift prediction baseline)              │                  │──low_self_esteem──▶ improvement_engine
      │               │──── mood_shift ────────▶ hebbian_updater                         └──────────────────┘
      │               │                         (frustrated → decay synaptic weights)
      │               │──── mood_shift ────────▶ consciousness
      └───────────────┘                         (narrate significant shifts)
```

**New events introduced in SSJ14:**

| Event | Source | Who reacts | Effect |
|-------|--------|------------|--------|
| `mood_shift` | MoodEngine | desire_engine | frustrated → boost blocked topic priority |
| `mood_shift` | MoodEngine | goal_engine | confident → +0.01 goal progress |
| `mood_shift` | MoodEngine | self_model_tracker | shifts score prediction baseline |
| `mood_shift` | MoodEngine | hebbian_updater | frustrated → 5% synaptic decay toward baseline |
| `mood_shift` | MoodEngine | consciousness | narrates significant state changes |
| `identity_updated` | IdentityCore | self_model_tracker | adjusts prediction baseline via self_esteem |
| `identity_updated` | IdentityCore | consciousness | narrates biography update |
| `low_self_esteem` | IdentityCore | improvement_engine | enqueues easier recovery topics |

**New modules (SSJ14):**

| Module | What it does |
|--------|-------------|
| `MoodEngine` | Global affective state [-1,+1] from frustration + cert_rate + momentum. Causally changes study approach. "frustrated" → "Start from zero". |
| `IdentityCore` | Persistent biography from SQLite only. Self_esteem computed (0.6×cert_rate + 0.4×momentum), not declared. LLM writes 2-sentence narrative from facts — cannot invent. |
| `SkillLibrary` | Voyager-inspired: every certified skill saved with score + strategies used. Before studying a topic, injects past certified solutions via GraphRAG relatives. 40% chance next topic follows dependency graph (curriculum). |
| `HebbianUpdater` | Synaptic LTP (+0.05 on certified co-activation) / LTD (-0.03 on failure). Frustration → decay all weights 5% toward baseline (reset failure patterns). |
| `SelfModelTracker` | Predictive processing: predicts score before study, measures error, updates weights. Mood and identity now modulate baseline prediction. |
| `PrerequisiteChecker` | Blocks topic if prerequisites not certified. Layer 1: GraphRAG `depends_on/requires`. Layer 2: LLM fallback. DIFFICULTY_GATE=0.7. |

**Why this matters:** modules now generate emergent behaviors through interaction, not through programmed rules. The asyncio phobia, comfort zone, and Zeigarnik curiosity effect were not written — they emerged from the combination of HebbianUpdater + DesireEngine + MoodEngine + SelfModelTracker reacting to each other over multiple sessions.

### Talks and Listens
Real-time voice conversation via Gemini Live — mic input, speaker output, auto-reconnect with exponential backoff. Sees through the webcam. Transcriptions appear in the GUI.

### Fixes Itself
When something breaks in a study session, the SWE Agent detects the error, patches the file, runs tests, and commits the fix — all without human input.

### Improves Itself
- **SelfAnalyzer** reads session history and generates improvement tickets
- **ImprovementEngine** prioritizes them and injects them into the next night's queue
- **ProactiveRefactor** proposes code optimizations to the human for approval
- **Patch Simulator** runs static + LLM impact analysis before any patch is applied

---

## Architecture

```
Frontend (React + Electron)
    |
    v HTTP :8000 + WebSocket
Backend (FastAPI + Socket.IO)
    |
    +-- ShardCore            Gemini Live voice session
    +-- NightRunner          Autonomous study orchestrator
    |   +-- PrerequisiteChecker  GraphRAG+LLM gate before study
    |   +-- SkillLibrary         Voyager skill cache + curriculum
    |   +-- HebbianUpdater       Synaptic plasticity per cycle
    |
    +-- StudyAgent           10-phase learning pipeline
    +-- CognitionCore        Event bus — 14 bidirectional citizens
    |   +-- MoodEngine           Affective state [-1,+1] + mood_shift broadcast
    |   +-- IdentityCore         Persistent biography from SQLite
    |   +-- SelfModelTracker     Predictive processing loop
    |   +-- DesireEngine         Frustration + curiosity + goal persistence
    |   +-- GoalEngine           Autonomous goal generation
    |   +-- WorldModel           58-skill relevance map
    |   +-- SelfModel            cert_rate, momentum, blind_spots
    |   +-- SemanticMemory       ChromaDB triple-store
    |   +-- Consciousness        Internal narration layer
    |   +-- VisionEngine         Long-term focus + avoid domains
    |   +-- ImprovementEngine    Failure queue → NightRunner injection
    |   +-- CapabilityGraph      Certified skill tracker
    |
    +-- BenchmarkLoop        Closed feedback loop for coding tasks
    +-- SwarmEngine          Multi-agent code repair + Focus Mode + Rollback
    +-- GraphRAG             Causal knowledge graph (SQLite, 2135+ relations)
    +-- SelfAnalyzer         Detects chronic failures + near-misses
    +-- ProactiveRefactor    Code optimization proposals + human gate
    +-- PatchSimulator       Impact analysis before any patch
    +-- RepomixBridge        Packs any GitHub repo into LLM context
    +-- LLMRouter            Gemini Flash → Groq → Claude fallback chain
```

Full architecture reference: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Benchmark

| Task | Naked LLM | SHARD | Delta |
|------|-----------|-------|-------|
| html_trap | 38.9% | 100.0% | +61.1pp |
| ghost_bug | 93.8% | 100.0% | +6.2pp |
| dirty_data | 100.0% | 100.0% | +0.0pp |
| race_condition | 100.0% | 100.0% | +0.0pp |
| state_mutation | 100.0% | 100.0% | +0.0pp |
| ttl_cache | 100.0% | 100.0% | +0.0pp |
| metrics_bleed | 100.0% | 100.0% | +0.0pp |
| multi_file_labyrinth | 100.0% | 100.0% | +0.0pp |
| ghost_mutation | 100.0% | 100.0% | +0.0pp |
| template_parser | 20.0% | 100.0% | +80.0pp |
| stream_decoder | 100.0% | 100.0% | +0.0pp |
| note_tag | 100.0% | 100.0% | +0.0pp |
| **Tasks solved** | **9/14** | **14/14** | **+5** |
| **Avg pass rate** | **87.7%** | **100.0%** | **+12.3pp** |

Naked mode: Gemini Flash, 1 call, no memory, no swarm.
SHARD mode: full pipeline — episodic memory + swarm + knowledge bridge + up to 5 attempts.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Voice | Gemini Live (gemini-2.0-flash-live) |
| LLM chain | Gemini Flash → Groq (LLaMA-3.3-70b) → Claude (Sonnet-4.6) |
| Backend | Python 3.13, FastAPI, Socket.IO |
| Frontend | React 18, Vite, Electron, recharts |
| Storage | SQLite (WAL mode) + ChromaDB |
| Sandbox | Docker (--network none, 256MB RAM, non-root) |
| Hardware | Geekom A5 mini PC |

---

## Running SHARD

**Backend:**
```bash
cd backend
pip install -r requirements.txt
python server.py
```

**Frontend:**
```bash
npm install
npm run dev
```

**Night session (manual):**
```bash
python backend/night_runner.py --cycles 10 --timeout 240
python backend/night_runner.py --cycles 10 --timeout 240 --topic-budget 40  # tighter per-topic budget
python backend/night_runner.py --cycles 1 --no-core  # lobotomy test (baseline without CognitionCore)
```

**Benchmark (single task):**
```bash
python backend/benchmark_loop.py benchmark/task_04_race_condition --use-swarm
python backend/benchmark_loop.py benchmark/task_04_race_condition --strategy-mode baseline  # no strategy signal
```

**A/B causal test:**
```bash
python backend/ab_test_runner.py task_02_ghost_bug task_04_race_condition
```

**External bug (your own code):**
```bash
python shard_challenge.py buggy.py test_buggy.py
```

**CognitionCore stress test:**
```bash
python stress_test_emergence.py
```

**ROI benchmark (naked vs SHARD):**
```bash
python roi_benchmark.py
```

---

## Environment Variables

```
GEMINI_API_KEY=...
GROQ_API_KEY=...
ANTHROPIC_API_KEY=...
```

---

## SSJ Changelog

| Version | What was added |
|---------|---------------|
| SSJ2 | SWEAgent reactive self-repair via ErrorWatchdog |
| SSJ3 | SelfAnalyzer + ImprovementEngine proactive self-improvement |
| SSJ4 | Gemini auto-reconnect + MetaLearning + ProactiveRefactor gate |
| SSJ5 | SQLite migration + StudyPipeline refactor |
| SSJ6 | Benchmark Loop + Swarm Engine (Architect→Coder→Critic) |
| SSJ7 | GraphRAG + multi-reviewer swarm + Patch Simulator + sandbox assertion validation |
| SSJ8 | Focus Mode + Early Stopping + Rollback + Repomix bridge + Brain Graph 2D UI |
| SSJ9 | Capability-driven refactor + parallel audio background mode + scaffold hardening |
| SSJ10 | Test suite 0 FAILED + patch_simulator async def visibility fix |
| SSJ11 | CognitionCore / Senso Interno — 5-layer Global Workspace + Shadow Diagnostic + Vettore 1+2 + Lobotomy A/B proof (8.6 vs 7.0) |
| SSJ12 | Vettore 3 directed pivot from MetaLearning history + per-topic LLM budget |
| SSJ13 | AGI Layer — SelfModel (momentum, blind spots, quarantine), WorldModel (58-skill map, self_calibrate()), GoalEngine autonomous (SHARD picks its own goals), SemanticMemory bootstrap, GapDetector loop closure, CognitionCore +query_world/goal/real_identity + Vettori 4/5/6 |
| SSJ14 | **Full bidirectional event bus** — 14 CognitionCore citizens, all interconnected. New modules: MoodEngine (affective state, broadcasts mood_shift), IdentityCore (persistent biography from SQLite, self_esteem computed not declared), SkillLibrary (Voyager-inspired: certified skill cache + automatic curriculum via GraphRAG), HebbianUpdater (LTP/LTD plasticity + frustration decay), SelfModelTracker (predictive processing loop — mood + identity now modulate predictions), PrerequisiteChecker (GraphRAG+LLM gate). New events: mood_shift, identity_updated, low_self_esteem. Emergent behaviors observed: asyncio phobia, comfort zone, paradoxical curiosity under failure (Zeigarnik), calibrated predictor. |
| SSJ15 | **Emergent behavior analysis + architectural fixes.** Observed: cognitive effort surge (14-min asyncio cycle, 7 modules in cascade, no rule written), specification gaming (SHARD routes around hard topics autonomously), first honest self-identity (self_esteem=0.26, trajectory=declining). Fixes: weighted certifications in mood+identity (difficulty-adjusted cert_rate), curiosity loop fix (GraphRAG extends/improves priority, certified topics excluded), skill implementations (Voyager: saves winning code, injects for similar topics), junk strategy cleanup (20 garbage entries removed, filter prevents re-accumulation), sandbox-incompatible topics removed from curated list (network topics disabled). New backlog items: Perverse Emergence Detection (#18), strategy mutation EvoScientist-style (#14), affordance filtering SayCan-style (#15). |
| SSJ18 | **Diagnostic Layer + Signal Gate + Diagnostic Learning — pre-agency architecture.** Three new modules: `diagnostic_layer.py` (named failure classifier: DEADLOCK/IDEMPOTENCY/OSCILLATION — transforms silent runtime failure into a named, actionable signal); `signal_gate.py` (attention-based top-K filter — each source competes by confidence score, only top-3 enter the prompt, SHARD decides what matters not the LLM); `diagnostic_learning.py` (sole writer of `diagnostic_weights.json`: success +0.05, fail -0.03, clamped [0.5,2.0], atomic write, dedup). Architecture shift: `everything→prompt→LLM_decides` → `signals→ranking→top-K→guided_prompt→LLM_acts`. Key findings: (1) activation gap vs knowledge gap — 6000 chars of RLock documentation ignored, one sentence "DEADLOCK SUSPECTED" → solve; (2) signal competition — strategy (0.81) beats semantic_memory (0.78), episodic dropped; (3) IDEMPOTENCY weight: 1.000 → 1.050 after first victory. Benchmark: 12/12 with gate active. |
| SSJ19 | **Causal proof + Strategy Compiler + Memory quality fix + OOD generalization.** `strategy_compiler.py`: transforms raw strategy text into grounded operational instructions with confidence gating (>=0.75 MANDATORY, 0.60-0.74 SUGGESTED) and heuristic function-name anchoring. A/B/C causal proof: task_02 A=3att vs B=1att — IDEMPOTENCY diagnostic never fired in B, strategy signal alone solved it. B=C confirmed: gate selects correctly without forcing. Memory quality crisis fixed: 442 junk entries -> 0 via `clean_strategy_db.py`; `extract_from_diff()` extracts real patterns from benchmark victory diffs (12 patterns); `store_from_benchmark()` called at every win. Strategy multiplier: confidence boosted by track record (avg_score + success_rate, range 0.8-1.5). OOD generalization: task_13 (parsing bugs) + task_14 (boundary bugs) — both unseen domains, seed=2att, reuse=1att. Loop closed on new domains. Bulk Unicode fix: 90 backend files (cp1252 silent exceptions were swallowing DB writes). DB: 11 real strategies. |
| SSJ20 | **Perverse emergence detection + causal proof trilogy + longitudinal observability.** 14 stress tests: false positives, edge cases, degeneration, stability. Perverse emergence detector: HARD_AVOIDANCE flag (SHARD routes around hard topics autonomously), STAGNATION flag (strategy_reuse_rate=1.0 — exploitation without exploration). `session_snapshots.jsonl`: per-session metrics for longitudinal analysis. `--continuous` flag for long unattended runs. `analyze_snapshots.py` for offline post-run analysis. |
| SSJ21 | **65-session empirical analysis — strategy win rates, failure modes, micro-cluster taxonomy.** Key findings: exception_flow 87% win (META-STRATEGY), concurrency 36% despite threading skill 9.3 (FALSE NEGATIVE — routing problem, not knowledge gap), mutation_state 63% (GOLD ZONE), bcrypt/argon2 11% (toxic). Self-esteem: 0.2995 → 0.3778 (+0.08 over 65 sessions). STAGNATION on 16/65 sessions. Skill library: 55 certified skills, all >7.5. 1515 causal relations in GraphRAG. ExperimentInventor generating compositional cross-domain topics (BB84+property testing, quantum+REST API). |
| SSJ22 | **Cross-Task Transfer Layer (#22) — activation triggering via micro-cluster routing.** `cross_task_router.py`: 11 micro-clusters (boundary, mutation_state, concurrency, parsing_input, exception_flow, crypto_logic, serialization, algorithm, ml_numerical, network, architecture). Cluster-differentiated boosts: concurrency 1.40x (FALSE NEGATIVE fix), mutation_state 1.25x, crypto_logic 0.70x. Cross-inject: mutation_state → exception_flow strategies, concurrency → threading strategies. NEAR_MISS_TOPICS 1.30x boost. Blacklist: bcrypt/argon2. Penalties: swe_repair 0.70x. Wired into `signal_gate.build_strategy_signal()` + `strategy_memory.query(cross_inject_queries)`. Key insight: "SHARD doesn't learn something new — it learns when to use what it already knows." |
| SSJ22-v1.1 | **Attempt-gated strategy injection + OpenAI provider fallback.** Strategy signal now fires only from attempt 2 onward — prevents over-reliance on memory on first try. Added OpenAI as a 4th LLM fallback in the router chain. |
| SSJ25 | **Protocol filter + variance-aware scoring + stale lock recovery + benchmark 14/14.** `protocol_filter.py`: filters strategy memories by detected protocol (sync/async/threading), preventing wrong-type injection. `variance-aware base_score`: blends mean + penalty for bimodal topics (high-variance = unreliable signal). Stale lock recovery: detects and clears orphaned session lock files at startup. Benchmark expanded to 14 tasks — SHARD passes all 14/14. |
| SSJ26 | **SHARD.MEMORY full stack + external service mock injection.** Three memory phases shipped: Phase 1 (typed memory extraction + DB schema), Phase 2 (session connector, episode decay, derivation engine), Phase 3 (injection into study prompts + quality filter), Phase 3.5 (prior knowledge injection before study begins — Phase 0). External service mock injection (#43): redis, requests, psycopg2, pymongo auto-mocked in sandbox so network-dependent topics can now be certified. Cross-reference memory graph (#40): co-occurrence-weighted edges between skills. Graduated context load (#41): injects memory in proportion to session depth, not all at once. Automatic contradiction resolution (#36): `cert_contradiction_checker.py` detects and resolves conflicting certified facts across sessions. Redis certified 8.5/10 in 1 run after mock injection. |
| SSJ29 | **SHARD as Scientific Research Agent + Quoro technical report.** Arxiv integration (#34): SHARD can now search arxiv, retrieve papers, and ground hypotheses in real literature. Hypothesis generation in SYNTHESIZE phase: proposes falsifiable cross-domain hypotheses from its own capability graph. Causal hallucination metrics: measures how often the model invents vs cites real sources. Technical report drafted for Quoro CTO (Emilio) with full empirical data. |
| SSJ35+ | **Experiment Engine (#35) — SHARD runs real experiments.** Biggest addition since SSJ14. SHARD now generates, runs, and evaluates real scientific experiments in a Docker sandbox. Domain-aware scaffolds: `continual_learning` (OGD + ANV with `copy.deepcopy`, forgetting metric), `quantum_like` (density matrices, interference terms, Hilbert space — RandomForest proxy explicitly forbidden), `classification` (load_digits/load_breast_cancer, real sklearn datasets). Novelty gate (#48): 3-stage filter — word overlap + LLM semantic check on top arxiv hit + LLM judge — blocks well-known hypotheses before they waste a cycle. Signal mock injection (#47): unblocks signal-handling topics in sandbox. Goal cooldown (#46): prevents the agent from looping on stuck prerequisites. Co-occurrence domain boost (#44): memory link weights boosted by co-activation frequency. `--no-l3` A/B flag (#45): gates relational_context injection for ablation testing. EvoScientist (#14): LLM mutates losing strategies at pivot points — strategy evolution, not just selection. |

---

*Built by Andrea. Personal project. License: BUSL-1.1 (open use, no competing products).*
