# SHARD

SHARD is a research prototype for cognitive infrastructure in AI agents: memory, skill reuse, benchmark repair loops, and a Global Workspace-style cognitive layer around ordinary LLM calls.

It is not a production AI breakthrough claim. The project is maintained as an empirical system: claims are kept only when they can be tied to code, tests, database state, experiment reports, or commits.

## Status & Methodology

SHARD is currently best described as a working research prototype with empirical methodology. The repository contains runtime systems for study, memory, benchmark repair, and cognitive arbitration, plus a documented falsification trail where earlier claims were revised after new evidence.

Recent corrections that shape the current interpretation:

- `343687e` reverted synthesize-time cognitive injection because relational context was poisoning the prompt at attempt 0.
- `9e85370` fixed the mood loop by passing `mood_score` into `WorkspaceArbiter`; before that, `ValenceField` was effectively inert in natural runs.
- `14b434f` aligned `real_identity` block typing so identity modulation actually reached `ValenceField`.
- `4dbb9d8` added persistent `shard_memory/mood_history.jsonl` instrumentation and histogram analysis.
- `58735ca` moved D2 frustration evidence out of runtime workspace into `docs/experiments/`.
- `4c37d65` documents D2.1A harness validation as PASS: cached sources, subprocess isolation, paired replica, no live search leakage.

The older claims `+16.6pp cert rate`, `+1.6 lobotomy proof`, and `14/14 benchmark 100% pass rate` are not treated here as general system claims. They were run-specific or condition-specific and are not currently used as README headline evidence.

## What Works (Verified)

These claims were checked in this workspace on 2026-05-05.

| Area | Current evidence | Status |
|---|---:|---|
| Pytest collection | `python -m pytest --collect-only -q` collected 881 tests | verified collection |
| Full pytest run | `python -m pytest -q` produced 809 passed, 8 skipped, 12 failed, 52 errors | contaminated by temp permission errors in this sandbox |
| Cognitive/GWT subset | 197 passed across cognition, workspace, GraphRAG, strategy, swarm, GWT A/B, context arbiter tests | verified subset |
| SWE/security subset | 121 passed across SWE security, SWE agent, workspace safety, authenticator tests | verified subset |
| Runtime/utility subset | 128 passed across runner, cleaner, patch simulator, cache, memory gate, replay, curriculum tests | verified subset |
| SQLite persistence | 26 application tables plus internal `sqlite_sequence` in `shard_memory/shard.db` | verified by Python `sqlite3` query |
| Skill library | 243 certified skill rows, 176 saved implementations | verified by SQLite query |
| GraphRAG | 3,161 knowledge graph relations; 1,456 verified, 282 disputed, 1,398 untested | verified by SQLite query |
| Capability graph | 1,054 capabilities in SQLite and `shard_memory/capability_graph.json`; 803 dependency rows | verified by SQLite/JSON query |
| Research hypotheses | 80 rows in `research_hypotheses`: 5 CONFIRMED, 22 REFUTED, 8 INCONCLUSIVE, 33 SKIPPED_TOO_COMPLEX, 1 KAGGLE_READY, 1 PENDING; 31 rows have generated code and 36 have stored results | verified by SQLite query |
| ChromaDB memory | `chromadb`: 3 collections (`episodes` 1,398, `knowledge` 250, `errors` 148); `strategy_db`: 1 collection (`strategy_memory` 1,201) | verified by Chroma `PersistentClient` |
| Mood instrumentation | `shard_memory/mood_history.jsonl` exists and currently has 3 samples | verified by line count |

Important caveat: the full pytest result is not a clean regression verdict because the failing run is dominated by temp directory permission failures in this execution environment. The module-specific green subsets are the evidence used for the verified status labels below.

## Core Modules That Exist And Run

- `backend/semantic_memory.py`: ChromaDB-backed long-term memory for episodes, knowledge, and recurring errors.
- `backend/strategy_memory.py`: Chroma-backed strategy retrieval and persistence, with async-safe writes and benchmark-diff extraction.
- `backend/graph_rag.py`: SQLite-backed causal relation extraction/query layer over `knowledge_graph`.
- `backend/capability_graph.py`: acquired capability ledger with SQLite persistence and JSON backup.
- `backend/skill_library.py`: SQLite library of certified skills and saved implementations.
- `backend/benchmark_loop.py`: closed repair loop for benchmark tasks, with pytest/jest/g++ style runners and optional swarm repair.
- `backend/swarm_engine.py`: Architect -> Coder -> Reviewer pipeline used by benchmark repair.
- `backend/experiment_inventor.py` and `backend/experiment_replay.py`: experiment generation and replay backlog.
- `backend/experiment_phases.py` and `backend/experiment_store.py`: research-mode Experiment Engine phases and hypothesis persistence.
- `backend/mood_engine.py`: mood score computed from frustration, recent cert rate, momentum, and workspace bias.
- `backend/identity_core.py`: persistent identity facts derived from SQLite, not persona prompt text.
- `backend/cognition/cognition_core.py`: Global Workspace-style aggregator, event bus, relational context, and emergence audit.
- `backend/cognition/workspace_arbiter.py`: `WorkspaceArbiter` and `ValenceField` for mood-modulated context competition.
- `backend/cognition/feedback_field.py`: reentrant bid modulation with optional SQLite persistence.
- `backend/cognition/mood_workspace_coupling.py`: winner-to-mood feedback path.
- `backend/context_arbiter.py`: per-topic context selection using the same valence semantics as the workspace arbiter.

See `ARCHITECTURE.md` for module status labels and data flows.

## What Is Being Tested

GWT activation is alive under forced mood. `python backend/gwt_mood_microtest.py` returns ESITO A: forced negative mood suppresses identity/real_identity below ignition while boosting experience, desire, and behavior directives. This proves the lever moves bids and winners; it does not prove better agent outcomes.

The D2.0 frustration benchmark is explicitly inconclusive. `docs/experiments/d2_0_frustration_benchmark.md` reports `INCONCLUSIVE_HARNESS`: both arms degraded together, external service instability exceeded contamination thresholds, mood never crossed -0.3, and workspace bias stayed at 0.0.

D2.1A is a harness-only PASS. `docs/experiments/d2_1a_harness_validation.md` documents cached MAP/AGGREGATE, subprocess isolation, paired replica, 4/4 subprocess exits at 0, zero DDGS/Brave/Playwright calls, and cache hash equality per topic. This validated the harness but is not itself a GWT outcome claim.

D2.1B failed its pre-registered single-topic stress prediction: `workspace_bias` stayed at zero everywhere. The useful finding was protocol-level: a single-cycle benchmark cannot observe a next-cycle coupling if winners are drained only after the topic ends.

D2.1C is now classified as `INCONCLUSIVE_MECHANISM_DISCONNECTED`. The sequential protocol produced an inverted pattern: ARM_OFF showed `workspace_bias=-0.15`, while ARM_ON stayed at zero. Log/code inspection shows ARM_OFF was synthetic ignition-failure fallback bias, while ARM_ON reached the GWT path but the stress-dominant `tensions` winner maps to zero in `MoodWorkspaceCoupling`. See `docs/experiments/d2_1c_sequential_validation.md`.

D2.1D tests the single pre-registered calibration hypothesis from D2.1C: `_WINNER_BIAS["tensions"] = (-0.05, +0.15)`. It returned `PASS_STRONG`: ARM_ON showed non-zero cycle-2 `workspace_bias=-0.095` with `tensions` bid traces, while ARM_OFF `workspace_bias=-0.15` was classified as synthetic fallback artifact and excluded from the GWT signal. This is an internal signal-propagation result, not an outcome-level performance claim.

Mood histogram work is active instrumentation, not proof. The current repo has persistent `mood_history.jsonl`; D2.0 showed the natural/easy regime often undersolicits mood coupling, while forced-mood microtests show the valence path can work when stress is present.

### GWT And Scientific Research Mode

The GWT path is implemented as a retry/stress-biased mechanism, not a blanket prompt enhancer. `CognitionCore.relational_context()` proposes identity, experience, knowledge, strategy, world, goal, real identity, desire, and tension blocks to `WorkspaceArbiter`; `ValenceField` modulates bids from `mood_score`; `FeedbackField` can apply reentrant winner/loser history; `MoodWorkspaceCoupling` feeds winner history back into `MoodEngine.compute()`. The current validated natural-run caveat is important: D2.0 showed `workspace_bias` at 0.0, while `backend/gwt_mood_microtest.py` shows the lever moves under forced mood.

Research mode adds a separate empirical block to the GWT context. When `research_mode=True`, `CognitionCore.query_empirical()` reads `research_hypotheses` and injects only non-pending statuses (`CONFIRMED`, `REFUTED`, `SKIPPED_TOO_COMPLEX`, `SKIPPED_KNOWN`) as Layer E empirical knowledge. This is intentionally narrower than "all experiment notes": `PENDING` and `INCONCLUSIVE` rows are excluded from prompt evidence.

The scientific research path is also gated before it becomes evidence. `backend/study_agent.py` checks arXiv novelty, feasibility, and alignment; `backend/experiment_phases.py` requires a four-part experiment spec (`MECHANISM`, `INTERVENTION`, `MEASUREMENT`, `SUCCESS CRITERION`), rejects weak proxy metrics, can route real-world data requirements to Kaggle or Modal queues, runs local sandbox experiments as three independent replicas, and uses an Antagonist review loop before validation. Current DB state is evidence of an experimental apparatus, not a public scientific conclusion.

## Architecture Map

The architecture is documented in `ARCHITECTURE.md`. At a high level:

```text
Interface / orchestration
  React + Electron + FastAPI/Socket.IO

Agent loops
  NightRunner, StudyAgent, BenchmarkLoop, SwarmEngine, Experiment replay/invention

Cognitive layer
  CognitionCore, WorkspaceArbiter, ValenceField, FeedbackField,
  MoodEngine, IdentityCore, ContextArbiter, MoodWorkspaceCoupling

Memory and learning
  SQLite shard.db, ChromaDB collections, JSON state files,
  SemanticMemory, StrategyMemory, SkillLibrary, GraphRAG, CapabilityGraph

Execution and safety
  DockerSandboxRunner, SWE security gates, workspace safety guards,
  auth-gated Socket.IO events, CAD/build agents with remaining host-exec risk
```

## How To Run

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
npm install
```

Run the Electron/Vite app:

```powershell
npm run dev
```

Run the backend directly:

```powershell
python backend/server.py
```

Run focused verification used by this README:

```powershell
python -m pytest -q tests/test_cognition_core.py tests/test_workspace_arbiter.py tests/test_feedback_field.py tests/test_mood_workspace_coupling.py tests/test_context_arbiter.py tests/test_graph_rag.py tests/test_skill_discovery.py tests/test_strategy_memory.py tests/test_swarm_engine.py tests/test_gwt_ab_test.py tests/test_desire_engine_workspace_bias.py
python -m pytest -q tests/test_swe_security.py tests/test_swe_agent.py tests/test_workspace_safety.py tests/test_authenticator.py
python backend/gwt_mood_microtest.py
```

Run D2 harness tooling:

```powershell
python backend/d2_1a_cache_sources.py
python backend/d2_1a_benchmark.py
python backend/d2_1a_analyze.py
```

D2.1B/D2.1C/D2.1D stress validation code exists in `backend/d2_1b_benchmark.py`, `backend/d2_1b_analyze.py`, `backend/d2_1c_benchmark.py`, `backend/d2_1c_analyze.py`, `backend/d2_1d_benchmark.py`, and `backend/d2_1d_analyze.py`. D2.1D includes the pre-registered `tensions` calibration patch and remains limited to next-cycle signal propagation.

## Stack

- Backend: Python, FastAPI, Socket.IO, asyncio, pytest.
- LLM providers: OpenAI, Anthropic, Groq, Google GenAI, routed through local provider utilities.
- Memory: SQLite, ChromaDB, JSON/JSONL state files.
- Retrieval and study: DuckDuckGo/Brave/web scraping paths, plus cached-source hooks for controlled experiments.
- Frontend: React, Vite, Electron, Tailwind, Three.js/react-three-fiber.
- Execution: Docker sandbox for study code, local subprocess paths for selected agents and tooling.

## Open Questions

- Does the D2.1D internal signal propagation survive repeated runs and structured provenance logging?
- After provenance is tracked, do GWT-induced internal mood signals correlate with better recovery/certification behavior under controlled stress?
- What policy should translate workspace winner shifts into concrete action changes, instead of only prompt context changes?
- How often does natural operation enter the stress regime where `MoodWorkspaceCoupling` matters, and how often is the observed bias synthetic fallback rather than real workspace-winner bias?
- Are CONFIRMED/REFUTED rows in `research_hypotheses` reliable enough to support external scientific claims, or only internal prompt guidance?
- Should the Experiment Engine's REFUTED-to-GraphRAG relation use a valid current relation type? The DB has 2 legacy `does_not_improve` rows while the current `GraphRAG` valid set does not include that relation.
- Which GraphRAG relations are stale or disputed enough to hurt future prompts?
- Can the temp-directory permission failures in the current Windows/sandbox test environment be eliminated without weakening security?
- Should `CapabilityGraph` persistence prefer SQLite-only behavior, JSON backup, or an explicit test-mode persistence strategy?

## Related Thinking

- `docs/experiments/d2_0_frustration_benchmark.md`: D2.0 inconclusive harness analysis.
- `docs/experiments/d2_1a_harness_validation.md`: D2.1A harness validation PASS.
- `docs/experiments/d2_1b_stress_validation.md`: D2.1B single-cycle stress validation FAIL with next-cycle observability diagnosis.
- `docs/experiments/d2_1c_sequential_validation.md`: D2.1C sequential validation, `INCONCLUSIVE_MECHANISM_DISCONNECTED`.
- `docs/experiments/d2_1d_tensions_bias_calibration.md`: D2.1D pre-registered `tensions` calibration, `PASS_STRONG` for signal propagation.
- `shard_gwt_ultrareview.md`: local GWT review notes.
- `shard_theoretical_mapping.md`: theoretical mapping notes.
- `README_LABS.md`: SHARD Labs material, intentionally not removed or rewritten here.

## Building In Public

The current documentation treats falsification as part of the project, not a reputational problem. The commit pattern around `74a6de5` -> `343687e`, `9e85370`, `14b434f`, `4dbb9d8`, and `4c37d65` is the public trail: try an architectural idea, instrument it, revert or narrow it when evidence disagrees, then document the new boundary.

Add the LinkedIn falsification post URL here when publishing the public README.

## Evidence Ledger

Commands run for this refoundation:

```powershell
git log --oneline -15
python -m pytest --collect-only -q
python -m pytest -q
python -m pytest -q tests/test_cognition_core.py tests/test_workspace_arbiter.py tests/test_feedback_field.py tests/test_mood_workspace_coupling.py tests/test_context_arbiter.py tests/test_graph_rag.py tests/test_skill_discovery.py tests/test_strategy_memory.py tests/test_swarm_engine.py tests/test_gwt_ab_test.py tests/test_desire_engine_workspace_bias.py
python -m pytest -q tests/test_swe_security.py tests/test_swe_agent.py tests/test_workspace_safety.py tests/test_authenticator.py
python -m pytest -q tests/test_runner.py tests/test_code_cleaner.py tests/test_patch_simulator.py tests/test_llm_cache.py tests/test_memory_gate.py tests/test_research_agenda.py tests/test_experiment_replay.py tests/test_suggest_curriculum.py
python backend/gwt_mood_microtest.py
```

SQLite and ChromaDB counts were gathered via Python because the `sqlite3` CLI is not installed in this environment:

```python
import sqlite3
conn = sqlite3.connect("shard_memory/shard.db")
# SELECT name FROM sqlite_master WHERE type='table' ORDER BY name
# SELECT COUNT(*) FROM skill_library
# SELECT COUNT(*) FROM knowledge_graph
```
