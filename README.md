# SHARD

**System of Hybrid Autonomous Reasoning and Design**

SHARD is an **agentic scaffolding** system — a persistent infrastructure that wraps LLMs with memory, feedback loops, self-repair, and autonomous improvement so they can tackle tasks that a single prompt never could.

It learns autonomously, fixes its own bugs, and improves its own code. It runs locally on a Geekom A5 mini PC and interacts via voice (Gemini Live), a React desktop app, and a fully autonomous nightly study loop.

---

## What is Agentic Scaffolding?

A raw LLM call is stateless — it has no memory of what failed last time, no ability to run code and see the result, no way to improve from experience.

SHARD wraps LLMs with:
- **Persistent memory** — capability graph, episodic memory, strategy memory
- **Closed feedback loops** — run code → see failure → feed error back → retry
- **Multi-agent pipelines** — Architect + Coder + parallel specialized reviewers
- **Causal knowledge** — GraphRAG stores what SHARD learned about why things break
- **Self-improvement** — analyzes its own performance and queues topics to re-study

The result: the same LLM that fails a hard coding task solo solves it in 2-3 attempts with the scaffold around it.

---

## What SHARD Does

### Talks and Listens
Real-time voice conversation via Gemini Live — mic input, speaker output, auto-reconnect with exponential backoff. Sees through the webcam. Transcriptions appear in the GUI.

### Learns Every Night
Autonomous study sessions while you sleep:
- Finds sources on the web (DuckDuckGo + Playwright scraping)
- Synthesizes knowledge into structured concepts
- Generates and runs code in a hardened Docker sandbox
- Validates with assert statements — code that doesn't prove it works gets rejected
- Certifies topics into the capability graph when score >= 7.5

### Fixes Itself
When something breaks in a study session, the SWE Agent detects the error, patches the file, runs tests, and commits the fix — all without human input.

### Improves Itself
- **SelfAnalyzer** reads session history and generates improvement tickets
- **ImprovementEngine** prioritizes them and injects them into the next night's queue
- **ProactiveRefactor** proposes code optimizations to the human for approval
- **Patch Simulator** runs impact analysis (static + LLM) before any patch is applied

### Benchmark Loop
Closes the feedback loop on hard coding tasks:
- Attempt 1: LLM solo (no test file)
- Attempt 2+: multi-agent Swarm (Architect → Coder → parallel reviewers → patch)
- Swarm reviewers: Concurrency, EdgeCases, Security, Performance, DataIntegrity
- GraphRAG injects causal warnings from previous studies into the Architect prompt

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
    +-- SwarmEngine        Multi-agent code repair (5-7 reviewers)
    +-- GraphRAG           Causal knowledge graph (SQLite)
    +-- SelfAnalyzer       Detects chronic failures + near-misses
    +-- ImprovementEngine  Priority queue -> NightRunner injection
    +-- ProactiveRefactor  Code optimization proposals + human gate
    +-- PatchSimulator     Impact analysis before any patch
    +-- LLMRouter          Gemini Flash -> Groq -> Claude fallback chain
```

Full architecture reference: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Stack

| Layer | Technology |
|-------|-----------|
| Voice | Gemini Live (gemini-2.0-flash-live) |
| LLM chain | Gemini Flash -> Groq (LLaMA-3.3-70b) -> Claude (Sonnet-4.6) |
| Backend | Python 3.13, FastAPI, Socket.IO |
| Frontend | React 18, Vite, Electron, recharts |
| Storage | SQLite (WAL mode) + ChromaDB |
| Sandbox | Docker (--network none, 256MB RAM, non-root) |
| Hardware | Geekom A5 mini PC |

---

## SSJ Changelog

| Version | What was added |
|---------|---------------|
| SSJ2 | SWEAgent reactive self-repair via ErrorWatchdog |
| SSJ3 | SelfAnalyzer + ImprovementEngine proactive self-improvement |
| SSJ4 | Gemini auto-reconnect + MetaLearning + ProactiveRefactor gate |
| SSJ5 | SQLite migration + StudyPipeline refactor (study_agent 2138->1439 lines) |
| SSJ6 | Benchmark Loop + Swarm Engine (Architect->Coder->Critic) |
| SSJ7 | Knowledge Bridge — ChromaDB accessible to all components |
| SSJ8 | GraphRAG causal graph + multi-reviewer swarm + Patch Simulator + sandbox assertion validation |

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

---

## Environment Variables

```
GEMINI_API_KEY=...
GROQ_API_KEY=...
ANTHROPIC_API_KEY=...
```

---

*Built by Andrea. Personal project.*
