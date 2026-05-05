# SHARD Architecture

This document describes the current architecture as code, not as aspiration. Status labels mean:

- `verified`: covered by green focused tests or directly verified by database/file inspection in this workspace.
- `experimental`: executable code exists, but outcome claims are still under test.
- `WIP`: implementation exists but is incomplete, recently changed, or not yet validated.
- `dormant`: code/data exists but is not actively exercised by the current validated path.

## System Overview

```text
UI and service boundary
  React/Vite/Electron
  backend/server.py (FastAPI + Socket.IO)

Session orchestration
  backend/night_runner.py
  backend/study_agent.py
  backend/benchmark_loop.py
  backend/swarm_engine.py

Cognitive workspace
  backend/cognition/cognition_core.py
    - layer 0 anchor from SQLite
    - executive summary
    - relational context
    - shared environment event bus
    - emergence audit
  backend/cognition/workspace_arbiter.py
    - WorkspaceArbiter
    - ValenceField
  backend/cognition/feedback_field.py
  backend/cognition/mood_workspace_coupling.py
  backend/context_arbiter.py

Memory and learning stores
  SQLite: shard_memory/shard.db
  ChromaDB: shard_memory/chromadb, shard_memory/strategy_db
  JSON/JSONL: shard_memory/*.json, shard_memory/*.jsonl

Execution and verification
  backend/sandbox_runner.py
  backend/swe_agent.py
  backend/swe_security.py
  tests/
  docs/experiments/
```

The architecture is layered, but not clean-room. SHARD is a prototype with multiple historical paths still present. The main documented loop today is: select or force a topic, gather or cache sources, synthesize a study output, evaluate it, persist results, update memory/cognitive state, and optionally replay or benchmark.

## GWT Implementation Detail

The Global Workspace-style layer is implemented across several files rather than as one monolithic subsystem.

Phase 1 is global workspace competition in `backend/cognition/cognition_core.py` and `backend/cognition/workspace_arbiter.py`. `CognitionCore.resolve_workspace(topic, mood_score)` gathers proposals, applies anti-monopoly boost through `WorkspaceSafetyGuard`, runs `WorkspaceArbiter.competition()`, records telemetry, broadcasts `workspace_winner`, and falls back to anchor/executive context if ignition fails. `CognitionCore.drain_session_winners()` accumulates every winner from synthesis and retries so downstream mood coupling can see full topic history.

Phase 2 is per-topic context arbitration in `backend/context_arbiter.py`. It reuses `ValenceField` semantics, then applies task-mode post-modulation. Tactical mode boosts `skill_library` and `past_context` while suppressing identity, behavior, and mood blocks; strategic mode keeps broader context eligible.

Phase 3 is bid modulation in `backend/cognition/feedback_field.py`. Winners decay, losers receive recovery boost, multipliers are capped, and optional persistence writes to `feedback_field_state`. The table exists in SQLite but currently has 0 rows, so persistent feedback should be described as available code, not active inspected state.

Phase 4 is mood-to-workspace coupling in `backend/cognition/mood_workspace_coupling.py` plus `backend/night_runner.py`. `NightRunner` initializes the coupling path, computes mood with `workspace_bias`, drains session winners, and calls `on_workspace_result(...)` for each winner. D2.0 showed this can be undersolicited in easy natural runs; the forced-mood microtest isolates the mechanism and shows winner shifts when mood is forced. D2.1C adds a sharper caveat: `workspace_bias` needs provenance, because non-zero bias can come from synthetic ignition-failure fallback, while real winners can be silent if their configured coupling delta is zero.

Layer E is the empirical block used only in research mode. `CognitionCore.relational_context(topic, research_mode=True, mood_score=...)` calls `query_empirical(topic)`, reads `research_hypotheses`, includes up to 3 relevant non-pending rows, and excludes `PENDING` and `INCONCLUSIVE` rows from prompt evidence. This block enters retry/synthesis context as knowledge, not as a proof claim.

Two baselines are explicitly supported in code. `--no-l3` disables L3 relational context for A/B comparison, and `GWT_OFF` in `backend/night_runner.py` preserves a sequential-injection baseline. Commit `343687e` matters here: attempt-0 synthesize-time cognitive injection was reverted because it poisoned the prompt; the current strongest path is retry/stress context rather than unconditional injection. D2.1D should test the `tensions` calibration hypothesis separately; D2.1C intentionally does not change `_WINNER_BIAS`.

## Module Reference

`SemanticMemory` (`backend/semantic_memory.py`) is a ChromaDB-backed long-term memory over three collections: `episodes`, `knowledge`, and `errors`. It indexes benchmark episodes, knowledge-base markdown, recurring error patterns, and some `CognitionCore` events. Status: `verified` as executable code and verified Chroma state (`episodes` 1,398; `knowledge` 250; `errors` 148), but semantic quality is not claimed as an outcome benchmark.

`StrategyMemory` (`backend/strategy_memory.py`) stores and retrieves successful strategies in the `strategy_memory` Chroma collection. It includes async-safe write locking, protocol inference, strategy extraction from benchmark diffs, utility scoring, cross-inject queries, and a pivot mechanism for chronic blocks. Status: `verified`; focused cognitive subset includes `tests/test_strategy_memory.py`, and Chroma inspection found 1,201 strategy records.

`GraphRAG` (`backend/graph_rag.py`) extracts and queries causal relations in SQLite table `knowledge_graph`. It validates relation types, stores source/target/relation/confidence/context/topic, exposes causal prompt context, graph stats, epistemic profiles, and verified relation upserts. Status: `verified` for parser/query behavior via `tests/test_graph_rag.py`; current DB has 3,161 relations, including 1,456 verified, 282 disputed, and 1,398 untested. The DB also contains 2 legacy `does_not_improve` rows outside the current valid relation set.

`CapabilityGraph` (`backend/capability_graph.py`) tracks acquired capabilities, dependencies, normalization of composite topics, contamination filtering, SQLite persistence, and JSON backup at `shard_memory/capability_graph.json`. Status: `experimental`: the runtime store is populated and traceable (1,054 capabilities, 803 dependency rows), but `tests/test_capability_graph.py::TestCapabilityGraph::test_persistence` currently fails in this sandbox because JSON backup writes hit temp permission errors while the test DB is intentionally disabled.

`SkillLibrary` (`backend/skill_library.py`) stores certified skills and saved implementations in SQLite tables `skill_library` and `skill_implementations`. It upserts best scores, returns exact or related skill context, saves implementation code only above pass-rate threshold, and proposes curriculum topics from GraphRAG overlap. Status: `verified`; current DB has 243 skill rows and 176 implementation rows.

`BenchmarkLoop` (`backend/benchmark_loop.py`) is the closed code-repair loop for benchmark tasks. It loads task files, asks an LLM or swarm to patch, validates syntax, runs language-specific tests, records attempts, saves episodes, updates semantic memory, and optionally stores strategy diffs after victory. Status: `experimental`: the loop is real and used by the project, but old headline benchmark claims are not carried forward without a fresh clean run.

`SwarmEngine` (`backend/swarm_engine.py`) implements a multi-agent repair pipeline: Architect, Coder, baseline Critic, and selected specialized reviewers for concurrency, edge cases, security, performance, and data integrity. It includes a token-budget meta observer, rollback mode, focus mode, code extraction, and patch prompts. Status: `verified` for helper behavior and mocked flow through `tests/test_swarm_engine.py`.

`ExperimentInventor` (`backend/experiment_inventor.py`) generates candidate experiment topics by combining an existing target skill with sampled atomic capabilities, guarded by topic validity filters and duplicate tracking. Status: `experimental`; it is simple executable logic, but generated-topic quality is not validated here.

`ExperimentReplay` (`backend/experiment_replay.py`) manages a persistent replay backlog in `shard_memory/experiment_replay.json` for experiments that should be revisited. It supports add, remove, random next-topic selection, duplicate suppression, validity filtering, and atomic JSON writes. Status: `verified`; `tests/test_experiment_replay.py` is green in the runtime/utility subset, and the current JSON list has 248 entries.

`Experiment Engine` (`backend/experiment_phases.py`, `backend/experiment_store.py`) is the research-mode hypothesis path. `ExperimentDesignPhase` generates executable Python for a hypothesis test, `ExperimentSandboxPhase` runs local code in `DockerSandboxRunner`, and `ExperimentValidatePhase` writes CONFIRMED/REFUTED/INCONCLUSIVE-style outcomes through the hypothesis store. The phases are self-gating and non-fatal when `research_mode=False` or a hypothesis is unsuitable. The path includes arXiv novelty checks, feasibility routing, four-section spec validation, alignment validation, N=3 local replication, Antagonist review, optional Kaggle/Modal queues, and GraphRAG feedback for confirmed/refuted outcomes. Status: `experimental`; code exists and is wired from `backend/study_agent.py`, but no current README-level scientific outcome claim is made from it.

`MoodEngine` (`backend/mood_engine.py`) computes a global mood score from frustration, recent weighted certification rate, momentum, and `workspace_bias`. It persists `mood_state.json`, appends every compute to `mood_history.jsonl`, exposes prompt hints and behavior directives, and broadcasts mood shifts when registered with `CognitionCore`. Status: `experimental`: instrumentation is verified, but natural-regime causal effect remains under test.

`IdentityCore` (`backend/identity_core.py`) rebuilds persistent identity facts from SQLite and optionally asks an LLM only for the narrative string. It computes sessions lived, total attempts, certified count, weighted cert rate, strong/weak domains, peak skills, chronic blocks, self-esteem, and trajectory, then persists `identity.json`. Status: `experimental`: the code is real and current JSON is populated, but identity-derived behavior effects are not yet isolated as causal outcomes.

`CognitionCore` (`backend/cognition/cognition_core.py`) is the shared cognitive environment. It builds an anchor from SQLite, an executive summary, relational context, event broadcasts, workspace proposals, workspace resolution, session winner tracking, and a Shadow Diagnostic Layer that audits measurable behavioral deltas rather than text. Status: `verified` for focused tests in `tests/test_cognition_core.py`; outcome-level GWT claims remain experimental.

`WorkspaceArbiter` (`backend/cognition/workspace_arbiter.py`) accepts workspace proposals, applies `ValenceField.mod(block_type, mood_score)`, optionally applies `FeedbackField`, filters by ignition threshold, selects within token budget, falls back on failed ignition, and exposes winners. Status: `verified`; `tests/test_workspace_arbiter.py` and `backend/gwt_mood_microtest.py` show bid/winner sensitivity under forced mood.

`ValenceField` (`backend/cognition/workspace_arbiter.py`) is the mood-to-bid multiplier table. It suppresses identity and real identity under negative valence below -0.3, boosts experience under frustration, boosts goal under positive valence above 0.3, and boosts desire/behavior directives under high arousal. Status: `verified` as code path after commits `9e85370` and `14b434f`; natural activation frequency is still experimental.

`FeedbackField` (`backend/cognition/feedback_field.py`) applies reentrant bid modulation: winners decay, losers boost, multipliers are capped and can optionally persist to SQLite table `feedback_field_state`. Status: `verified` via `tests/test_feedback_field.py`; current DB table exists but has 0 rows, so persistent feedback state is not active in the inspected database.

`MoodWorkspaceCoupling` (`backend/cognition/mood_workspace_coupling.py`) closes the loop from workspace result back to mood. It decays prior valence/arousal bias, applies per-winner bias, applies negative bias for ignition failure, can propagate to `DesireEngine`, and exposes `get_bias()` for `MoodEngine.compute()`. Status: `experimental`: tests are green, but D2.0 showed natural/easy runs left `workspace_bias` at 0.0.

`ContextArbiter` (`backend/context_arbiter.py`) performs per-topic context competition using the same `ValenceField` semantics as the workspace layer. It ranks candidate blocks, applies tactical/strategic post-modulation, respects token budget, preserves stable reading order, and falls back to the highest bid when nothing clears threshold. Status: `verified` via `tests/test_context_arbiter.py`.

`WorkspaceSafetyGuard` (`backend/cognition/workspace_safety.py`) adds safety behavior around the workspace: ignition fallback context, anti-monopoly detection, diversity boost, mood death-spiral detection, override directives, telemetry, and reset. Status: `verified`; included in the 121-pass SWE/security subset through `tests/test_workspace_safety.py`.

`DesireEngine` (`backend/desire_engine.py`) tracks per-topic desire/frustration signals and receives workspace bias from `MoodWorkspaceCoupling`. It participates in topic selection and mood computation. Status: `verified` only for the workspace-bias behavior covered by `tests/test_desire_engine_workspace_bias.py`; broader motivational policy is experimental.

`StudyAgent` (`backend/study_agent.py`) implements MAP, AGGREGATE, SYNTHESIZE, and validation-style phases for study topics. It now includes `D2_CACHED_SOURCES_PATH` hooks for cached MAP/AGGREGATE in controlled D2 harness runs. Status: `experimental`: the D2.1A hook is validated as harness behavior, not as cognitive performance.

`NightRunner` (`backend/night_runner.py`) is the main session loop: topic selection, forced topic mode, cognitive registration, mood computation, context arbitration, study execution, activation logging, and D2 subprocess entry. Status: `experimental`: it is the integration path, but full end-to-end behavior is too broad to claim from unit tests alone.

`D2 harness` (`backend/d2_1a_cache_sources.py`, `backend/d2_1a_benchmark.py`, `backend/d2_1a_analyze.py`, `backend/d2_1b_benchmark.py`, `backend/d2_1b_analyze.py`, `backend/d2_1c_benchmark.py`, `backend/d2_1c_analyze.py`) isolates sources, subprocesses, paired replicas, manifests, sequential topics, and analysis for frustration/GWT experiments. Status: `verified` for D2.1A harness validation by `docs/experiments/d2_1a_harness_validation.md`; `experimental` for D2.1B/D2.1C GWT stress interpretation. D2.1C is documented as `INCONCLUSIVE_MECHANISM_DISCONNECTED`, not as a performance result.

`DockerSandboxRunner` (`backend/sandbox_runner.py`) runs generated study code inside a `shard-sandbox:latest` Docker image with non-root execution, memory/PID limits, network disabled, path validation, timeouts, and cleanup handling. Status: `verified` by tests in design, but current full-suite execution errors around temp permissions prevent using the full sandbox test file as a clean green signal in this run.

`SWE security gates` (`backend/swe_agent.py`, `backend/swe_security.py`, `tests/test_swe_security.py`) reject dangerous imports, dangerous calls, syntax errors, and classic sandbox escape patterns for repair tasks. Status: `verified`; `tests/test_swe_security.py` and `tests/test_swe_agent.py` are part of the 121-pass security subset.

`Electron bridge` (`electron/main.js`, `electron/preload.js`) exposes renderer APIs through `contextBridge` with `nodeIntegration: false` and `contextIsolation: true`. Status: `verified-fixed` relative to commit `ab10b49`; no new security claim beyond the inspected configuration.

`Server auth boundary` (`backend/server.py`) uses FastAPI plus Socket.IO. It tracks authenticated Socket.IO session IDs and gates several events through `_require_auth`, while face auth can be disabled and then auto-authenticates clients. Status: `WIP`; auth exists but is incomplete as a system security boundary.

`CAD agent` (`backend/cad_agent.py`) generates and verifies CAD artifacts and still uses local subprocess execution paths. Status: `WIP/security-risk`; useful functionality exists, but host execution remains a flagged security boundary.

## Data Flows

### Study Loop

1. `NightRunner` selects a topic or receives `--force-topic`.
2. `StudyAgent` runs MAP and AGGREGATE, unless `D2_CACHED_SOURCES_PATH` points to frozen sources.
3. Cognitive context is assembled through `CognitionCore.relational_context()` and/or `ContextArbiter`.
4. `WorkspaceArbiter` resolves proposals using current `mood_score`.
5. The study output is evaluated, recorded in SQLite/JSON/Chroma where applicable, and may update `SkillLibrary`, `CapabilityGraph`, `StrategyMemory`, `GraphRAG`, `MoodEngine`, and `IdentityCore`.
6. `CognitionCore.drain_session_winners()` feeds `MoodWorkspaceCoupling`; its bias can enter the next `MoodEngine.compute()`.

### Benchmark Repair Loop

1. `BenchmarkLoop` reads task source, tests, and README.
2. It builds a prompt with environment probe, benchmark memory, knowledge bridge, GraphRAG, semantic memory, and optional strategy signals.
3. The LLM or `SwarmEngine` proposes a patch.
4. The loop validates syntax, writes the candidate file, runs tests, parses failures, and repeats until success or attempt limit.
5. Success stores a benchmark episode and may store a strategy diff; failure can enqueue study topics.

### GWT Loop

The GWT path is currently strongest in retry/stress contexts. Proposals enter `WorkspaceArbiter`, `ValenceField` modulates bids using `mood_score`, `FeedbackField` applies winner/loser history, winners are broadcast globally, and `MoodWorkspaceCoupling` can turn winner history into a mood bias. D2.0 showed that easy/natural runs can leave this path undersolicited; the forced-mood microtest shows the valence lever itself is alive. D2.1C showed that the stress-dominant winner can be `tensions`, which is semantically plausible but currently numerically silent because `_WINNER_BIAS["tensions"] == (0.00, 0.00)`.

### Scientific Research Loop

1. `StudyAgent` enters the research path only when `research_mode=True`.
2. `_fetch_arxiv_phase(topic)` can fetch up to 5 arXiv sources and pass them into the MAP-compatible source path.
3. The hypothesis path checks novelty with arXiv overlap plus LLM semantic/literature judging; failures default to novel rather than blocking the run.
4. Feasibility gates classify the hypothesis as local, Kaggle, Modal, or invalid. Real-world data requirements can be queued through `backend/kaggle_runner.py` or `backend/modal_runner.py`.
5. `ExperimentDesignPhase` requires a four-section spec: `MECHANISM`, `INTERVENTION`, `MEASUREMENT`, and `SUCCESS CRITERION`. Free-form specs get one forced rewrite; weak metric linkage, simulation grounding, and proxy metrics trigger binding rewrites.
6. `_validate_experiment_alignment()` scores causal link, domain fidelity, falsifiability, implementability, and baseline clarity. Scores >=0.70 are VALID, >=0.30 are REWRITE, and <0.30 are INVALID; calibration logs are written under `shard_workspace/experiments/alignment_log_*.jsonl`.
7. `ExperimentSandboxPhase` runs local experiment code as three independent replicas, parses `RESULT: <float>`, and stores mean/std/n in the result payload.
8. `_antagonist_review(...)` audits the experiment for cheating, bugs, and misalignment. Correctable failures can rewrite code; fatal failures or max attempts end as INCONCLUSIVE.
9. `ExperimentValidatePhase` interprets the sandbox output, updates confidence, persists to `research_hypotheses`, and can feed confirmed/refuted edges into GraphRAG.

Known WIP issue: `ExperimentValidatePhase` currently maps REFUTED outcomes toward `does_not_improve`, but `backend/graph_rag.py` does not include `does_not_improve` in its current valid relation-type set. The inspected database has 2 legacy `does_not_improve` rows. Treat this as a schema/policy mismatch to fix before using research outputs as durable graph evidence.

## Persistence

SQLite lives at `shard_memory/shard.db`. Python `sqlite3` inspection on 2026-05-05 found 27 total tables including internal `sqlite_sequence`; that means 26 application tables:

```text
activation_log, affordance_cache, capabilities, capability_deps,
environment_events, epistemic_velocity_log, experiments, failed_cache,
feedback_field_state, improvement_tickets, knowledge_graph, kv_store,
llm_cache, memories, memory_links, pivot_events, predictions,
prerequisite_cache, refactor_history, research_hypotheses,
schema_version, self_inconsistencies, session_reflections,
skill_implementations, skill_library, synaptic_weights
```

Current inspected SQLite counts:

| Table/query | Count |
|---|---:|
| `skill_library` | 243 |
| `skill_implementations` | 176 |
| `knowledge_graph` | 3,161 |
| `capabilities` | 1,054 |
| `capability_deps` | 803 |
| `experiments` | 3,938 |
| `experiments WHERE certified=1` | 2,519 |
| `activation_log` | 1,285 |
| `COUNT(DISTINCT session_id) FROM activation_log` | 618 |
| `feedback_field_state` | 0 |
| `research_hypotheses` | 80 |
| `research_hypotheses WHERE code IS NOT NULL AND code != ''` | 31 |
| `research_hypotheses WHERE result IS NOT NULL AND result != ''` | 36 |

`research_hypotheses` status counts in the inspected DB:

| Status | Count |
|---|---:|
| `SKIPPED_TOO_COMPLEX` | 33 |
| `REFUTED` | 22 |
| `FAILED` | 10 |
| `INCONCLUSIVE` | 8 |
| `CONFIRMED` | 5 |
| `KAGGLE_READY` | 1 |
| `PENDING` | 1 |

ChromaDB persistence:

| Path | Collections/counts |
|---|---|
| `shard_memory/chromadb` | `episodes` 1,398; `knowledge` 250; `errors` 148 |
| `shard_memory/strategy_db` | `strategy_memory` 1,201 |
| `shard_memory/experiment_db` | 0 collections in this inspection |

JSON/JSONL persistence includes `capability_graph.json` (1,054 keys), `experiment_replay.json` (248 entries), `benchmark_episodes.json` (39 top-level task keys), `mood_state.json`, `mood_history.jsonl`, `identity.json`, `world_model.json`, `principles.json`, and other runtime state files. These files are runtime artifacts; counts can change after normal SHARD sessions.

## Security Model

The strongest security boundary is `DockerSandboxRunner` in `backend/sandbox_runner.py`: it runs generated code in a Docker image, disables network, applies process/memory limits, uses a non-root user, validates sandbox paths, and attempts timeout cleanup.

The SWE repair path has AST/string-level safety checks that block critical imports and calls. The focused security subset (`tests/test_swe_security.py`, `tests/test_swe_agent.py`, `tests/test_workspace_safety.py`, `tests/test_authenticator.py`) passed 121 tests in this workspace.

Electron renderer hardening is present after `ab10b49`: `electron/main.js` has `nodeIntegration: false` and `contextIsolation: true`, and `electron/preload.js` exposes a bounded API through `contextBridge`.

Known gaps remain. `backend/server.py` has event-level auth checks but can auto-authenticate when face auth is disabled, so it should not be described as a complete auth boundary. `backend/cad_agent.py` still uses local subprocess execution, so CAD generation remains a host-exec risk. Some sandbox-related tests currently hit temp-directory permission errors in this environment, so a clean full-suite security verdict is not claimed.

## Empirical Methodology

SHARD uses A/B and paired-replica thinking rather than one-off demos. The D2.0 result is explicitly `INCONCLUSIVE_HARNESS`, not a hidden negative or positive result: both arms degraded together, external-service anomalies were above threshold, mood never crossed -0.3, and `workspace_bias` stayed at 0.0.

D2.1A fixed the harness first: cached/fixed sources, subprocess isolation per arm, identical config replicas, manifest-per-run, mood sample archiving, and strict contamination rules. The documented outcome is harness-only PASS on 2026-05-05. It is not an outcome-level performance claim.

D2.1B failed the pre-registered single-topic stress prediction, but it exposed an observability issue: winner bias is drained after a topic, so a single-cycle protocol cannot reliably observe next-cycle coupling.

D2.1C used a sequential two-topic protocol and is classified as `INCONCLUSIVE_MECHANISM_DISCONNECTED`. ARM_OFF produced non-zero synthetic ignition-failure fallback bias, while ARM_ON reached real workspace competition but the dominant stress winner `tensions` had zero configured MoodWorkspaceCoupling bias. The next valid step is D2.1D: pre-register a calibration patch and rerun the same protocol.

Forced-mood microtesting is used to isolate mechanism from outcome. `backend/gwt_mood_microtest.py` bypasses the full pipeline and checks whether mood values change bids/winners. It currently returns ESITO A, which means the GWT lever is alive under forced conditions. Outcome causality still requires a later stress protocol with bias provenance and behavior-level metrics.

Scientific research mode uses the same falsification posture. CONFIRMED and REFUTED rows in `research_hypotheses` are internal experimental records gated by novelty, feasibility, spec validation, sandbox replication, and review. They should not be promoted to external scientific claims unless the experiment artifact, source assumptions, and result interpretation have been reviewed independently.

The falsification pattern is part of the method: inject an idea, instrument it, revert or narrow it when evidence disagrees, and document the boundary. Commits `343687e`, `9e85370`, `14b434f`, `4dbb9d8`, and `4c37d65` are the current trail.

## Evidence Commands

Representative commands used for this architecture pass:

```powershell
git log --oneline -15
python -m pytest --collect-only -q
python -m pytest -q
python -m pytest -q tests/test_cognition_core.py tests/test_workspace_arbiter.py tests/test_feedback_field.py tests/test_mood_workspace_coupling.py tests/test_context_arbiter.py tests/test_graph_rag.py tests/test_skill_discovery.py tests/test_strategy_memory.py tests/test_swarm_engine.py tests/test_gwt_ab_test.py tests/test_desire_engine_workspace_bias.py
python -m pytest -q tests/test_swe_security.py tests/test_swe_agent.py tests/test_workspace_safety.py tests/test_authenticator.py
python backend/gwt_mood_microtest.py
```

`sqlite3` CLI was not available, so SQLite counts were gathered with Python's standard library:

```python
import sqlite3
conn = sqlite3.connect("shard_memory/shard.db")
conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
conn.execute("SELECT COUNT(*) FROM knowledge_graph")
```
