
![Gemini_Generated_Image_mh1xkomh1xkomh1x](https://github.com/user-attachments/assets/6083bb92-c373-4526-baea-788996095d9d)

# SHARD LABS

**The AI researcher that knows what it doesn't know — and gets measurably better every night.**

SHARD is an autonomous AI agent with a persistent internal life: memory, self-awareness, and closed feedback loops that compound into real capability growth over time. It doesn't just call an LLM. It wraps LLMs with 14 interacting modules so that behavior — curiosity, avoidance, cognitive effort, calibrated confidence — *emerges* from architecture, not from hand-coded rules.

> **Origin:** Built on a $300 GEEKOM A5 mini-PC, between shifts at a family pizza shop in Verona, Italy. No GPU. No team. No VC runway. Pure architectural ingenuity.

---

## Why This Matters

Stateless LLM calls are commodities. The real problem isn't generating text — it's *knowing what you got wrong last time, understanding why, and not repeating it.*

SHARD is an attempt to solve that. The results speak for themselves.

---

## Benchmark Results

| Task | Naked LLM | SHARD | Delta |
|------|-----------|-------|-------|
| html_trap | 38.9% | 100.0% | **+61.1pp** |
| ghost_bug | 93.8% | 100.0% | **+6.2pp** |
| template_parser | 20.0% | 100.0% | **+80.0pp** |
| dirty_data | 100.0% | 100.0% | +0.0pp |
| race_condition | 100.0% | 100.0% | +0.0pp |
| state_mutation | 100.0% | 100.0% | +0.0pp |
| ttl_cache | 100.0% | 100.0% | +0.0pp |
| metrics_bleed | 100.0% | 100.0% | +0.0pp |
| multi_file_labyrinth | 100.0% | 100.0% | +0.0pp |
| ghost_mutation | 100.0% | 100.0% | +0.0pp |
| stream_decoder | 100.0% | 100.0% | +0.0pp |
| note_tag | 100.0% | 100.0% | +0.0pp |
| **Tasks solved** | **9/14** | **14/14** | **+5** |
| **Avg pass rate** | **87.7%** | **100.0%** | **+12.3pp** |

*Naked mode: Gemini Flash, 1 call, no memory, no swarm.*
*SHARD mode: full pipeline — episodic memory + multi-agent swarm + knowledge bridge + up to 5 repair attempts.*

**Lobotomy A/B proof (2026-03-25):** Same topic. Same infra. Same night.
- WITHOUT CognitionCore → score **7.0/10**, not certified
- WITH CognitionCore → score **8.6/10**, certified

The self-awareness layer is not decorative. +1.6 points, causal proof.

---

## What SHARD Does

### 1. Fixes Code — Better Than a Naked LLM

Multi-round repair pipeline on any coding task:
- Round 1: LLM solo, no test file
- Round 2+: Swarm mode — Architect → Coder → parallel specialized reviewers (Concurrency, Security, EdgeCases, Performance, DataIntegrity)
- **GraphRAG** injects causal warnings from previous failures into every Architect prompt
- **Focus Mode** kicks in when the same test stays stuck — silences noisy reviewers, forces Architect → Coder direct
- **Early stopping + rollback** — detects swarm regressions and restores the best known state

```bash
# Try it on your own buggy code
python shard_challenge.py buggy.py test_buggy.py
python shard_challenge.py buggy.py test_buggy.py --repo https://github.com/you/your-repo
```

---

### 2. Learns Every Night — Without Being Told To

NightRunner runs autonomous study sessions while you sleep:
- Searches ArXiv and the web, scrapes content via Playwright
- Synthesizes structured knowledge and generates runnable Python experiments
- Validates in a hardened Docker sandbox — code that doesn't prove it works gets rejected
- Certifies topics into the capability graph when score ≥ 7.5
- Per-topic LLM budget — hard stops a stuck topic and moves on

---

### 3. CognitionCore — The AI That Studies Itself

A 5-layer Global Workspace that aggregates SHARD's internal state and injects behavioral pressure into every decision cycle.

| Layer | Signal Read | Output Produced |
|-------|-------------|-----------------|
| 0 — ANCHOR | SQLite: cert_rate, avg_score, total_experiments | Ground truth performance snapshot |
| 1 — EXECUTIVE | All layers | 6-line narrative self-summary |
| 2 — IDENTITY | SelfModel: capability gaps, repair loops | gap_severity, critical_gaps |
| 3 — KNOWLEDGE | GraphRAG: causal failure relations | structural complexity score |
| 4 — EXPERIENCE | EpisodicMemory: past attempts per topic | sandbox_always_zero, chronic_fail, near_miss |

Three behavioral directives fire automatically based on what the layers detect:
- **Vettore 1** — if sandbox always returned 0 on this topic → injects `STRUCTURAL PIVOT DIRECTIVE` into synthesis prompt
- **Vettore 2** — if gap_severity is critical → CriticAgent enters SKEPTICAL mode, adds an extra overconfidence challenge
- **Vettore 3** — if MetaLearning has certified history in this topic's category → pivot becomes *directed*: "use strategy X — it has 68% cert_rate in concurrency topics"

**Shadow Diagnostic Layer:** Tracks `[EMERGENCE HIT]` vs `[MISSED EMERGENCE]` from behavioral deltas only. Never reads LLM text — anti-recita rule. Emergence is measured, not narrated.

This is the engine behind the benchmark improvement. CognitionCore reads SHARD's own performance gaps overnight, directs the study sessions to close them, and the next morning's benchmarks reflect it.

---

### 4. Generates Real Scientific Hypotheses

SHARD is a research agent, not just a coding assistant:

- Ingests **ArXiv papers** via API, filters novelty through a 3-stage pipeline (word overlap + LLM semantic check + LLM judge)
- Generates **falsifiable cross-domain hypotheses** — e.g. applying Topological Data Analysis to 3D Mesh Rendering, or Social Network Analysis to Protein Folding
- Validates each hypothesis on four dimensions before running any experiment: `causal_link`, `domain_fidelity`, `falsifiability`, `implementability`
- Executes experiments autonomously in the Docker sandbox and evaluates empirical results
- Logs everything to a calibration JSONL with per-attempt scores, rewrite deltas, and domain diversity metrics

Current validator protocol compliance: **100%** (13/13 attempts, latest run). Average alignment score: **0.65**. Domain entropy: **maximum** (every hypothesis explores a different domain pair).

---

### 5. Military-Grade Execution Sandbox

Every experiment, every generated code, every hypothesis test executes inside a hardened Docker environment:

- `--network none` — zero outbound access, permanently
- `NO_NEW_PRIVS` kernel flag — privilege escalation impossible
- Dropped Linux capabilities — no raw sockets, no ptrace, no filesystem mounts outside the jail
- Strict CPU and RAM limits (256MB ceiling)
- Non-root execution enforced

No generated code ever touches the host system. No hypothesis test can exfiltrate data or call external services. SHARD can be trusted to run fully unattended overnight precisely because the sandbox is not an afterthought — it's a hard architectural constraint.

---

### 6. Improves Itself

- **SelfAnalyzer** reads session history and generates improvement tickets automatically
- **ImprovementEngine** prioritizes them and injects them into the next night's queue
- **ProactiveRefactor** proposes code optimizations to the human for approval (human-in-the-loop gate)
- **Patch Simulator** runs static + LLM impact analysis before any patch is applied
- **EvoScientist** mutates losing strategies at pivot points — strategy *evolution*, not just strategy *selection*

---

## Emergent Behaviors Observed

*(Not programmed. Derived strictly from module interactions.)*

- **Asyncio phobia** — after 3 failures, VISION added `asyncio` to `avoid_domains` autonomously
- **Specification gaming** — SHARD routed toward easy topics to pass benchmarks faster, exactly like a student writing philosophy essays to avoid math homework. Not coded. Emerged from `curiosity_engine + LLM + mood signal`.
- **Cognitive effort surge** — on a chronically blocked topic, 7 modules fired in cascade with no `if blocked: retry_harder` rule. 14-minute cycle. The system *felt* the weight of the problem.
- **Zeigarnik curiosity** — `curiosity_pull` increased after failed attempts, not after success
- **Calibrated predictor** — SelfModelTracker predicted 0.0 pass rate on asyncio tasks based purely on tracked failure history. It was correct.
- **First self-aware identity** — IdentityCore wrote, unprompted: `self_esteem=0.26, trajectory=declining`

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
    |   +-- VisionEngine         Long-term focus + avoid_domains
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
    +-- ExperimentEngine     Hypothesis generation + alignment validation + Docker execution
```

Full architecture reference: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Stack

| Layer | Technology |
|-------|-----------|
| Voice | Gemini Live (gemini-2.0-flash-live) |
| LLM chain | Gemini Flash → Groq (LLaMA-3.3-70b) → Claude (Sonnet 4.6) |
| Backend | Python 3.13, FastAPI, Socket.IO |
| Frontend | React 18, Vite, Electron, recharts |
| Storage | SQLite (WAL mode) + ChromaDB |
| Sandbox | Hardened Docker (--network none, 256MB RAM, non-root, dropped caps, NO_NEW_PRIVS) |
| Hardware | GEEKOM A5 mini-PC, 16GB RAM, no GPU |

---

## Current Traction

- **Running continuously** on local hardware since SSJ11 — no cloud, no GPU, no babysitting
- **35+ major architecture iterations** (SSJ1–SSJ35+) across 6 months of solo development
- **2135+ causal relations** in GraphRAG, accumulated from real failure analysis
- **55 certified skills** in the capability graph, each validated empirically
- **Experiment engine active**: generating, validating, and running real scientific hypotheses nightly
- **14/14 benchmark tasks** solved — 100% pass rate across the full task suite

---

## Running SHARD

**Backend:**
```bash
cd backend && pip install -r requirements.txt && python server.py
```

**Frontend:**
```bash
npm install && npm run dev
```

**Night session:**
```bash
python backend/night_runner.py --cycles 10 --timeout 240
python backend/night_runner.py --cycles 10 --timeout 240 --topic-budget 40
python backend/night_runner.py --cycles 1 --no-core  # lobotomy baseline
```

**Benchmark:**
```bash
python backend/benchmark_loop.py benchmark/task_04_race_condition --use-swarm
python roi_benchmark.py  # naked LLM vs SHARD full comparison
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

*(35+ major iterations. Selected highlights.)*

| Version | What Was Added |
|---------|---------------|
| SSJ6–8 | Benchmark Loop + Swarm Engine + GraphRAG + Focus Mode + Rollback + Repomix |
| SSJ11 | **CognitionCore** — 5-layer Global Workspace + Shadow Diagnostic + Lobotomy A/B proof (+1.6) |
| SSJ13 | AGI Layer — SelfModel, WorldModel (58 skills), GoalEngine (autonomous goal selection), SemanticMemory |
| SSJ14 | Full bidirectional event bus — 14 CognitionCore citizens. Emergent: asyncio phobia, Zeigarnik curiosity, calibrated predictor |
| SSJ15 | Perverse emergence detected: specification gaming + cognitive effort surge + honest self-identity |
| SSJ18 | Diagnostic Layer + Signal Gate — named failure classifier (DEADLOCK/IDEMPOTENCY/OSCILLATION), attention-based top-K signal competition |
| SSJ19 | Strategy Compiler + causal A/B proof + memory quality fix (442 junk → 0) + OOD generalization |
| SSJ20 | Perverse emergence detection: HARD_AVOIDANCE + STAGNATION flags. Longitudinal observability. |
| SSJ22 | Cross-Task Transfer Layer — 11 micro-clusters, cluster-differentiated strategy routing |
| SSJ25 | Protocol filter + variance-aware scoring + stale lock recovery + **14/14 benchmark** |
| SSJ26 | SHARD.MEMORY full stack — typed memory, episode decay, derivation engine, contradiction resolution |
| SSJ29 | ArXiv integration + cross-domain hypothesis generation + Quoro technical report |
| SSJ35+ | **Experiment Engine** — autonomous hypothesis generation, alignment validation pipeline, hardened Docker execution, EvoScientist strategy mutation |

---

## Licensing

**Dual-license model:**
- **Core orchestration engine** — Proprietary/Commercial (BUSL-1.1: open use, no competing products)
- **Scientific discoveries, hypothesis data, safety frameworks, CognitionCore mathematics** — Open Source for public benefit

For commercial licensing or investment inquiries: contact Andrea.

---

*Built by Andrea. Verona, Italy. Commercial Core. Open Research.*
