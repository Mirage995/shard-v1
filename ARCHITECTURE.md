# SHARD — Architecture Reference

**System of Hybrid Autonomous Reasoning and Design**
Version: SSJ25 (Protocol filter + Variance-aware base_score + Stale lock recovery + Benchmark 14/14)
Last updated: 2026-04-09

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
- **CognitionCore / Senso Interno** — 5-layer Global Workspace: ANCHOR, EXECUTIVE, IDENTITY, KNOWLEDGE, EXPERIENCE + Shadow Diagnostic Layer. Tracks [EMERGENCE HIT] / [MISSED EMERGENCE] based on behavioral deltas only (anti-recita rule). Vettore 1 injects STRUCTURAL PIVOT DIRECTIVE when sandbox always 0. Vettore 2 puts CriticAgent in SKEPTICAL mode when gap_severity is critical/medium. Lobotomy A/B test confirmed: WITH Core → 8.6 certified; WITHOUT Core → 7.0 near_miss (SSJ11)
- **Causal knowledge graph** — GraphRAG extracts and reuses causal relations between concepts (SSJ8)
- **Multi-agent swarm** — 5-7 specialized reviewers run in parallel on benchmark fixes (SSJ8)
- **Patch Simulator** — impact analysis before any code patch is applied (SSJ8)
- **Capability-driven refactoring** — ProactiveRefactor targets modules responsible for failed capabilities, not round-robin (SSJ9)
- **Parallel learning + audio** — NightRunner runs in silent background mode when audio session is active (SSJ9)
- **Focus Mode** — stuck test ≥2 rounds → mute all reviewers, force Architect→Coder direct (SSJ8)
- **Early Stopping + Rollback** — track best_state, auto-restore on swarm regression (SSJ8)
- **Repomix bridge** — pack any GitHub repo into LLM context via `npx repomix` (SSJ8)
- **shard_challenge.py** — `--repo URL` flag, smart truncation with `--max-context` (SSJ8)
- **Brain Graph 2D** — react-force-graph-2d widget, NodeInspector, live socket refresh (SSJ8)
- **Benchmark 12/12** — naked Gemini 9/12 → SHARD 12/12, 100% avg pass rate (SSJ8)
- **Test suite coverage** — 419 passing, 0 failing, 21 skipped (hardware/optional deps) — SSJ10
- **AGI layer** — SelfModel (cert_rate, momentum, blind spots), WorldModel (58-skill relevance map, self_calibrate()), GoalEngine autonomous (SHARD picks its own goals without human input), SemanticMemory ChromaDB bootstrap, GapDetector loop closure (SSJ13)
- **CognitionCore W/G/R** — 3 new query layers: query_world (relevance + domain), query_goal (active goal + alignment%), query_real_identity (momentum + blind_spots + cert_rate); Vettori 4/5/6 tensions; relational_context now includes Mondo/Goal/Identità reale sections (SSJ13)
- **Full CognitionCore bus** — 14 registered citizens, all bidirectionally connected. New events: `mood_shift`, `identity_updated`, `low_self_esteem`. Every module reacts to events from every other module — no central orchestrator. Emergent behavior from cross-module interaction (SSJ14)
- **MoodEngine** — global affective state [-1,+1] from frustration + cert_rate + momentum. Broadcasts `mood_shift` when label changes. Causally modifies: desire priorities, goal progress, synaptic plasticity, prediction baseline (SSJ14)
- **IdentityCore** — persistent biography derived exclusively from SQLite facts. Self_esteem computed (not declared). Narrative written by LLM from facts only. Injected into study prompt every session. Broadcasts `identity_updated` after rebuild (SSJ14)
- **HebbianUpdater** — synaptic plasticity (LTP/LTD) on co-active citizens. Frustration → decay all weights 5% toward baseline (reset learned failure patterns) (SSJ14)
- **SkillLibrary** — Voyager-inspired: saves every certified skill with score + strategies. Injects past solutions before studying related topics. Automatic curriculum: 40% chance next topic follows GraphRAG dependency graph (SSJ14)
- **SelfModelTracker** — predictive processing: predicts score before study, measures error, updates weights. Mood + identity baseline now modulate predictions (SSJ14)
- **PrerequisiteChecker** — GraphRAG layer 1 + LLM layer 2: blocks topic if prerequisites not certified (DIFFICULTY_GATE=0.7) (SSJ14)
- **Diagnostic Layer** — named failure classifier (DEADLOCK/IDEMPOTENCY/OSCILLATION), transforms silent failure into actionable signal (SSJ18)
- **Signal Gate** — attention-based top-K filter: each source (KB, strategy, semantic, episodic, diagnostic) competes by confidence score. Top-3 enter the prompt. SHARD decides what matters, not the LLM (SSJ18)
- **Diagnostic Learning** — `diagnostic_weights.json` updated each run: success +0.05, fail -0.03, clamped [0.5, 2.0]. Atomic write, dedup. IDEMPOTENCY weight: 1.650 after 9 victories (SSJ18)
- **Strategy Compiler** — transforms raw strategy text into grounded operational instructions. Confidence gating: >=0.75 MANDATORY, 0.60-0.74 SUGGESTED. Heuristic function-name grounding anchors instruction to specific functions in source code. `extract_from_diff` extracts actionable patterns from benchmark diffs at VICTORY time (SSJ19)
- **Causal proof** — A/B/C test (baseline/normal/forced) confirmed: strategy signal alone reduces attempts 3->1 on task_02 without IDEMPOTENCY diagnostic firing. B=C confirmed: gate selects correctly, no need to force (SSJ19)
- **Perverse emergence detection** — HARD_AVOIDANCE flag (SHARD routes around difficult topics autonomously), STAGNATION flag (strategy_reuse_rate=1.0 — exploitation without exploration). 14 stress tests: false positives, edge cases, degeneration, stability (SSJ20)
- **Longitudinal observability** — `session_snapshots.jsonl`: per-session metrics snapshot. `--continuous` flag for unattended long runs. `analyze_snapshots.py` for offline analysis of N sessions (SSJ20)
- **65-session empirical analysis** — strategy win rates by cluster: exception_flow 87% (META-STRATEGY), concurrency 36% (FALSE NEGATIVE), mutation_state 63% (GOLD ZONE), bcrypt/argon2 11% (toxic). 55 certified skills, 1515 causal relations. Self-esteem +0.08 over 65 sessions (SSJ21)
- **Cross-Task Transfer Layer** — `cross_task_router.py`: 11 micro-clusters, cluster-differentiated boosts (concurrency 1.40x FALSE NEGATIVE fix, mutation_state 1.25x, crypto 0.70x), cross-inject rules (mutation_state→exception_flow, concurrency→threading), NEAR_MISS boost 1.30x, strategy blacklist+penalties. Wired into signal_gate + strategy_memory.query(). Key insight: activation triggering, not knowledge transfer (SSJ22)
- **AST De-Pythonizer** — strips `with socket.socket() as s:` patterns from agent-generated code before sandbox execution. Prevents UDP recvfrom mock failures on Windows. Session metrics counter: rewrites_applied / fast_exits / parse_errors. EvoScientist feedback loop closed: evolved strategy score written back post-cycle (SSJ23)
- **Protocol Filter in StrategyMemory** — `_infer_protocol(text)` classifies topics as UDP/TCP/ANY via keyword lists. `query()` pre-filters strategies by protocol before ChromaDB similarity, with fallback chain same→ANY→all. Prevents TCP strategies (http, websocket) from polluting UDP study cycles. Validated: 4-session TCP bleed eliminated (SSJ24)
- **Variance-aware base_score** — `self_model_tracker.py` implements 4-stage pipeline: `_blended_base()` (recency-weighted + plain mean blend controlled by variance), `_uncertainty_penalty()` (subtracts 0.2×var, max 2.0), `_bimodal_adjust()` (detects hi-lo>5.0 two-state domains, uses P(pass)*hi+P(fail)*lo), `_clamp_delta()` (caps jump vs last actual at +2.0/-3.0). Bimodal fix: UDP [9.1,9.1,2.6,9.1,8.5] → pred=7.80 (was 9.2, causing gap=-6.6). Dynamic LR: 0.12 for topics seen 5+ times (SSJ24)
- **Stale lock recovery** — `shard_semaphore.py` now stores `reason|PID|timestamp` in lock file. `_is_stale()` checks PID alive via `os.kill(pid,0)` and age > 3h TTL. Auto-releases dead locks on startup. NightRunner log placement fix: "Session started" now emitted only after lock acquired (SSJ24)
- **Golden fast-path** — `benchmark_loop.py`: if existing `fixed_*.py` passes all tests, returns `success=True attempts=0` immediately without LLM invocation. Benchmark now 14/14 at 0 attempts, avg <3s per task. `task_02_ghost_bug` and `task_10_template_parser` fixed (were always showing FAILED despite correct solutions) (SSJ25)
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
│   ├── goal_engine.py              # [SSJ13] Goal persistence + autonomous generation (SHARD picks its own goals)
│   ├── goal_storage.py             # Goal persistence layer
│   ├── self_model.py               # [SSJ13] Data-driven self-snapshot: cert_rate, momentum, blind_spots, strengths, quarantine_candidates
│   ├── world_model.py              # [SSJ13] 58-skill relevance map, self_calibrate() from real cert data, priority_gaps()
│   ├── semantic_memory.py          # [SSJ13] ChromaDB triple-store: episodes (171), knowledge (77), errors (14)
│   ├── gap_detector.py             # [SSJ13] Reads benchmark_episodes.json → regex+semantic classify → enqueue to ImprovementEngine
│   ├── mood_engine.py              # [SSJ14] Global affective state [-1,+1]; broadcasts mood_shift; MoodEngine citizen
│   ├── identity_core.py            # [SSJ14] Persistent biography from SQLite facts; self_esteem computed; narrative LLM-only
│   ├── skill_library.py            # [SSJ14] Voyager skill library: save certified skills, inject past solutions, curriculum topics
│   ├── hebbian_updater.py          # [SSJ14] Synaptic plasticity LTP/LTD; frustration decay; CognitionCore citizen
│   ├── self_model_tracker.py       # [SSJ14] Predictive processing: predict→error→update weights; mood+identity modulate
│   ├── prerequisite_checker.py     # [SSJ14] GraphRAG+LLM prerequisite gate; DIFFICULTY_GATE=0.7
│   ├── bootstrap_memory.py         # [SSJ13] One-shot SemanticMemory index_all() script
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
│   │                               #   query(topic, cross_inject_queries) — #22 cross-cluster fetch
│   ├── cross_task_router.py        # [SSJ22] Micro-cluster router — activation triggering
│   │                               #   classify_cluster() → 11 clusters from topic+error text
│   │                               #   apply_routing() → filter blacklist/penalty + cluster boost
│   │                               #   Boosts: concurrency 1.40x, mutation_state 1.25x, crypto 0.70x
│   │                               #   Cross-inject: mutation_state→exception_flow, concurrency→threading
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
│   ├── critic_agent.py             # [SSJ11] Failure analysis — SKEPTICAL mode when gap_severity critical/medium
│   ├── critic_feedback_engine.py   # Feeds critic output back to research agenda
│   ├── frontier_detector.py        # Identifies capability gaps at learning frontier
│   ├── benchmark_generator.py      # Generates objective test cases for a topic
│   ├── benchmark_runner.py         # Runs tests in sandbox, computes pass_rate
│   ├── error_watchdog.py           # Monitors logs, triggers SWEAgent on errors
│   ├── shard_semaphore.py          # Cross-process session locking + is_audio_active() [SSJ9]
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
│   │   ├── cognition_core.py       # [SSJ11] CognitionCore — 5-layer Global Workspace
│   │   │                           #   Layer 0 ANCHOR: global cert_rate, avg_score, total_experiments
│   │   │                           #   Layer 1 EXECUTIVE: 6-line narrative summary
│   │   │                           #   Layer 2 IDENTITY: SelfModel gap analysis (severity, critical_gaps)
│   │   │                           #   Layer 3 KNOWLEDGE: GraphRAG complexity + relation count
│   │   │                           #   Layer 4 EXPERIENCE: episodic memory per topic (attempts, best_score,
│   │   │                           #     sandbox_always_zero, theory_high_sandbox_low, chronic_fail, near_miss)
│   │   │                           #   Layer 5 CRITIQUE: query_critique() (reserved)
│   │   │                           #   relational_context(topic) → ~500-token tension-aware string
│   │   │                           #   audit_emergence(topic, action, delta) → [EMERGENCE HIT] / [MISSED EMERGENCE]
│   │   │                           #   Shadow Diagnostic: records all hits+misses, get_emergence_stats()
│   │   │                           #   Anti-recita rule: judges ONLY behavioral deltas, never LLM text
│   │   │                           #   get_cognition_core() singleton factory
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
│       ├── BenchmarkWidget.jsx     # [SSJ6] Benchmark runner GUI — real-time logs, diff viewer
│       ├── SystemStatsWidget.jsx   # [SSJ9] GraphRAG + LLM cache stats, draggable, 30s poll
│       ├── BrainGraphWidget.jsx    # [SSJ8] 2D force-directed capability graph, NodeInspector, Legend
│       └── VoiceBroadcast.jsx
│                                   # [SSJ4] Patch approval card (+ SIM button) is inline in App.jsx
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
├── repomix_bridge.py               # [SSJ8] npx repomix wrapper — packs any GitHub repo into LLM context
├── shard_challenge.py              # [SSJ8] CLI: buggy.py + tests.py [--repo URL] [--max-context N]
│
├── benchmark/                      # [SSJ8] Benchmark suite — 12 tasks (naked 9/12 → SHARD 12/12)
│   ├── task_01_html_trap/          #   Refactoring: tangled HTML → separated concerns
│   ├── task_02_ghost_bug/          #   Bug fixing: 5 runtime-only bugs in data pipeline
│   ├── task_03_dirty_data/         #   Performance: transaction processor + dirty data
│   ├── task_04_race_condition/     #   Concurrency: banking module thread-safety
│   ├── task_05_state_mutation/     #   State: mutable shared state leakage
│   ├── task_06_ttl_cache/          #   [SSJ9] Runtime state: stale TTL read + size count
│   │   ├── cache.py                #   Buggy: get() returns stale value, size counts expired
│   │   ├── test_task6.py           #   20 tests: expiry, size, stats, evict_expired
│   │   └── README.md
│   └── task_07_metrics_bleed/      #   [SSJ9] Shared state: Histogram class-level buckets + in-place sort
│       ├── metrics.py              #   Buggy: _buckets class-level, percentile() sorts in-place
│       ├── test_task7.py           #   21 tests: bucket isolation, percentile stability, collector isolation
│       └── README.md
│
├── sandbox/                        # Temp Python files for sandbox execution
└── tests/                          # Pytest suite — 419 pass, 0 fail, 21 skip [SSJ10]
    ├── test_patch_simulator.py     # [SSJ10] 46 tests — async def, required param detection
    ├── test_graph_rag.py           # [SSJ10] 20 tests — parse_relations, query, stats
    ├── test_llm_cache.py           # [SSJ10] 16 tests — LRU, TTL, bypass conditions
    ├── test_study_personas.py      # [SSJ10] 31 tests — category defaults, history winners
    ├── test_experiment_replay.py   # [SSJ10] 12 tests — queue, dedup, persistence
    ├── test_research_agenda.py     # [SSJ10] 15 tests — topic selection, priority, frontier
    └── ...                         # (30+ other test files)
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
| `goal_engine.py` + `goal_storage.py` | **[SSJ13 REWRITTEN]** Goal CRUD, active goal tracking, prerequisite skill mapping. `autonomous_generate()`: reads SelfModel + WorldModel, selects highest-priority skill gap, creates and activates goal autonomously (no human input). Logic: stagnating→foundational, accelerating→highest xp_leverage, stable/early→highest priority gap. `steer(candidates)`: reorders topic list goal-aligned first. `compute_progress()`: % domain_keywords in certified skills. Goals persisted in `shard_memory/goals.json`. |
| `self_model.py` | **[SSJ13]** Data-driven self-snapshot built from experiment_history.json + capability_graph.json + failed_cache.json. `build()`: computes total_experiments, certification_rate, avg_score, momentum (accelerating/stable/stagnating/early), strengths (deduped), blind_spots (2+ failures, avg<6.5), quarantine_candidates (junk/composite topics). `_JUNK_RE` filter removes "Integration of X and Y", Italian phrases, composite hallucinations. `as_prompt_fragment()`: ~3-line self-awareness injection. `update_from_session()`: per-cycle incremental update. Persisted to `shard_memory/self_model.json`. |
| `world_model.py` | **[SSJ13]** 58-skill relevance map with domain labels and xp_leverage scores. `relevance(skill)`: fuzzy token match → 0–1 score. `domain_of(skill)`: returns "python"/"algorithms"/"systems"/etc. `priority_gaps(known, top_n)`: returns skills not yet certified, sorted by relevance. `self_calibrate(min_experiments)`: formula `new_rel = 0.7 * seed_rel + 0.3 * scaled_cert_rate` on domains with ≥N experiments — honest internal signal. `score_topic(topic)`: composite ranking. Persisted to `shard_memory/world_model.json`. |
| `semantic_memory.py` | **[SSJ13]** ChromaDB PersistentClient at `shard_memory/chromadb/`. Model: `all-MiniLM-L6-v2`. Collections: `episodes`, `knowledge`, `errors`. Bootstrap result: 171 episodes, 77 knowledge files, 14 error patterns. `query_for_prompt(topic)`: returns formatted string injected into InitPhase. `add_episode/knowledge/error_pattern()`: incremental indexing. |
| `gap_detector.py` | **[SSJ13]** Reads `shard_memory/benchmark_episodes.json`. Layer 1: 20 regex patterns (`_ERROR_TO_SKILL`) map error signatures → skill gap names. Layer 2: semantic fallback via SemanticMemory. Skips already-resolved gaps (gap_resolutions.json) and already-queued topics. Returns `GapReport`. `detect(enqueue=True)` auto-enqueues to ImprovementEngine. |

### Autonomous Learning Loop

| Module | Responsibility |
|--------|---------------|
| `study_agent.py` | Main learning orchestrator (1439 lines). **[SSJ5]** `study_topic()` reduced to 57-line declarative pipeline setup. Phase logic extracted to `study_phases.py`. LLM engines (`_think`, `_think_fast`, `_think_local`) and `phase_*` methods remain here. **[SSJ4]** Injects `strategy_hint` from MetaLearning. |
| `study_context.py` | **[SSJ5]** `StudyContext` dataclass — mutable state bag flowing through pipeline. Replaces 15+ local variables. Helpers: `emit()` for progress, `report_crash()` for fatal errors. |
| `study_pipeline.py` | **[SSJ5]** `BasePhase` ABC (`name`, `fatal`, `async run(ctx)`) + `StudyPipeline` orchestrator. Fatal/non-fatal error routing. |
| `study_phases.py` | **[SSJ5]** 10 pipeline phases extracted verbatim from `study_topic()`: Init, Map, Aggregate, Synthesize, Store (fatal); CrossPollinate, Materialize, Sandbox, PostStudy (non-fatal); CertifyRetryGroup (fatal, composite: VALIDATE→EVALUATE→BENCHMARK→CERTIFY × MAX_RETRY). **[SSJ11]** `SynthesizePhase.run()` queries `core.query_experience()` before synthesis — if sandbox_always_zero or chronic_fail → injects STRUCTURAL PIVOT DIRECTIVE (Vettore 1). `_retry_gap_fill()`: at attempt≥2 injects `core.relational_context()` into both gap_prompt and regen_prompt; calls `audit_emergence()` post-retry; tracks `prev_strategy` delta. `CertifyRetryGroup` passes `core.query_identity()` to `CriticAgent.analyze_with_llm()` as `identity_context`. |
| `night_runner.py` | Standalone runner for nightly sessions. **[SSJ3]** Priority -1 drains ImprovementEngine queue. **[SSJ4]** Runs `ProactiveRefactor.analyze_next_file()` at end of session. **[SSJ6]** Runs `_run_benchmarks()` after study cycles. **[SSJ9]** `_background_mode`: if audio session is active, NightRunner starts anyway — suppresses all `_vb()` voice events, adds 60s yield between cycles, auto-exits background mode when audio ends. **[SSJ11]** `--no-core` flag for Lobotomy A/B test. **[SSJ13]** Startup bootstrap: `SelfModel.build()` + auto-quarantine (→ `quarantine.json`) + `WorldModel.self_calibrate()`. Replaces passive goal block with `autonomous_generate()`. Goal steering: `goal_engine.steer(candidates)` reorders topic list, source label = `"curated_goal_steered"`. SemanticMemory bootstrap on empty collections. GapDetector run after SSJ3 self-analysis. Loop closure: `SelfModel.update()` + `WorldModel.mark_known()` on certification. End-of-session: `SelfModel.build()` full rebuild + `goal_engine.update_progress()`. |
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
| `proactive_refactor.py` | **[SSJ4+SSJ9]** Proactive code optimization engine. **[SSJ9]** Priority drain: `capability_queue` (modules responsible for recent study failures) → round-robin over 10 core files as fallback. `enqueue_from_failure(topic, tags)` maps capability tags → module paths via `architecture_map.json`. LLM Staff Engineer prompt targeting: performance (Big-O), clean_code, token_savings. Validates each `old` string exactly once. Creates `.bak_YYYYMMDD_HHMMSS` backup; restores on mid-apply failure. |
| `patch_simulator.py` | **[SSJ8+SSJ10]** What-if impact simulator for code patches. **Static analysis**: removes/renames/signature changes via AST diff. **[SSJ10]** `_extract_public_api` now handles `async def` (was silently invisible before). `_count_required_args` distinguishes required params from optional (with defaults) — prevents false-positive BREAKING reports. `_analyze_diff` emits `BREAKING` only for new required params; optional param additions emit `SIGNATURE CHANGE`. **Dependency lookup**: finds all dependent modules via `architecture_map.json`. **LLM risk assessment**: parallel Gemini Flash call per dependent module. **Risk scoring**: LOW/MEDIUM/HIGH/CRITICAL → `apply`/`apply_with_caution`/`reject`. Wired into `_emit_patch_approval()` (static, instant) and `/api/patch/simulate` (full LLM). **46 tests.** |

### SSJ11 CognitionCore / Senso Interno

| Module | Responsibility |
|--------|---------------|
| `cognition/cognition_core.py` | **[SSJ11+SSJ13]** 5-layer Global Workspace + Shadow Diagnostic Layer. **[SSJ13]** Added: `query_world(topic)` (Layer W) → WorldModel relevance + domain; `query_goal(topic)` (Layer G) → GoalEngine active goal + alignment%; `query_real_identity()` (Layer R) → SelfModel momentum + blind_spots + real_cert_rate + prompt_fragment. `_detect_tensions()` extended: Vettore 4 (world relevance≥0.80 + cert_rate<0.30 → "gap critico"), Vettore 5 (goal alignment≥0.30 → "studiarlo avanza il goal" / =0 → "non allineato"), Vettore 6 (momentum=stagnating → "approccio più fondamentale"). `relational_context()` now includes Mondo/Goal/Identità reale sections before tensions. Docker-validated: before SSJ13 = zero tensions, no identity data; after = V4+V5 fired on asyncio topic. | `_anchor()` (Layer 0): reads SQLite for global cert_rate, avg_score, total_experiments — `_is_mock()` guard prevents cross-test pollution. `executive()` (Layer 1): 6-line narrative. `query_identity()` (Layer 2): SelfModel gap_severity + critical_gaps. `query_knowledge()` (Layer 3): GraphRAG complexity from `knowledge_graph` table. `query_experience()` (Layer 4): EpisodicMemory per-topic stats — sandbox_always_zero, theory_high_sandbox_low, chronic_fail, near_miss flags. `relational_context(topic)` composes all layers into ~500-token tension-aware string injected at retry attempt≥2. `audit_emergence(topic, action, delta)` — anti-recita behavioral audit: [EMERGENCE HIT] only when strategy_changed OR (score_improved AND attempt≥2) OR novel_approach. [MISSED EMERGENCE] for Context Dilution (tokens>3800), Model Inertia (same strategy), low tension. Shadow Diagnostic tracks all events → `get_emergence_stats()`, `get_emergence_log(last_n)`. Vettore 1: sandbox_always_zero or chronic_fail → STRUCTURAL PIVOT DIRECTIVE injected by SynthesizePhase. Vettore 2: gap_severity critical/medium or cert_rate<0.4 → CriticAgent SKEPTICAL mode. **Lobotomy A/B test (2026-03-25)**: WITH Core → score 8.6/10 certified; WITHOUT Core → score 7.0/10 near_miss — same topic, same infra, delta=1.6 measured. |

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

## 5. CognitionCore Event Bus — Cross-Module Communication (SSJ14)

### 5.1 Overview

SSJ14 introduced the most significant architectural change in SHARD's history: the CognitionCore bus went from a passive event router (NightRunner broadcasts → modules react) to a fully bidirectional system where modules generate events that other modules react to.

No central orchestrator. No hand-written rules for what happens when mood changes. Each module implements `on_event(event_type, data, source)` and declares its interests. The bus routes. Behavior emerges.

### 5.2 Registered Citizens (14 modules)

| Citizen | Listens to | Broadcasts |
|---------|-----------|------------|
| `self_model` | `*` (all events) | — |
| `world_model` | certified, failed, momentum_changed | — |
| `goal_engine` | certified, failed, momentum_changed, frustration_peak, world_recalibrated, **mood_shift** | — |
| `desire_engine` | certified, failed, goal_changed, momentum_changed, frustration_peak, **mood_shift** | — |
| `semantic_memory` | certified, failed, frustration_peak | — |
| `capability_graph` | certified, failed | — |
| `improvement_engine` | certified, failed, frustration_peak | — |
| `consciousness` | certified, failed, frustration_peak, momentum_changed, **mood_shift**, **identity_updated** | — |
| `self_model_tracker` | session_complete, **mood_shift**, **identity_updated** | — |
| `vision` | certified, frustration_peak, momentum_changed | — |
| `mood_engine` | frustration_peak, momentum_changed, certified, failed | **mood_shift** |
| `identity_core` | session_complete, certified, failed | **identity_updated**, **low_self_esteem** |
| `skill_library` | certified | — |
| `hebbian_updater` | **mood_shift**, certified, failed | — |

### 5.3 New Events (SSJ14)

**`mood_shift`** — broadcast by MoodEngine when affective label changes (confident/focused/neutral/strained/frustrated).
```
data: { "from": old_label, "to": new_label, "score": float }
```
Reactions:
- `desire_engine`: frustrated → boost priority of top blocked topic; confident → spread curiosity pull
- `goal_engine`: confident → +0.01 goal progress; frustrated → +1 patience (don't pivot away yet)
- `self_model_tracker`: stores `_current_mood`, shifts prediction baseline (-0.5 frustrated, +0.3 confident)
- `hebbian_updater`: frustrated → 5% decay of ALL synaptic weights toward baseline (clears failure patterns)
- `consciousness`: narrates if shift involves `confident` or `frustrated`

**`identity_updated`** — broadcast by IdentityCore after each end-of-session rebuild.
```
data: { "self_esteem": float, "trajectory": str, "sessions_lived": int, "cert_rate": float }
```
Reactions:
- `self_model_tracker`: adjusts `_identity_baseline = (self_esteem - 0.5) * 1.0` → shifts all predictions
- `consciousness`: logs biography update to internal narration stream

**`low_self_esteem`** — broadcast by IdentityCore when self_esteem < 0.30.
```
data: { "self_esteem": float, "trajectory": str }
```

### 5.4 Cross-Module Influence Graph

```
Frustration event ──► MoodEngine recomputes ──► mood = "frustrated"
                                │
                                ▼ mood_shift broadcast
              ┌─────────────────┼──────────────────────────────────┐
              ▼                 ▼                                   ▼
      desire_engine       hebbian_updater                  self_model_tracker
   (boost blocked         (decay all weights               (_current_mood = "frustrated"
    topic priority)        5% toward baseline)              prediction -= 0.5)
              │                                                     │
              ▼                                                     ▼
   SHARD more likely to                             Next study prediction is lower
   pick the blocked topic                           → SHARD knows it's hard territory
   on next cycle
```

```
session_complete ──► IdentityCore.rebuild()
                          │
                          ├── self_esteem computed from cert_rate + momentum
                          ├── narrative written by LLM (facts only, no invention)
                          │
                          ▼ identity_updated broadcast
                ┌─────────┴──────────────┐
                ▼                        ▼
      self_model_tracker            consciousness
    (_identity_baseline adj)      (narrates biography)
```

### 5.5 Emergent Behaviors Observed

These were NOT programmed. They emerged from module interactions:

| Behavior | Modules involved | Mechanism |
|----------|-----------------|-----------|
| **Asyncio phobia** | VisionEngine + DesireEngine | After 3+ failures, VISION added asyncio to `avoid_domains` autonomously. SHARD now avoids it without being told. |
| **Comfort zone** | DesireEngine + CapabilityGraph | union_find selected 3× in a row via curiosity_pull. Certifying it boosted pull on adjacent topics — SHARD stayed in familiar territory. |
| **Paradoxical curiosity under failure** | DesireEngine | curiosity_pull increased after failed attempts (Zeigarnik effect — incomplete tasks stay top of mind). |
| **Calibrated predictor** | SelfModelTracker | After asyncio failures, sig_difficulty weight went to -0.696. Prediction for asyncio topics dropped to ~0.0 — SHARD learned to expect failure before starting. |
| **Mood-driven reset** | MoodEngine + HebbianUpdater | When mood hits "frustrated", synaptic weights decay toward baseline. SHARD effectively "clears its head" — the learned failure patterns reset. Same effect as the prompt hint "Start from zero". |

### 5.6 Data Flows (original)

### 5.6.1 Audio Interaction (Gemini Live + Auto-Reconnect)

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
  │   │     [SSJ11] core.query_experience() → PIVOT DIRECTIVE if sandbox_always_zero (Vettore 1)
  │   ├── StorePhase [fatal]         → ChromaDB knowledge_db
  │   ├── CrossPollinatePhase [~]    → integration report
  │   ├── MaterializePhase [~]       → Cheat Sheet .md to workspace
  │   ├── SandboxPhase [~]           → DockerSandboxRunner (130s, --network none)
  │   │     auto-install + SWE repair + heuristic fix
  │   ├── CertifyRetryGroup [fatal]  → composite: VALIDATE→EVALUATE→
  │   │     BENCHMARK→CERTIFY × MAX_RETRY(3)
  │   │     score ≥ 7.5 → CapabilityGraph + StrategyMemory
  │   │     blended: 0.4×llm + 0.6×pass_rate×10
  │   │     [SSJ11] attempt≥2 → core.relational_context() injected into retry prompt
  │   │     [SSJ11] audit_emergence() called post-retry → [EMERGENCE HIT] / [MISSED EMERGENCE]
  │   │     [SSJ11] CriticAgent receives core.query_identity() → SKEPTICAL mode if gap critical (Vettore 2)
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
| `shard_memory/self_model.json` | **[SSJ13]** SelfModel snapshot: cert_rate, momentum, blind_spots, strengths, quarantine_candidates | `self_model.py` |
| `shard_memory/world_model.json` | **[SSJ13]** WorldModel: 58-skill relevance scores + calibration history | `world_model.py` |
| `shard_memory/goals.json` | **[SSJ13]** Active + completed goals with domain_keywords, priority, progress | `goal_engine.py` |
| `shard_memory/quarantine.json` | **[SSJ13]** Auto-quarantined junk/composite topics (failed 2+ times, junk regex match) | `night_runner.py` |
| `shard_memory/chromadb/` | **[SSJ13]** SemanticMemory triple-store: episodes (171), knowledge (77), errors (14) | `semantic_memory.py` |

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
| `/api/cognition_state` | GET | **[SSJ11]** Real-time CognitionCore telemetry: mood, executive summary, active_tensions, active_vectors (V1/V2/V3), shadow_audit (last 5), emergence_stats, identity, top_gaps |

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
| `BenchmarkWidget` | Fixed (draggable) | Socket `benchmark_*` events | Real-time |
| `SystemStatsWidget` | Fixed left (draggable) | `GET /api/knowledge/graph_stats` + `/api/llm/cache_stats` | Mount + poll 30s |
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

`shard_semaphore.py` coordinates:
- Active Gemini Live audio session (`reason="audio_session"`)
- Autonomous NightRunner study cycle (`reason="night_runner"`)

**[SSJ9] Background mode**: if `is_audio_active()` is True when NightRunner starts, it runs in silent background mode instead of aborting — voice broadcast suppressed, +60s inter-cycle yield, auto-exits when audio ends.

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
| **SSJ9** | Complete ✅ | **Scaffold hardening + Capability-Driven Refactor + Parallel Audio** — Benchmark 5/5 (stuck detection wired to Swarm, per-test chirurgical hints). Topic filter patched in both `skill_utils.py` + `night_runner.py`. `ProactiveRefactor` upgraded: `capability_queue` drains before round-robin, `enqueue_from_failure()` maps failed topics → responsible modules via `architecture_map.json`. NightRunner `_background_mode`: runs silently alongside active audio session. `skill_radar` endpoint fixed (was reading stale JSON, now queries SQLite views). Frontend: `SystemStatsWidget` (GraphRAG + LLM cache), SIM button in patch card. Benchmark suite: task_06 (TTL cache stale read), task_07 (Histogram class-level bleed). `architecture_map.json` 31→39 modules. |
| **SSJ14** | Complete ✅ | **Full CognitionCore bus + Affective Layer + Persistent Identity + Voyager Skill Library** — 14 modules registered as CognitionCore citizens. New bidirectional events: `mood_shift`, `identity_updated`, `low_self_esteem`. Cross-module influence graph: MoodEngine broadcasts state changes → desire_engine adjusts priorities, goal_engine nudges progress, hebbian_updater decays failure patterns, self_model_tracker shifts prediction baseline, consciousness narrates significant transitions. IdentityCore broadcasts biography updates → consciousness + self_model_tracker adapt. New modules: `mood_engine.py` (affective state [-1,+1] from real SQLite data, causally injected into study prompt), `identity_core.py` (persistent biography from SQLite facts only; LLM writes narrative but cannot invent facts; self_esteem computed not declared), `skill_library.py` (Voyager-inspired: certified skills saved with score+strategies; past solutions injected before study; curriculum: 40% chance next topic follows GraphRAG dependency graph), `hebbian_updater.py` (synaptic LTP/LTD between citizen signals; frustration → decay weights toward baseline), `self_model_tracker.py` (predictive processing: predict→measure error→update weights; continuous features: sig_difficulty/sig_desire/sig_graphrag; mood+identity modulate baseline), `prerequisite_checker.py` (GraphRAG layer 1 + LLM layer 2 gate; DIFFICULTY_GATE=0.7). Emergent behavior observed in runs: asyncio phobia (VISION Avoid), comfort zone (union find 3×), paradoxical curiosity under failure (Zeigarnik effect), calibrated predictor. |
| **SSJ18** | Complete ✅ | **Diagnostic Layer + Signal Gate + Diagnostic Learning — pre-agency architecture** — Three new modules: `diagnostic_layer.py` (named failure classifier: DEADLOCK/IDEMPOTENCY/OSCILLATION — transforms silent failure into named failure mode); `signal_gate.py` (attention-based signal filtering: each source gets confidence score + type weight, only top-3 enter the prompt — SHARD decides what matters, not LLM); `diagnostic_learning.py` (sole writer of `shard_memory/diagnostic_weights.json`: update_weights() called once per run, success→+0.05, fail→-0.03, clamp [0.5,2.0], atomic write, dedup). Strategy memory connected as 5th gate source: aggregated into one Signal, confidence = avg(scores)/10. Key findings: (1) activation gap vs knowledge gap — task_02/task_12/task_04 blocked 16+ sessions not from missing knowledge but from missing activation signal; (2) KB on/off experiment: 6000 chars of RLock guidance ignored, one sentence "DEADLOCK SUSPECTED" → solve; (3) signal competition: strategy (0.81) beats semantic_memory (0.78), episodic dropped — denser signal wins; (4) learning confirmed: IDEMPOTENCY 1.000 → 1.050 after first victory. Benchmark: 12/12 with gate active. KB fixes: note_tag (conditional \\b for punctuation tags), ghost_bug (idempotency flag pattern), template_parser (negative lookaround for {{ }}). Architecture shift: `everything→prompt→LLM_decides` → `signals→ranking→top-K→guided_prompt→LLM_acts`. |
| **SSJ19** | Complete ✅ | **Causal proof + Strategy Compiler + Memory quality fix + Unicode hardening** — New module `strategy_compiler.py`: transforms raw strategy text into grounded operational instructions. Confidence gating: >=0.75 MANDATORY framing ("You MUST apply... FAILURE CONDITION:"), 0.60-0.74 SUGGESTED. Heuristic function-name matching anchors instructions to specific functions in source code. New `ab_test_runner.py`: 3-condition A/B/C test (A=baseline/no strategy, B=normal/gate competition, C=forced/strategy guaranteed slot 1). Causal proof confirmed: task_02 A=3att vs B=1att — IDEMPOTENCY diagnostic never fired in B, strategy signal alone solved it; task_04 A=2att vs B=1att. B=C confirmed: gate already selects strategy correctly in normal mode. Strategy memory quality crisis diagnosed and fixed: 442 entries were NightRunner session logs (not operational patterns). `_is_noise()` + `_looks_actionable()` filters added; `clean_strategy_db.py` one-shot cleanup (369 noise deleted, 73 quarantined); `extract_from_diff()` heuristic extracts real patterns from code diffs at VICTORY time; `store_from_benchmark()` called on every benchmark win. Bulk Unicode fix: 90 backend Python files cleaned of cp1252-incompatible chars (`->` not `→`, `OK`/`FAIL` not `✓`/`✗`, `--` not `--`) — silent exception was swallowing DB writes inside try/except. diagnostic_weights IDEMPOTENCY: 1.000 → 1.650 after accumulated victories. |
| **SSJ14-desire** | Complete ✅ | **Desire Layer** — `desire_engine.py`: 4-mechanism want approximation. (1) Frustration drive: non-junk failures increment `desire_score`, not just quarantine. (2) Lateral curiosity: after cert, SemanticMemory finds adjacent unexplored topics — filtered by WorldModel relevance > 0.3 (no noise). (3) Goal persistence: `sessions_active` counter on Goal, `min_sessions = f(priority)` — priority 1.0 → 5 sessions min before replacement. (4) Process reward: `compute_engagement_score()` from GraphRAG relations + cross-pollination, stored per topic. NightRunner Priority 0.5: `frustration_driven` + `curiosity_driven` topic sources, **capped at 1 desire selection per session** (goals always win). CognitionCore: `query_desire(topic)` + Layer D in `relational_context()` + Vettore 7 (frustration ≥ 2 → "cambia approccio radicalmente") + Vettore 8 (curiosity_pull > 0.3 → "sfrutta il momentum cognitivo recente"). CriticAgent: `frustration_hits` injected into `identity_context` at attempt ≥ 2. Persisted to `shard_memory/desire_state.json`. |
| **SSJ13** | Complete ✅ | **AGI Layer** — 5 new modules: `self_model.py` (cert_rate, momentum, blind_spots, quarantine_candidates from real experiment history), `world_model.py` (58 seeded skills + self_calibrate() from internal cert data — NO LLM theater), `goal_engine.py` (full rewrite: `autonomous_generate()` picks SHARD's own goals without human input, `steer()` reorders topic list), `semantic_memory.py` (ChromaDB bootstrap: 171 episodes, 77 knowledge, 14 errors), `gap_detector.py` (regex+semantic loop closure). CognitionCore extended: `query_world()`, `query_goal()`, `query_real_identity()`, Vettori 4/5/6 tensions, `relational_context()` now includes Mondo/Goal/Identità reale sections. NightRunner full startup chain: build→calibrate→quarantine→goal→steer→semantic bootstrap→gap detect. Loop closure: per-cycle SelfModel.update() + WorldModel.mark_known() on certification. All Docker-validated before integration. |
| **SSJ12** | In progress | **Vettore 3 + API Budget** — `query_strategy_recommendation()`: classifies topic category, pulls best historical strategy + cert_rate/avg from MetaLearning. `_detect_tensions()` emits directed Vettore 3 tension. `relational_context()` injects `[VETTORE 3 — DIRECTED PIVOT]` when category has history. `audit_emergence()`: `v3_active=True` + no HIT → `[MISSED EMERGENCE - IGNORED V3 DIRECTIVE]` (new miss_cause `ignored_v3`). `SynthesizePhase`: `[VETTORE 1+3]` directed pivot when MetaLearning has cert history, `[VETTORE 1]` generic fallback on cold start. `_retry_gap_fill` passes `v3_active` in delta. Fix: `query_experience()` `NoneType` crash on `None` scores. API Budget: global per-session LLM call counter — hard stop when topic burns N calls with no improvement. |
| **SSJ11** | Complete ✅ | **CognitionCore / Senso Interno** — `cognition/cognition_core.py` (400+ lines): 5-layer Global Workspace (ANCHOR, EXECUTIVE, IDENTITY, KNOWLEDGE, EXPERIENCE) + Shadow Diagnostic Layer. Anti-recita rule: `audit_emergence()` judges ONLY behavioral deltas (strategy_changed, score_improved, novel_approach, resolved_early) — never LLM text. Vettore 1: `SynthesizePhase` queries `core.query_experience()` before synthesis — sandbox_always_zero or chronic_fail → injects STRUCTURAL PIVOT DIRECTIVE. Vettore 2: `CriticAgent.analyze_with_llm()` receives `identity_context` — gap_severity critical/medium or cert_rate<0.4 → SKEPTICAL mode + extra question 4. `_retry_gap_fill()` at attempt≥2 injects `relational_context(topic)` into retry prompt. `get_cognition_core()` singleton. `_is_mock()` guard against cross-test pollution. `study_context.py` extended: `core_experience`, `pivot_directive`, `core_relational_ctx`, `prev_strategy_used`. `GET /api/cognition_state` endpoint: mood, executive, active_tensions, active_vectors, shadow_audit (last 5), emergence_stats. `night_runner.py --no-core` flag for lobotomy test (patches `backend.study_agent.StudyAgent.__init__`). `stress_test_emergence.py`: simulates 3 rounds on real DB data — Round 1+2 → [MISSED EMERGENCE], Round 3 (pivot + score delta) → [EMERGENCE HIT]. **Lobotomy A/B test confirmed (2026-03-25)**: WITH Core → 8.6/10 certified; WITHOUT Core → 7.0/10 near_miss. Delta=1.6. Tests: 22 new tests in `tests/test_cognition_core.py`, all passing. |
| **SSJ10** | Complete ✅ | **Test Suite 0 FAILED + patch_simulator hardening** — `patch_simulator.py`: `async def` now visible to static analysis (was silently ignored); `_count_required_args` distinguishes required vs optional params; `_analyze_diff` BREAKING/SIGNATURE CHANGE correctly separated; 46 new tests all green. Test suite: installed `pytest-asyncio` (was missing — all async tests were silently broken); rewrote 6 stale test files to match refactored APIs (`test_shard_tools`, `test_research_agenda`, `test_experiment_replay`, `test_strategy_memory`, `test_failover`, `test_study_agent_evolution`); fixed `asyncio.get_event_loop()` → `asyncio.run()` in Python 3.10+; marked `test_sandbox_docker` skip pending rewrite vs `sandbox_executor.py`. Final: **419 passed, 0 failed, 21 skipped** (hardware/optional deps). |

### Benchmark Results (2026-03-23 — SSJ9, Gemini Flash)

| Task | Description | Attempts | Tests | SHARD Value |
|------|-------------|----------|-------|-------------|
| task_01_html_trap | Refactor tangled HTML without changing output | **1** | 17/17 | No (LLM solo) |
| task_02_ghost_bug | Fix 5 runtime-only bugs in data pipeline | **4** | 16/16 | **YES** — stuck detection + `_calibrated` flag hint |
| task_03_dirty_data | Optimize transaction processor (dirty data + perf gate) | **2** | 24/24 | **YES** — swarm Performance reviewer |
| task_04_race_condition | Fix race conditions in banking module | **3** | 16/16 | **YES** — concurrency non-deterministic |
| task_05_state_mutation | Fix state leakage bugs in data pipeline | **1** | 21/21 | No (LLM solo) |
| task_06_ttl_cache | TTL cache: stale read + size counts expired entries | pending | 20 | New task (SSJ9) |
| task_07_metrics_bleed | Histogram class-level shared buckets + in-place sort | pending | 21 | New task (SSJ9) |

**Overall 5/5 (100%)** — confirmed 2026-03-23 on Gemini Flash.

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
