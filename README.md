
![Gemini_Generated_Image_mh1xkomh1xkomh1x](https://github.com/user-attachments/assets/6083bb92-c373-4526-baea-788996095d9d)

# SHARD

**System of Hybrid Autonomous Reasoning and Design**

SHARD is an agentic scaffolding system — a persistent infrastructure that wraps LLMs with memory, feedback loops, multi-agent swarms, and a self-awareness layer so they can solve coding tasks that a single prompt never could.

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
    +-- ShardCore          Gemini Live voice session
    +-- NightRunner        Autonomous study orchestrator
    +-- StudyAgent         10-phase learning pipeline
    +-- CognitionCore      5-layer Global Workspace + Shadow Diagnostic
    +-- BenchmarkLoop      Closed feedback loop for coding tasks
    +-- SwarmEngine        Multi-agent code repair + Focus Mode + Rollback
    +-- GraphRAG           Causal knowledge graph (SQLite)
    +-- SelfAnalyzer       Detects chronic failures + near-misses
    +-- ImprovementEngine  Priority queue -> NightRunner injection
    +-- ProactiveRefactor  Code optimization proposals + human gate
    +-- PatchSimulator     Impact analysis before any patch
    +-- RepomixBridge      Packs any GitHub repo into LLM context
    +-- LLMRouter          Gemini Flash -> Groq -> Claude fallback chain
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
| **Tasks solved** | **9/12** | **12/12** | **+3** |
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
| SSJ13 | AGI Layer — SelfModel (momentum, blind spots, quarantine), WorldModel (58-skill map, self_calibrate()), GoalEngine autonomous (SHARD picks its own goals), SemanticMemory bootstrap (171 episodes, 77 knowledge, 14 errors), GapDetector loop closure, CognitionCore +query_world/goal/real_identity + Vettori 4/5/6 |
| SSJ14 | Desire Layer — DesireEngine: frustration drive (failures increase pull), lateral curiosity (adjacent topics filtered by WorldModel), goal persistence (sessions_active), process reward (engagement_score). NightRunner Priority 0.5, cap 1/session. CognitionCore Vettori 7+8. |

---

*Built by Andrea. Personal project. License: BUSL-1.1 (open use, no competing products).*
