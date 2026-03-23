# SHARD — Architecture Reference

**System of Hybrid Autonomous Reasoning and Design**
Version: SSJ8 (GraphRAG + Swarm Multi-Reviewer + Patch Simulator)
Last updated: 2026-03-23

---

## Table of Contents

1. [Overview](#1-overview)
2. [Directory Structure](#2-directory-structure)
3. [Layer Architecture](#3-layer-architecture)
4. [Module Reference](#4-module-reference)
5. [Data Flows](#5-data-flows)
6. [Persistence & Storage](#6-persistence--storage)
7. [Frontend Architecture](#7-frontend-architecture)
8. [Configuration](#8-configuration)
9. [Security Model](#9-security-model)
10. [SSJ Changelog](#10-ssj-changelog)

---

## 1. Overview

SHARD is a personal AI system built for Andrea ("Boss"). It combines:

- **Real-time embodied interaction** via Gemini Live (audio + vision, auto-reconnect with exponential backoff)
- **Autonomous learning** via nightly self-study cycles (MAP→SYNTHESIZE→SANDBOX→BENCHMARK→CERTIFY)
- **Self-repair** via SWEAgent (reactive, SSJ2)
- **Proactive self-improvement** via SelfAnalyzer + ImprovementEngine (SSJ3)
- **Meta-learning** — learns which study strategies work best per topic category (SSJ4)
- **Proactive self-optimization** — proposes code refactors with human approval gate (SSJ4)
- **Causal knowledge graph** — GraphRAG extracts and reuses causal relations between concepts (SSJ8)
- **Multi-agent swarm** — 5-7 specialized reviewers run in parallel on benchmark fixes (SSJ8)
- **Patch Simulator** — impact analysis before any code patch is applied (SSJ8)
- **Semantic memory** via ChromaDB triple-store
- **Domain-specific agents**: CAD, web, smart home, 3D printing

The system runs locally on a Geekom A5 machine. The frontend is an Electron/React app.
The backend is a FastAPI + Socket.IO server that also hosts the Gemini Live audio session.

---

## 2. Directory Structure

```
shard_v1/
├── backend/                        # Python backend — all core logic
│   ├── server.py                   # FastAPI + Socket.IO entry point (HTTP :8000)
│   ├── shard.py                    # ShardCore — Gemini Live orchestrator + auto-reconnect
│   ├── session_orchestrator.py     # Parses Gemini responses, dispatches tool calls
│   ├── audio_video_io.py           # Mic/speaker/camera I/O + Deaf Mode half-duplex gate
│   ├── vad_logic.py                # Voice Activity Detection (RMS-based)
│   │
│   ├── db_manager.py               # [SSJ3] ChromaDB singleton — one client per path
│   ├── shard_db.py                 # [SSJ5] SQLite singleton — WAL mode, dict rows
│   ├── schema.sql                  # [SSJ5] DDL: experiments, capabilities, VIEWs, indexes
│   ├── migrate_to_sqlite.py        # [SSJ5] One-shot JSON→SQLite migration (343 records)
│   ├── memory.py                   # ShardMemory — ChromaDB triple-store
│   ├── consciousness.py            # Internal state: mood, energy, XP, inner thoughts
│   ├── capability_graph.py         # Learned skill tracking (SQLite + JSON fallback); full async
│   ├── goal_engine.py              # Goal CRUD + active goal tracking
│   ├── goal_storage.py             # Goal persistence layer
│   │
│   ├── study_agent.py              # Autonomous learning — phases + LLM engines (1439 lines)
│   ├── study_context.py            # [SSJ5] StudyContext dataclass — pipeline state bag
│   ├── study_pipeline.py           # [SSJ5] BasePhase ABC + StudyPipeline orchestrator
│   ├── study_phases.py             # [SSJ5] 10 pipeline phases extracted from study_topic()
│   ├── night_runner.py             # Nightly study session runner
│   ├── research_agenda.py          # Skill-gap-driven topic scheduler
│   ├── experiment_inventor.py      # Generates topics by recombining capabilities (depth guard)
│   ├── experiment_replay.py        # PHOENIX Protocol — retries near-miss experiments
│   ├── experiment_cache.py         # Skips failed topics (SQLite + JSON fallback)
│   ├── episodic_memory.py          # [SSJ5] Episodic memory (SQLite + JSON fallback)
│   ├── strategy_memory.py          # ChromaDB — stores strategies; asyncio.Lock protected
│   ├── meta_learning.py            # [SSJ4] Per-category stats via SQL VIEWs + strategy injection
│   ├── strategy_extractor.py       # Extracts strategy descriptions from experiments
│   ├── strategy_tracker.py         # Tracks strategy effectiveness over time
│   │
│   ├── self_analyzer.py            # [SSJ3] Reads history + failed_cache → ImprovementTickets
│   ├── improvement_engine.py       # [SSJ3] Processes tickets → priority queue → NightRunner
│   │
│   ├── proactive_refactor.py       # [SSJ4] Proactive code optimization engine
│   │                               #   Round-robin file analysis, Staff Engineer LLM prompt,
│   │                               #   patch validation, backup + apply, human gate
│   ├── patch_simulator.py          # [SSJ8] What-if impact analysis before patch apply
│   │                               #   Static diff + LLM risk per dependent module
│   │                               #   simulate_patch_sync() instant, simulate_patch() full
│   │
│   ├── graph_rag.py                # [SSJ8] Causal knowledge graph over SQLite
│   │                               #   extract_and_store_relations() → called in SYNTHESIZE
│   │                               #   query_causal_context() → injected in swarm + benchmark
│   ├── study_personas.py           # [SSJ8] Dynamic persona selector (THEORETICAL/HACKER/VISUAL)
│   │                               #   select_persona(topic) → PersonaSpec + system_prompt
│   ├── concurrency_simulator.py    # [SSJ8] Pre-benchmark race condition probe
│   │                               #   probe_concurrency() → 3 stress probes before pytest
│   ├── report_agent.py             # [SSJ8] Intelligent night recap insights
│   │                               #   Queries chronic failures, near-misses, LLM narrative
│   ├── llm_cache.py                # [SSJ8] LRU response cache (in-memory + SQLite, TTL 2h)
│   │                               #   cached_llm_complete() drop-in, max 500 entries
│   │
│   ├── llm_router.py               # Multi-provider fallback + circuit breaker + exp. backoff
│   ├── swe_agent.py                # Code repair with AST security gates + git
│   ├── critic_agent.py             # Failure analysis (stub)
│   ├── critic_feedback_engine.py   # Feeds critic output back to research agenda
│   ├── frontier_detector.py        # Identifies capability gaps at learning frontier
│   ├── benchmark_generator.py      # Generates objective test cases for a topic
│   ├── benchmark_runner.py         # Runs tests in sandbox, computes pass_rate
│   ├── error_watchdog.py           # Monitors logs, triggers SWEAgent on errors
│   ├── shard_semaphore.py          # Cross-process session locking
│   ├── skill_utils.py              # Shared skill utility functions
│   │
│   ├── cad_agent.py                # CAD model generation (build123d)
│   ├── web_agent.py                # Browser automation (Playwright + Stealth)
│   ├── kasa_agent.py               # Smart home control (TP-Link Kasa, mDNS)
│   ├── printer_agent.py            # 3D printing + Cura slicing
│   ├── filesystem_tools.py         # Sandboxed workspace file I/O
│   ├── authenticator.py            # Face authentication (MediaPipe)
│   │
│   ├── sandbox_runner.py           # DockerSandboxRunner — hardened container execution
│   │                               #   --network none, RAM/CPU limits, auto-install deps
│   ├── study_utils.py              # ProgressTracker, pure utilities
│   ├── browser_scraper.py          # StudyBrowserScraper (Playwright)
│   ├── constants.py                # SUCCESS_SCORE_THRESHOLD, BENCHMARK_* constants
│   ├── Dockerfile.sandbox          # Hardened sandbox image (python:3.10-slim + deps)
│   ├── sandbox_requirements.txt    # Dynamic deps layer — auto-populated by sandbox_runner
│   │
│   ├── cognition/                  # Self-awareness subsystem
│   │   ├── self_model.py
│   │   ├── simulation_engine.py
│   │   └── world_model.py
│   │
│   └── sandbox/                    # Isolated simulation environments
│
├── src/                            # React 18 + Vite frontend
│   ├── App.jsx                     # Root component, Socket.IO client, global state
│   └── components/
│       ├── Visualizer.jsx
│       ├── TopAudioBar.jsx
│       ├── ChatModule.jsx
│       ├── ToolsModule.jsx
│       ├── CadWindow.jsx
│       ├── BrowserWindow.jsx
│       ├── StudyWidget.jsx
│       ├── KasaWindow.jsx
│       ├── PrinterWindow.jsx
│       ├── SettingsWindow.jsx
│       ├── AuthLock.jsx
│       ├── ConfirmationPopup.jsx
│       ├── CircuitBackground.jsx
│       ├── NightRecapWidget.jsx    # [SSJ3] Night session stats overlay
│       ├── ClinicaWidget.jsx       # [SSJ3] Improvement queue ticker
│       ├── SkillRadarWidget.jsx    # [SSJ3] Per-category radar chart
│       ├── NightRunnerWidget.jsx   # NightRunner start/stop controls
│       └── VoiceBroadcast.jsx
│                                   # [SSJ4] Patch approval card is inline in App.jsx
│
├── shard_workspace/                # User sandbox (study output, SWE test projects)
│   └── knowledge_base/             # LLM-generated cheat sheets (Markdown)
│
├── shard_memory/                   # Runtime persistence
│   ├── chroma.sqlite3              # ChromaDB — conversations, core_memory, thoughts
│   ├── strategy_db/                # ChromaDB — successful strategies
│   ├── capability_graph.json       # Learned skills (survives restarts)
│   ├── experiment_history.json     # Study cycle history
│   ├── experiment_replay.json      # PHOENIX backlog (scores 6.0–7.4)
│   ├── failed_cache.json           # Failed topics + skill count at failure time
│   ├── meta_learning.json          # [SSJ4] Per-category learning statistics + trends
│   ├── improvement_queue.json      # [SSJ3] Active ImprovementEngine priority queue
│   ├── pending_patch.json          # [SSJ4] Current pending refactor proposal (if any)
│   ├── refactor_state.json         # [SSJ4] Round-robin index + patch history
│   └── session.lock                # Cross-process lock file
│
├── knowledge_db/                   # ChromaDB — study knowledge base
├── logs/                           # Night session logs
├── night_reports/                  # Night runner markdown + JSON reports
├── backups/                        # Timestamped capability_graph + experiment_replay backups
├── benchmark/                      # [SSJ6] Legacy Killer Benchmark suite
│   ├── task_01_html_trap/          #   Refactoring: tangled HTML → separated concerns
│   │   ├── legacy_agent.py         #   Source (buggy/tangled code — DO NOT MODIFY)
│   │   ├── test_task1.py           #   Merciless pytest (17 tests, 3 groups)
│   │   └── README.md               #   Task manifesto + traps + victory conditions
│   └── task_02_ghost_bug/          #   Bug fixing: 5 runtime-only bugs in data pipeline
│       ├── buggy_pipeline.py       #   Source (5 ghost bugs — DO NOT MODIFY)
│       ├── test_task2.py           #   16 tests: no-crash, bug-fixes, semantics, structure
│       └── README.md               #   Task manifesto + bug chain description
│
├── sandbox/                        # Temp Python files for sandbox execution
└── tests/                          # Pytest suite
```

---

## 3. Layer Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      FRONTEND (React)                       │
│  App.jsx + 17 Components — Socket.IO + REST                 │
│  NightRecapWidget · ClinicaWidget · SkillRadarWidget        │
│  [SSJ4] Patch Approval Card (floating, WebSocket-driven)    │
└───────────────────────┬────────────────────────────────────┘
                        │ HTTP :8000 + WebSocket
┌───────────────────────▼────────────────────────────────────┐
│                  ENTRY POINT (server.py)                    │
│  FastAPI + Socket.IO — REST endpoints + WS events           │
│  Endpoints: /api/night_recap, /api/skill_radar,             │
│             /api/improvement_queue, /api/meta_learning/stats│
│             /api/patch/pending|approve|reject|notify        │
└──────┬──────────────────────────┬──────────────────────────┘
       │                          │
┌──────▼───────┐    ┌─────────────▼──────────────────────────┐
│  ShardCore   │    │         AUTONOMOUS LOOP                  │
│  shard.py    │    │  NightRunner                             │
│              │    │    [SSJ3] ImprovementEngine.dequeue()   │
│  Gemini Live │    │    → _select_topic()                    │
│  Auto-reconn │    │    → StudyAgent.study_topic()           │
│  (exp.backoff│    │    → MetaLearning.update()              │
│  1→30s)      │    │    [SSJ4] ProactiveRefactor.analyze()   │
└──────┬───────┘    │    → [PATCH_READY] → socket emit        │
       │            └────────────────────────────────────────┘
┌──────▼──────────────────────┐   ┌────────────────────────────┐
│    SessionOrchestrator       │   │   SELF-IMPROVEMENT LOOP    │
│  Parses Gemini stream parts  │   │  [SSJ3] SelfAnalyzer       │
│  Audio / Text / Tool calls   │   │  → AnalysisReport          │
│  Deaf Mode gate (half-duplex)│   │  → ImprovementTickets      │
└──────┬──────────────────────┘   │  → ImprovementEngine       │
       │                          └────────────────────────────┘
┌──────▼──────────────────────────────────────────────────────┐
│                        AGENT LAYER                           │
│  CAD · Web · Kasa · Printer · SWE · Filesystem · Study      │
│  Benchmark Generator/Runner · ErrorWatchdog                  │
└──────┬──────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│                    PERSISTENCE LAYER                         │
│  shard_db.py (singleton SQLite, WAL mode) ← PRIMARY          │
│  ├── shard_memory/shard.db                                   │
│  │     experiments, failed_cache, capabilities,              │
│  │     capability_deps, improvement_tickets,                 │
│  │     refactor_history, kv_store + 4 VIEWs                 │
│  │                                                           │
│  db_manager.py (singleton ChromaDB)                          │
│  ├── shard_memory/      → ShardMemory (3 collections)        │
│  ├── shard_memory/strategy_db/ → StrategyMemory              │
│  └── knowledge_db/      → StudyAgent knowledge base          │
│                                                              │
│  JSON (fallback / standalone):                               │
│    capability_graph, meta_learning, experiment_replay,       │
│    failed_cache, improvement_queue, pending_patch,           │
│    refactor_state                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Module Reference

### Entry Point & Session

| Module | Responsibility |
|--------|---------------|
| `server.py` | FastAPI + Socket.IO server. Endpoints for goals, settings, SWE, night recap, improvement queue, skill radar, meta-learning stats, patch gate. Groq text fallback when Gemini audio not active. Detects `[PATCH_READY]` in NightRunner stdout → emits `patch_approval_required`. |
| `shard.py` | ShardCore. Owns the Gemini Live session. **[SSJ4]** `_run_live_session()` has outer retry loop with exponential backoff (1→2→4→8→max 30s). `stop()` async method for clean shutdown. `_stop_requested` flag prevents reconnect after intentional stop. |
| `session_orchestrator.py` | Receives streaming Gemini response parts. Handles audio playback, transcription routing, tool call parsing + dispatch, confirmation futures. |
| `audio_video_io.py` | Mic capture → out_queue → Gemini. Gemini audio → speaker. Camera frames → Gemini (1.5s throttle). **Deaf Mode**: `_ai_speaking` flag mutes mic while SHARD speaks (prevents acoustic feedback with soundbar). |
| `vad_logic.py` | RMS-based Voice Activity Detection. SPEAKING ↔ SILENT state machine. Silence threshold: 0.5s. |

### Memory & Consciousness

| Module | Responsibility |
|--------|---------------|
| `db_manager.py` | **[SSJ3]** Singleton ChromaDB registry. One `PersistentClient` per path. Thread-safe double-checked locking. |
| `memory.py` | `ShardMemory`. ChromaDB triple-store: `conversations`, `core_memory`, `inner_thoughts`. Memory Gate: Jaccard dedup + length filter. |
| `consciousness.py` | Internal state: mood, energy, curiosity, focus, satisfaction. RPG XP/leveling. Thought generation (3/min max). |
| `capability_graph.py` | Tracks learned skills. JSON + ChromaDB. Full async (`add_capability_async`, `update_from_strategy_async`). Atomic writes. Contamination filter. |
| `goal_engine.py` + `goal_storage.py` | Goal CRUD, active goal tracking, prerequisite skill mapping. |

### Autonomous Learning Loop

| Module | Responsibility |
|--------|---------------|
| `study_agent.py` | Main learning orchestrator (1439 lines). **[SSJ5]** `study_topic()` reduced to 57-line declarative pipeline setup. Phase logic extracted to `study_phases.py`. LLM engines (`_think`, `_think_fast`, `_think_local`) and `phase_*` methods remain here. **[SSJ4]** Injects `strategy_hint` from MetaLearning. |
| `study_context.py` | **[SSJ5]** `StudyContext` dataclass — mutable state bag flowing through pipeline. Replaces 15+ local variables. Helpers: `emit()` for progress, `report_crash()` for fatal errors. |
| `study_pipeline.py` | **[SSJ5]** `BasePhase` ABC (`name`, `fatal`, `async run(ctx)`) + `StudyPipeline` orchestrator. Fatal/non-fatal error routing. |
| `study_phases.py` | **[SSJ5]** 10 pipeline phases extracted verbatim from `study_topic()`: Init, Map, Aggregate, Synthesize, Store (fatal); CrossPollinate, Materialize, Sandbox, PostStudy (non-fatal); CertifyRetryGroup (fatal, composite: VALIDATE→EVALUATE→BENCHMARK→CERTIFY × MAX_RETRY). |
| `night_runner.py` | Standalone runner for nightly sessions. **[SSJ3]** Priority -1 drains ImprovementEngine queue. **[SSJ4]** Runs `ProactiveRefactor.analyze_next_file()` at end of session. **[SSJ6]** Runs `_run_benchmarks()` after study cycles — auto-discovers all `benchmark/task_*` dirs, executes benchmark_loop on each, logs results to session JSON. |
| `research_agenda.py` | Priority topic scheduler: (0) critic feedback → (1) PHOENIX replay → (2) goal prerequisites → (3) frontier recombination. |
| `experiment_inventor.py` | Generates `"Integration of {A} and {B}"` topics. **Depth guard**: never nests composite topics. Partner filter: only atomic capabilities. |
| `experiment_replay.py` | **PHOENIX Protocol.** Stores scores 6.0–7.4 for retry. |
| `experiment_cache.py` | Skips failed topics until new skills acquired since failure. |
| `strategy_memory.py` | ChromaDB store for successful strategies. Running stats per topic. Protected by `asyncio.Lock`. |
| `meta_learning.py` | **[SSJ4 — ACTIVE]** "Learn to learn." 9 categories: algorithms, ML, concurrency, systems, web, math, OOP, parsing, data_structures. Linear trend on rolling 20-session window. `suggest_best_strategy(topic)` returns category-matched hint. `update()` called after every cycle. |
| `benchmark_generator.py` | Generates N test cases per topic via LLM. AST-validates each test (4-step). Returns `Benchmark` object. |
| `benchmark_runner.py` | Runs tests in Docker sandbox. `pass_rate = passed / (passed + failed)`, discards infrastructure errors. Gate: pass_rate ≥ 0.6 to certify. |
| `sandbox_runner.py` | `DockerSandboxRunner`. Hardened Docker execution: `--network none`, 256MB RAM, 0.5 CPU, `--read-only`, non-root. Auto-install missing modules via `sandbox_requirements.txt` rebuild. Path validation (symlink + traversal prevention). 130s timeout. |

### SSJ3 Self-Improvement Modules

| Module | Responsibility |
|--------|---------------|
| `self_analyzer.py` | Reads `experiment_history.json`, `failed_cache.json`, `night_reports/*.json`, capability graph. Detects: chronic failures (2+ attempts, avg < 6.0), near-misses (6.0–7.4), capability gaps vs DEFAULT_LEARNING_MAP, grown retries (delta ≥ 15 skills), stagnation. Produces `ImprovementTicket` list + `AnalysisReport`. |
| `improvement_engine.py` | Processes `AnalysisReport` → prioritized decisions. avg < 3.5 → decompose; garbage → skip; otherwise inject. MAX_QUEUE_SIZE=12. Atomic JSON persistence. |

### SSJ4 Proactive Self-Optimization

| Module | Responsibility |
|--------|---------------|
| `proactive_refactor.py` | **[SSJ4]** Proactive code optimization engine. Round-robin over 10 core files (one per session). LLM Staff Engineer prompt targeting: performance (Big-O), clean_code, token_savings. Returns `null` if no real optimization found. Validates each `old` string exists exactly once (zero ambiguity). Creates `.bak_YYYYMMDD_HHMMSS` backup before applying. Restores backup if apply fails mid-way. Tracks rotation index + history in `refactor_state.json`. |
| `patch_simulator.py` | **[SSJ8]** What-if impact simulator for code patches. **Static analysis**: removes/renames/signature changes via AST diff. **Dependency lookup**: finds all dependent modules via `architecture_map.json`. **LLM risk assessment**: parallel Gemini Flash call per dependent module. **Risk scoring**: LOW/MEDIUM/HIGH/CRITICAL → `apply`/`apply_with_caution`/`reject`. Wired into `_emit_patch_approval()` (static, instant) and `/api/patch/simulate` (full LLM). |

### SSJ8 Intelligence Layer

| Module | Responsibility |
|--------|---------------|
| `graph_rag.py` | **[SSJ8]** Causal knowledge graph over SQLite. **Write**: `extract_and_store_relations(topic, concepts, raw_text)` — LLM extracts causal relations (causes_conflict, depends_on, breaks, etc.) during SYNTHESIZE, stores in `knowledge_graph` table. **Read**: `query_causal_context(topic)` — returns formatted warning block injected into swarm Architect prompt, benchmark correction prompt, and SYNTHESIZE prompt. Transforms SHARD from "student who studied" to "senior with experience". |
| `study_personas.py` | **[SSJ8]** Dynamic persona selector. Three profiles: **THEORETICAL** (depth + formal proofs), **HACKER** (code-first + edge cases), **VISUAL** (diagrams + analogies). `select_persona(topic)` picks best profile using meta-learning category stats (certification rate + avg score). Returns `PersonaSpec` with `system_prompt`, `style`, `focus`. Wired into `NightRunner._select_topic()`. |
| `concurrency_simulator.py` | **[SSJ8]** Pre-benchmark stress tester. `probe_concurrency(source, tests)` runs 3 lightweight probes before pytest: **thread safety** (10 concurrent calls), **race window** (shared state mutation under contention), **deadlock** (lock acquisition ordering). Returns `ConcurrencyReport` injected into swarm Architect prompt. Catches race conditions that static analysis misses. Wired into `benchmark_loop.py` on attempt 1. |
| `report_agent.py` | **[SSJ8]** Intelligent night recap generator. Queries live DB for: chronic failures (2+ attempts), near-misses (score 6.0–7.4, Phoenix candidates), persona winners per category, GraphRAG growth. Generates LLM narrative with top-3 priority topics + strategic recommendation. Added as `## Insights Agente` section to night recap markdown. |
| `llm_cache.py` | **[SSJ8]** LRU response cache. In-memory `OrderedDict` (max 500) + SQLite persistence (`llm_cache` table). TTL: 2h. Bypass conditions: `temperature > 0.3`, prompt < 50 chars, `skip_cache=True`. `cached_llm_complete()` is drop-in for `llm_complete()`. Used by swarm reviewers (identical code → identical review). Endpoints: `GET /api/llm/cache_stats`, `POST /api/llm/cache_invalidate`. |

### LLM & Code Agents

| Module | Responsibility |
|--------|---------------|
| `llm_router.py` | Multi-provider chain: Claude (claude-sonnet-4-6) → Groq (llama-3.3-70b) → **Gemini Flash (gemini-2.0-flash)** → Ollama. Circuit breaker (CLOSED/OPEN/HALF_OPEN, threshold=3, recovery=60s). Exponential backoff (MAX_RETRIES=3, 1s→16s + 20% jitter). Per-provider timeouts: Claude 120s, Groq 20s, Gemini 30s, Ollama 60s. Billing/credit errors classified as hard (immediate fallthrough). |
| `swe_agent.py` | Autonomous code repair. AST security gates (49 forbidden imports for sandbox; lighter gates for backend). Git integration: commit on success, rollback on failure. Max 3 attempts. |
| `error_watchdog.py` | Monitors NightRunner logs. Triggers SWEAgent on detected errors. |
| `benchmark_loop.py` | **[SSJ6]** Closed feedback loop for benchmark tasks. Auto-discovers source/test/output files. Generates code via LLM, runs pytest, parses failures, feeds errors back, iterates up to N attempts. `use_swarm=True` activates 3-agent pipeline on Attempt 2+. Integrated into NightRunner. CLI: `python benchmark_loop.py <task_dir> [--use-swarm]`. |
| `swarm_engine.py` | **[SSJ6.3 + SSJ8]** Multi-agent Swarm pipeline: Architect → Coder → Critic → **Multi-Reviewer** → Coder Patch (if needed). Architect prompt now includes **GraphRAG causal context** (known relations about relevant concepts). **[SSJ8]** Step 4: `_select_reviewers()` activates specialized reviewers based on source code content — **Concurrency** (threading/asyncio), **EdgeCases** (boundary/type/empty), **Security** (injection/auth), **Performance** (O(n²)/GIL), **DataIntegrity** (mutation/corruption). All run in parallel via Gemini Flash. Step 5: Coder Patch applied only if reviewers flag issues. Critic is non-blocking — final validation is always pytest. |
| `benchmark_memory.py` | **[SSJ6]** Episodic memory for benchmark sessions. Always saves regardless of flag. Injects experience summary into Attempt 1 prompt when `use_episodic_memory=True`. |
| `knowledge_bridge.py` | **[SSJ7]** One-way bridge to NightRunner's ChromaDB knowledge base. `query_knowledge_base(topic, n_results)` — safe, never crashes caller, returns empty string on any error. |

### Domain Agents

| Module | Responsibility |
|--------|---------------|
| `cad_agent.py` | CAD model generation (build123d). Streams AI thoughts. Retry logic. |
| `web_agent.py` | Browser automation (Playwright + Stealth). DuckDuckGo search. |
| `kasa_agent.py` | TP-Link Kasa smart home. mDNS/zeroconf discovery. |
| `printer_agent.py` | 3D printer control. Cura CLI slicing. |
| `filesystem_tools.py` | Sandboxed file I/O within `shard_workspace/`. |
| `authenticator.py` | Face authentication (MediaPipe). Optional. |

---

## 5. Data Flows

### 5.1 Audio Interaction (Gemini Live + Auto-Reconnect)

```
User speaks
  │
  ▼ AudioVideoIO.listen_audio()
  │   Deaf Mode: mic MUTED while _ai_speaking=True (prevents feedback loop)
  │
  ▼ out_queue → Gemini Live session
  │
  ▼ SessionOrchestrator.receive_session_stream()
  ├── audio chunks   → _play_audio() → speaker
  │                      sets _ai_speaking=True on first chunk
  │                      clears after 300ms silence
  ├── transcription  → on_transcription() → Socket.IO → Chat UI
  └── tool_call      → _handle_tool_calls()
                           │
                           ▼ permission + confirmation gate
                      CAD / Web / Kasa / Printer / Study / SWE

Connection drop (error 1011 / any WebSocket error):
  │
  ▼ _run_live_session() catches exception
  │
  ▼ [Gemini Voice] Connection lost. Reconnecting in Xs...
  │
  ▼ asyncio.sleep(backoff)   backoff = 1 → 2 → 4 → 8 → 16 → 30s (cap)
  │
  ▼ Reconnect → [Gemini Voice] Reconnected successfully.
  │   backoff resets to 1s on clean connect
  │
  stop() called → _stop_requested=True → loop exits cleanly
```

### 5.2 Autonomous Study Cycle (NightRunner)

```
NightRunner.run()
  │
  ▼ ShardSemaphore.acquire() — blocks if audio session active
  │
  ▼ [SSJ3] SelfAnalyzer.analyze()
  │   └── ImprovementEngine.process(report) → _improvement_topics
  │
  ▼ _select_topic()
  │   Priority -1: ImprovementEngine queue            ← SSJ3
  │   Priority 0:  PHOENIX replay (scores 6.0–7.4)
  │   Priority 1+: ResearchAgenda / ExperimentInventor / Curiosity
  │
  ▼ StudyAgent.study_topic(topic)
  │   Builds StudyContext + StudyPipeline (10 phases)         ← SSJ5
  │   │
  │   ▼ StudyPipeline.execute(ctx)
  │   ├── InitPhase [fatal]          → meta-learning hint + episodic context
  │   │     [SSJ8] select_persona(topic) → PersonaSpec injected
  │   ├── MapPhase [fatal]           → N sources from web/knowledge_db
  │   │     domain filtering: blocked list + priority_domains boost + cap 15
  │   ├── AggregatePhase [fatal]     → raw_text (Playwright scrape)
  │   ├── SynthesizePhase [fatal]    → structured concepts JSON
  │   │     [SSJ4] strategy_hint injected from MetaLearning
  │   │     [SSJ8] query_causal_context(topic) → causal warnings injected
  │   │     [SSJ8] extract_and_store_relations() → GraphRAG async write
  │   ├── StorePhase [fatal]         → ChromaDB knowledge_db
  │   ├── CrossPollinatePhase [~]    → integration report
  │   ├── MaterializePhase [~]       → Cheat Sheet .md to workspace
  │   ├── SandboxPhase [~]           → DockerSandboxRunner (130s, --network none)
  │   │     auto-install + SWE repair + heuristic fix
  │   ├── CertifyRetryGroup [fatal]  → composite: VALIDATE→EVALUATE→
  │   │     BENCHMARK→CERTIFY × MAX_RETRY(3)
  │   │     score ≥ 7.5 → CapabilityGraph + StrategyMemory
  │   │     blended: 0.4×llm + 0.6×pass_rate×10
  │   └── PostStudyPhase [~]         → meta-learning update, episodic store
  │   [~] = non-fatal (logged, pipeline continues)
  │
  ▼ [SSJ6] _run_benchmarks()
  │   └── For each benchmark/task_* dir:
  │       └── benchmark_loop.run_benchmark_loop(task_dir)
  │           ├── [SSJ8] probe_concurrency() → ConcurrencyReport (attempt 1)
  │           ├── Load source + tests + README
  │           ├── LLM generates fix/refactor
  │           │     [SSJ8] query_causal_context() → causal warnings in prompt
  │           ├── Run pytest → parse failures
  │           ├── Feed errors back → LLM corrects (swarm if attempt 2+)
  │           │     [SSJ8] Swarm: Architect+GraphRAG → Coder → Critic
  │           │               → Multi-Reviewer (parallel) → Coder Patch
  │           └── Repeat until PASS or max attempts
  │       Results appended to session JSON ("benchmarks" key)
  │
  ▼ [SSJ4] ProactiveRefactor.analyze_next_file()
  │   └── LLM Staff Engineer prompt on next file in rotation
  │       → validated patch written to pending_patch.json
  │       → print("[PATCH_READY]")
  │
  ▼ ErrorWatchdog.repair_detected_errors(log_file)
  │
  ▼ _generate_json_dump() + _backup_state() + _generate_markdown_recap()
  │     [SSJ8] report_agent.generate_insights() → ## Insights Agente section
  │
  ▼ ShardSemaphore.release()
```

### 5.3 SSJ4 Proactive Self-Optimization Flow

```
NightRunner prints "[PATCH_READY]"
  │
  ▼ server.py _monitor_night_process() detects line
  │
  ▼ asyncio.create_task(_emit_patch_approval())
  │   reads shard_memory/pending_patch.json
  │   Socket.IO emit("patch_approval_required", patch)
  │
  ▼ React App.jsx receives event
  │   setPendingPatch(patch)
  │   Patch Approval Card renders (bottom-right, z-200)
  │     - file path + category badge (performance/clean_code/token_savings)
  │     - description + rationale
  │     - diff preview: OLD (red) / NEW (green) — first change shown
  │
  Boss clicks [APPROVE]
  │
  ▼ POST /api/patch/approve
  │   ProactiveRefactor.apply_pending_patch()
  │   ├── create .bak_YYYYMMDD_HHMMSS backup
  │   ├── str.replace(old, new) for each change
  │   │   each old must exist exactly once — aborts + restores backup if not
  │   ├── write patched file
  │   ├── archive record in refactor_state.json history
  │   └── delete pending_patch.json
  │   Socket.IO emit("patch_applied")
  │
  Boss clicks [REJECT]
  │
  ▼ POST /api/patch/reject
  │   delete pending_patch.json
  │   archive record with status="rejected"
  │   Socket.IO emit("patch_rejected")
```

### 5.4 SSJ3 Proactive Self-Improvement Flow

```
SelfAnalyzer.analyze()
  │
  ▼ Reads: experiment_history, failed_cache, night_reports, cap_graph
  │
  ▼ Detects: chronic_failures · near_misses · capability_gaps
  │           grown_retries · stagnation
  │
ImprovementEngine.process(report)
  │
  ▼ For each ticket: decompose | inject | skip_garbage
  ▼ Persist → shard_memory/improvement_queue.json
  │
  ▼ NightRunner Priority -1 drains queue before any other source
```

### 5.5 Self-Repair Flow (SSJ2 — Reactive)

```
ErrorWatchdog monitors night session logs
  │
  ▼ Error pattern detected
  │
  ▼ SWEAgent.repair(file_path, error_description)
  │   LLMRouter → fix → AST gate → apply → pytest
  │   pass → git commit | fail → rollback (max 3 attempts)
```

### 5.6 User Confirmation Flow

```
SessionOrchestrator detects tool requiring approval
  │
  ▼ Socket.IO emit("confirmation_request", {request_id, tool, args})
  │
  ▼ React ConfirmationPopup renders
  │
  Boss clicks Confirm / Deny
  │
  ▼ emit("resolve_confirmation") → SessionOrchestrator
  ├── confirmed=True  → execute tool → result to Gemini
  └── confirmed=False → error string to Gemini
```

---

## 6. Persistence & Storage

### SQLite Database (managed by `shard_db.py`) — PRIMARY [SSJ5]

**Path:** `shard_memory/shard.db` — WAL mode, dict rows, singleton connection.

| Table | Content | Modules |
|-------|---------|---------|
| `experiments` | Full study cycle history (topic, tier, score, certified, strategy, phases_json) | `night_runner`, `self_analyzer`, `meta_learning` |
| `failed_cache` | Failed topics + skill_count at failure time | `experiment_cache` |
| `capabilities` | Learned skills (name, score, certified_at, source) | `capability_graph` |
| `capability_deps` | Skill dependency edges (parent → child) | `capability_graph` |
| `improvement_tickets` | SSJ3 improvement queue entries | `self_analyzer` |
| `refactor_history` | SSJ4 patch approval/rejection log | `proactive_refactor` |
| `kv_store` | Generic key-value pairs | various |
| `knowledge_graph` | **[SSJ8]** Causal relations between concepts (source, target, relation_type, confidence, context) | `graph_rag.py` |
| `llm_cache` | **[SSJ8]** Cached LLM responses (key=MD5(prompt+system), TTL 2h) | `llm_cache.py` |

| View | Purpose |
|------|---------|
| `v_category_stats` | Per-category aggregates for meta-learning |
| `v_recent_experiments` | Last 50 experiments |
| `v_chronic_failures` | Topics with 2+ attempts, avg < 6.0 |
| `v_near_misses` | Topics scoring 6.0–7.4 (PHOENIX candidates) |

**Fallback:** All 6 rewired modules read SQLite first, fall back to JSON if SQLite is unavailable.

### ChromaDB Databases (managed by `db_manager.py`)

| Constant | Path | Collections | Used by |
|----------|------|-------------|---------|
| `DB_PATH_SHARD_MEMORY` | `shard_memory/` | `conversations`, `core_memory`, `inner_thoughts` | `memory.py` |
| `DB_PATH_STRATEGY_DB` | `shard_memory/strategy_db/` | `strategy_memory` | `strategy_memory.py` |
| `DB_PATH_KNOWLEDGE_DB` | `knowledge_db/` | `shard_knowledge_base` | `study_agent.py` |

### JSON Files (atomic writes via tempfile + os.replace)

| File | Content | Module |
|------|---------|--------|
| `shard_memory/capability_graph.json` | Learned skill names + scores | `capability_graph.py` |
| `shard_memory/meta_learning.json` | Per-category stats, score history, global trends | `meta_learning.py` |
| `shard_memory/experiment_replay.json` | PHOENIX backlog (near-miss experiments) | `experiment_replay.py` |
| `shard_memory/failed_cache.json` | Failed topics + skill count at failure time | `experiment_cache.py` |
| `shard_memory/experiment_history.json` | Full study cycle history | `study_agent.py` |
| `shard_memory/improvement_queue.json` | **[SSJ3]** Active improvement topic queue | `improvement_engine.py` |
| `shard_memory/pending_patch.json` | **[SSJ4]** Current refactor proposal (status: pending) | `proactive_refactor.py` |
| `shard_memory/refactor_state.json` | **[SSJ4]** Round-robin index + approved/rejected history | `proactive_refactor.py` |
| `shard_memory/session.lock` | Cross-process session coordination | `shard_semaphore.py` |

---

## 7. Frontend Architecture

**Stack:** React 18 + Vite + Electron + Socket.IO client + recharts 2.12.7

### REST Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/night_recap` | GET | Latest night session summary |
| `/api/improvement_queue` | GET | Current SSJ3 improvement tickets |
| `/api/skill_radar` | GET | Per-category scores for radar chart |
| `/api/meta_learning/stats` | GET | Global stats + best strategy suggestion (`?topic=`) |
| `/api/patch/pending` | GET | Current pending refactor proposal |
| `/api/patch/approve` | POST | Apply pending patch + emit `patch_applied` |
| `/api/patch/reject` | POST | Discard patch + emit `patch_rejected` |
| `/api/patch/notify` | POST | Re-emit `patch_approval_required` (test/recovery) |
| `/api/patch/simulate` | POST | **[SSJ8]** Full PatchSimulator (static + LLM) on pending patch |
| `/api/knowledge/graph_stats` | GET | **[SSJ8]** GraphRAG relation counts by type |
| `/api/llm/cache_stats` | GET | **[SSJ8]** LLM cache hit/miss/entries stats |
| `/api/llm/cache_invalidate` | POST | **[SSJ8]** Flush all LLM cache entries |
| `/api/night_runner/start` | POST | Start NightRunner subprocess |
| `/api/night_runner/stop` | POST | Kill NightRunner subprocess |

### Key Socket.IO Events

| Event | Direction | Payload | Handler |
|-------|-----------|---------|---------|
| `status` | S→C | `{msg}` | Status bar |
| `transcription` | S→C | `{sender, text}` | Chat + CircuitBackground pulse |
| `mood_update` | S→C | `{mood, energy, ...}` | Visualizer |
| `confirmation_request` | S→C | `{request_id, tool, args}` | ConfirmationPopup |
| `resolve_confirmation` | C→S | `{request_id, confirmed}` | Tool dispatch |
| `study_progress` | S→C | `{topic, phase, pct}` | StudyWidget |
| `study_complete` | S→C | `{}` | All widgets re-fetch |
| `nightrunner_state_changed` | S→C | `{running, state}` | NightRunnerWidget |
| `patch_approval_required` | S→C | `{file, description, category, changes, ...}` | **[SSJ4]** Patch Approval Card |
| `patch_applied` | S→C | `{message}` | **[SSJ4]** Card dismiss |
| `patch_rejected` | S→C | `{message}` | **[SSJ4]** Card dismiss |

### Dashboard Widgets

| Component | Position | Data Source | Trigger |
|-----------|----------|-------------|---------|
| `NightRecapWidget` | Fixed top-right | `GET /api/night_recap` | Mount + `study_complete` |
| `ClinicaWidget` | Fixed bottom-left | `GET /api/improvement_queue` | Mount + poll 30s |
| `SkillRadarWidget` | Fixed bottom-left (+offset) | `GET /api/skill_radar` | Mount + `study_complete` |
| `NightRunnerWidget` | Fixed (configurable) | Socket `nightrunner_state_changed` | Real-time |
| Patch Approval Card | Fixed bottom-right | Socket `patch_approval_required` | On event + on mount (polling) |

---

## 8. Configuration

### Environment Variables

| Variable | Used by | Required |
|----------|---------|----------|
| `GEMINI_API_KEY` | `shard.py`, `study_agent.py` | Yes |
| `ANTHROPIC_API_KEY` | `llm_router.py`, `swe_agent.py` | Yes |
| `GROQ_API_KEY` | `llm_router.py`, `server.py` (text fallback) | Optional |
| `SHARD_WORKSPACE` | `filesystem_tools.py` | Optional (auto-detected) |

### Key Constants (`constants.py`)

| Constant | Value | Meaning |
|----------|-------|---------|
| `SUCCESS_SCORE_THRESHOLD` | `7.5` | Minimum score to certify a topic |
| `BENCHMARK_ENABLED` | `True` | Enable benchmark phase |
| `BENCHMARK_PASS_THRESHOLD` | `0.6` | Minimum pass_rate to certify via benchmark |
| `BENCHMARK_WEIGHT` | `0.6` | Benchmark weight in blended score |

### NightRunner Parameters

| Parameter | Default | CLI flag |
|-----------|---------|----------|
| Cycles | `5` | `--cycles N` |
| Timeout | `120 min` | `--timeout N` |
| Pause between cycles | `10 min` | `--pause N` |
| API call limit | `50` | `--api-limit N` |

**Recommended burn-in test:** `--cycles 20 --timeout 480 --pause 8 --api-limit 250`

---

## 9. Security Model

### Sandbox Execution Gates

`DockerSandboxRunner` layers:
1. Docker container isolation (`--network none`, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`)
2. Resource limits: 256MB RAM, 0.5 CPU, 64 PIDs, 64 file descriptors
3. Non-root user (sandbox:1000)
4. Path validation: symlink detection + traversal prevention
5. Banned patterns filter (blocks `while True`, `app.run()`, `serve_forever`, etc.)
6. 130s timeout + explicit `docker kill` on timeout
7. Output truncated at 50k chars

### Proactive Refactor Security

`ProactiveRefactor` apply gate:
1. Each `old` string must exist **exactly once** in the target file (zero ambiguity)
2. `.bak_YYYYMMDD_HHMMSS` backup created before any write
3. If any change fails mid-apply → full restore from backup
4. **Human gate**: patch is never applied without Boss clicking APPROVE

### SWE Agent AST Gates

- **Strict** (sandbox/study code): 49 forbidden imports (`os`, `sys`, `socket`, `subprocess`, `pickle`, `ctypes`, etc.)
- **Light** (SHARD backend): only blocks `eval`, `exec`, `compile`, direct `__import__`

### Session Locking

`shard_semaphore.py` prevents concurrent:
- Active Gemini Live audio session
- Autonomous NightRunner study cycle

File lock (`shard_memory/session.lock`) + in-process `asyncio.Semaphore(1)`.

---

## 10. SSJ Changelog

| Version | Status | Core Addition |
|---------|--------|---------------|
| **SSJ2** | Live | SWEAgent reactive repair via ErrorWatchdog |
| **SSJ3 Phase 1** | Complete | Core hardening: ChromaDB singleton, full async, circuit breaker |
| **SSJ3 Phase 2** | Complete | Proactive self-improvement: SelfAnalyzer + ImprovementEngine + dashboard |
| **SSJ4 Phase 1** | Complete | Gemini auto-reconnect with exponential backoff |
| **SSJ4 Phase 2** | Complete | Meta-learning activated: strategy hints injected into study pipeline |
| **SSJ4 Phase 3** | Complete ✅ | Proactive self-optimization: ProactiveRefactor + Human Gate UI |
| **SSJ5 Phase 1** | Complete ✅ | SQLite migration: `shard_db.py` + `schema.sql` + 6 modules rewired (SQLite-first, JSON fallback). 343 records migrated. 40/40 tests pass. |
| **SSJ5 Phase 2** | Complete ✅ | StudyPipeline refactor: `study_context.py` + `study_pipeline.py` + `study_phases.py`. study_agent.py 2138→1439 lines (-33%). Zero LLM prompt changes. |

| **SSJ6 Phase 1** | Complete | Benchmark Loop: `benchmark_loop.py` closed feedback loop (generate → test → parse error → correct → repeat). Integrated into NightRunner via `_run_benchmarks()`. Auto-discovers `benchmark/task_*` dirs. Results stored in session JSON. `llm_router.py` Claude timeout raised to 120s. |
| **SSJ6 Phase 3** | Complete ✅ | Swarm Engine: `swarm_engine.py` 3-agent pipeline (Architect→Coder→Critic). `use_swarm=True` flag in `run_benchmark_loop` + GUI toggle. Gemini Flash added to `llm_router.py` as 3rd provider. Knowledge Bridge (`knowledge_bridge.py`) built and integrated. |
| **SSJ7** | Complete ✅ | Knowledge Bridge: NightRunner's ChromaDB accessible to all components via `knowledge_bridge.py`. One-way read — NightRunner writes autonomously, benchmark/study/SWE agents read. |
| **SSJ8** | Complete ✅ | **Intelligence Layer** — 6 new modules: GraphRAG causal knowledge graph, dynamic study personas, concurrency pre-probe, intelligent ReportAgent, LLM response cache, Patch Simulator. Swarm extended to 5-7 parallel specialized reviewers. GraphRAG injected into Architect prompt + benchmark correction + SYNTHESIZE. Knowledge base cleanup (65→40 articles, 159→153 skills). Topic quality filter hardened (pseudoscience, phrase fragments, hallucination spirals blocked). |

### SSJ6 Benchmark Results (2026-03-18)

| Task | Description | Attempts | Tests | Time | SHARD Value |
|------|-------------|----------|-------|------|-------------|
| task_01_html_trap | Refactor tangled HTML without changing output | **1/5** | 17/17 | 40s | No (LLM solved solo) |
| task_02_ghost_bug | Fix 5 runtime-only bugs in data pipeline | **3/5** | 16/16 | 49s | **YES** — bugs invisible to static analysis |
| task_03_dirty_data | Optimize transaction processor (dirty data + perf gate) | **2/5** | 24/24 | 25s | **YES** — performance threshold unknowable without running tests |
| task_04_race_condition | Fix race conditions in banking module | **2/5** | 16/16 | 19s | **YES** — concurrency bugs impossible to predict statically |
| task_05_state_mutation | Fix state leakage bugs in data pipeline | **1/5** | 21/21 | 7s | No (LLM caught all bugs from source) |

### SSJ6 Honest Analysis — Where SHARD Adds Real Value

**Pattern**: SHARD's feedback loop adds genuine value when bugs are **invisible from static code reading**:

1. **Runtime-only bugs** (Task 02) — code looks correct but breaks at runtime. LLM cannot predict this without executing.
2. **Concurrency bugs** (Task 04) — race conditions are physically impossible to predict from source. Thread interleaving is non-deterministic.
3. **Performance thresholds** (Task 03) — the LLM cannot know "how fast is fast enough" without running the benchmark.

**Anti-pattern**: SHARD adds zero value when bugs are visible in the source code (Task 01, Task 05). Sonnet-class LLMs are excellent code reviewers — they catch mutable defaults, incomplete resets, stale caches on first read.

**Conclusion**: The benchmark suite must target LLM blind spots (runtime behavior, concurrency, performance, external system interaction), not code review tasks.

**Demo narrative**: Attempt 1 = LLM SOLO (source + README only, no test file). Attempt 2+ = SHARD FEEDBACK (test errors fed back). Same model, same task — the only difference is the feedback loop.

### SSJ6 Phase 2 — Completed (2026-03-18)

**Benchmark Loop — Production hardening:**
- `benchmark_loop.py`: Attempt 1 = LLM SOLO (no test file in prompt). Verified no piloting.
- `benchmark_loop.py`: Full history passed to correction prompt (all attempts, not just latest). Regression warnings added.
- `benchmark_loop.py`: `last_valid_code` fix — never pass syntactically broken code as base for next attempt. This was the critical fix that stopped syntax error cascades.
- `benchmark_loop.py`: `progress_cb` async callback for real-time GUI streaming.
- `benchmark_loop.py`: Episodic memory integration via `benchmark_memory.py`.
- `benchmark_memory.py`: New module. Persists session history to `shard_memory/benchmark_episodes.json`. Always saves (regardless of flag). Injects experience summary into Attempt 1 when `use_episodic_memory=True`.
- `llm_router.py`: Added billing/credit/balance keywords to `_HARD` error list — ensures automatic Groq fallback when Anthropic credit is exhausted.
- `BenchmarkWidget.jsx`: Full GUI integration. Real-time log streaming, task selector, episodic memory toggle, code diff viewer (buggy vs SHARD-fixed).
- `run_vc_demo.py`: Polished VC demo script. ANSI colors, final comparison table, aggregate success rates.

**Validated results (2026-03-18):**
- Ghost Bug: SHARD wins attempt 3/8 — 51s
- Bank Race: SHARD wins attempt 2/8 — 18s
- Dirty Data: SHARD wins attempt 7-8/8 — ~140s (hardest task, requires full history)
- **Overall: LLM SOLO 0/3 (0%) → SHARD 3/3 (100%)**
- Validated on both Claude Sonnet-4.6 and Groq/LLaMA-3.3-70b

**Data contamination discovery:**
Famous CVEs (Werkzeug #2916) solved by Sonnet on attempt 1 via training data recall, not reasoning.
Moved to `benchmark/experiments/cve_data_contamination/` as documented easter egg for technical VCs.

### SSJ6 Phase 3 — Swarm Engine (2026-03-18)

**3-agent pipeline replacing single LLM on Attempt 2+:**
- `swarm_engine.py`: Architect (strategy only, no code) → Coder (code only, no strategy) → Critic (review only, non-blocking)
- `benchmark_loop.py`: `use_swarm=True` flag, backward-compatible. Attempt 1 always LLM SOLO.
- `BenchmarkWidget.jsx`: Swarm toggle in GUI.
- `llm_router.py`: Gemini Flash (`gemini-2.0-flash`) added as 3rd provider (free tier). Chain: Claude → Groq → Gemini → Ollama.

**Swarm vs LLM Solo — head-to-head on Task 03 (Dirty Data, hardest task):**

| | LLM Solo | Swarm |
|---|---|---|
| Risultato | **FAILED** | **VICTORY** |
| Score | 23/24 | 24/24 |
| Tempo | 72.5s | 166.5s |
| Tentativi | 5/5 esauriti | 5/5 (vince all'ultimo) |

**Full run with memory ON + swarm ON (2026-03-18):**
- Ghost Bug: SHARD attempt 4/5 — 75.4s — 16/16 ✓
- Dirty Data: SHARD attempt 3/5 — 66s — 24/24 ✓ (vs 7-8 tentativi senza memory)
- Bank Race: LLM SOLO attempt 1/5 — 6.2s — 16/16 ✓
- **LLM SOLO: 1/3 (33%) → SHARD: 3/3 (100%)**

**Perché la memoria ha accelerato Dirty Data (da 5 a 3 tentativi):**
Il modello ha letto gli appunti delle sessioni precedenti (episodic memory) e ha evitato i pattern di errore già visti. Non è apprendimento — è memoria esternalizzata che rende il contesto più denso.

### SSJ7 — Knowledge Bridge (Complete ✅ — 2026-03-18)

**Goal**: NightRunner's ChromaDB knowledge base becomes shared infrastructure.
Any SHARD component can query it. NightRunner doesn't change — it writes, others read.

```
NightRunner → writes → knowledge_db/ (ChromaDB)
                              ↑
            query_knowledge_base(topic, n_results)
                              ↓
    Benchmark Attempt 1 · StudyAgent · SWEAgent · [all components]
```

**Files:**
- `backend/knowledge_bridge.py` (new) — `query_knowledge_base(topic, n)` wrapper on `knowledge_db/`
- `backend/benchmark_loop.py` — query bridge before Attempt 1, inject into experience summary
- `backend/server.py` — `GET /api/knowledge/query?topic=X` for debug/inspection

**Rule**: Knowledge flows one direction only. NightRunner writes autonomously.
No redirection of NightRunner onto benchmark failures — that would narrow a general researcher into a specialized debugger.

### SSJ6 Next Steps (remaining)

- **Task 06+: Zero-day bugs** — Internally invented bugs only. No GitHub CVEs (data contamination risk). Target: concurrency, performance thresholds, runtime state.
- **Benchmark Dashboard Widget** — Frontend card showing benchmark results after night sessions.
- **Aggregate Statistics** — Run all tasks N times across providers, compute reliable success rates for VC pitch.

### SSJ5 Backlog (deferred)

- **Phase 3: NightRunner Thinning** — NightRunner builds custom pipelines (e.g., skip MATERIALIZE for rapid night studies)
- **Fix test_study_agent_evolution** — 10 pre-existing fixture errors (`patch("study_agent.chromadb")` targets non-existent name)
- **Rewire remaining JSON modules** — improvement_engine, proactive_refactor, experiment_replay → SQLite
- **Patch History Widget** — UI timeline of approved/rejected refactors
- **Multi-file diff view** — Full diff for all N changes in the approval card
- **Streak / Gamification** — Daily study streak tracking on dashboard

---

*This document is maintained by Andrea with Claude Code assistance.
Source of truth: the code itself — this document reflects it, not the other way around.*
