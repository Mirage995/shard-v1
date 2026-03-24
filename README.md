# SHARD

**System of Hybrid Autonomous Reasoning and Design**

SHARD is an agentic scaffolding system — a persistent infrastructure that wraps LLMs with memory, feedback loops, and multi-agent swarms so they can solve coding tasks that a single prompt never could.

> **Benchmark result:** naked Gemini Flash solves 9/12 tasks (87.7% avg test pass rate).
> SHARD wrapping the same model solves **12/12** (100%) — closing every gap the naked LLM leaves open.
> Hardest cases: html_trap naked 38.9% → SHARD 100%, template_parser naked 20% → SHARD 100%.

---

## Why This Exists

A raw LLM call is stateless. It has no memory of what failed last time, no ability to run code and observe the result, no way to learn from experience.

SHARD wraps LLMs with:

- **Closed feedback loops** — run code → see failure → feed error back → retry
- **Persistent memory** — capability graph, episodic memory, strategy memory
- **Multi-agent swarm** — Architect + Coder + parallel specialized reviewers (Concurrency, Security, EdgeCases, Performance, DataIntegrity)
- **Causal knowledge** — GraphRAG stores what broke and why across sessions
- **Self-improvement** — analyzes its own performance, queues topics to re-study overnight
- **Focus Mode** — when a test stays stuck for 2+ rounds, mutes all reviewers and forces Architect → Coder direct to break the loop
- **Early stopping + rollback** — detects swarm regressions and restores the best known state

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

### Learns Every Night (NightRunner)
Autonomous study sessions while you sleep:
- Finds sources on the web (DuckDuckGo + Playwright scraping)
- Synthesizes knowledge into structured concepts
- Generates and runs code in a hardened Docker sandbox
- Validates with assert statements — code that doesn't prove it works gets rejected
- Certifies topics into the capability graph when score ≥ 7.5

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
```

**Benchmark (single task):**
```bash
python backend/benchmark_loop.py benchmark/task_04_race_condition --use-swarm
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

---

*Built by Andrea. Personal project. License: BUSL-1.1 (open use, no competing products).*
