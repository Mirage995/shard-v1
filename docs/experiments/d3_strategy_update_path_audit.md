# D3 Strategy Update Path Audit

## Status

Audit only. No code changes. No benchmark run.

## Executive Finding

Strategy memory is read but not updated because the normal D3 study protocol reaches retrieval, memory write, and failure-memory paths, but does not reach any StrategyMemory write/update gate: the available writers are success-, repair-, benchmark-victory-, strategy-object-, or EvoScientist-pivot gated.

## Strategy Memory API

| function | file | purpose | read/write/update | callers |
| --- | --- | --- | --- | --- |
| `StrategyMemory.query(topic, k=3, cross_inject_queries=None)` | `backend/strategy_memory.py` | Semantic retrieval from the `strategy_memory` Chroma collection; returns ranked prior strategies. | read | `backend/night_runner.py` cycle setup; `backend/benchmark_loop.py` strategy signal; indirect/direct retrieval via `backend/study_agent.py::retrieve_strategy` querying `collection` directly. |
| `StrategyMemory.store_strategy(topic, strategy, outcome, score=0.0)` | `backend/strategy_memory.py` | Append a text strategy document with topic/outcome/score/running stats/protocol metadata. | write | `study_phases.py::_extract_and_store_strategy`; `study_phases.py` SWE repair / auto-debug success paths; `night_runner.py` EvoScientist pivot path; `strategy_memory.py::store_from_benchmark`; async wrapper callers. |
| `StrategyMemory.store_strategy_object(strategy)` | `backend/strategy_memory.py` | Append a `Strategy` object as a Chroma document with strategy metadata. | write | `study_phases.py::_extract_and_store_strategy`; `study_phases.py::PostStudyPhase` if `ctx.strategy_obj` exists. |
| `StrategyMemory.store_from_benchmark(task_key, prev_code, winning_code, attempts_used)` | `backend/strategy_memory.py` | Diff last failed code vs winning benchmark code and store an extracted pattern. | write | `backend/benchmark_loop.py` only after benchmark victory with more than one attempt. |
| `StrategyMemory.update_evolved_strategy_score(topic, strategy_text, real_score, real_outcome)` | `backend/strategy_memory.py` | Update metadata for a previously stored `outcome="evolved"` strategy. | update | `backend/night_runner.py` only if `_evolved_strategy` was created during a chronic-block pivot. |
| `StrategyMemory.pivot_on_chronic_block(topic)` | `backend/strategy_memory.py` | Delete strategies for a chronically blocked topic to force a new approach. | delete/reset | `backend/night_runner.py` chronic fail-streak / near-miss loop handling. |
| `StrategyTracker.update_strategy(strategy_obj, success)` | `backend/strategy_tracker.py` | API placeholder for strategy effectiveness tracking. | no-op | `study_phases.py::PostStudyPhase`; currently returns `None` and persists nothing. |

## Update Path Call Graph

Direct update/write paths found:

1. `study_phases.py::CertifyRetryGroup.run` calls `_extract_and_store_strategy(ctx)` during each validation/evaluation retry cycle.
   - `_extract_and_store_strategy` calls `ctx.agent.strategy_memory.extract_strategy(experiment)`.
   - `StrategyMemory.extract_strategy` returns `None` if `score < 5.0` and verdict is not `PASS`.
   - If extraction succeeds, it calls `store_strategy_async(...)`.
   - It also calls `StrategyExtractor.extract_from_experiment(...)`, but `backend/strategy_extractor.py` is a stub returning `None`, so `ctx.strategy_obj` is normally not created.

2. `study_phases.py::PostStudyPhase.run` writes a strategy object only if `ctx.strategy_obj` exists.
   - Because `StrategyExtractor.extract_from_experiment` is currently a no-op stub, this branch is generally not reached.
   - `StrategyTracker.update_strategy(...)` is also a no-op stub.

3. `night_runner.py` reads strategy memory every cycle with `strategy_memory.query(topic, k=1)`.
   - It updates an evolved strategy only if `_evolved_strategy` exists.
   - `_evolved_strategy` is produced only inside the chronic-block pivot path before `pivot_on_chronic_block`.
   - D3.0B/C forced one cycle per topic and did not trigger chronic-block pivot conditions.

4. `benchmark_loop.py` writes strategy memory only after benchmark victory.
   - The call is `StrategyMemory().store_from_benchmark(...)`.
   - It requires `attempt_num > 1`, at least two benchmark attempts, and a pattern match in the code diff.
   - D3.0B/C did not run this benchmark victory path as the learning mechanism under test.

5. SWE repair / auto-debug paths in `study_phases.py` can store success strategies.
   - They are gated on a successful repair/patch.
   - D3.0B/C did not show this as the active update route.

## Update Preconditions

| precondition | required? | source | satisfied in D3.0B/C? | notes |
| --- | --- | --- | --- | --- |
| Strategy retrieval available | yes for reads | `night_runner.py` cycle setup / `StrategyMemory.query` | yes | D3.0B/C saw strategy reads in every session. |
| Strategy extraction returns `strategy_info` | yes for normal study write | `StrategyMemory.extract_strategy` | no observable evidence | Extraction filters out low-score non-PASS experiments (`score < 5.0` and verdict not `PASS`). D3 scores were mostly low and no store markers appeared. |
| Strategy object exists (`ctx.strategy_obj`) | yes for object write | `StrategyExtractor.extract_from_experiment` | no | `StrategyExtractor` is a transition stub returning `None`. |
| Certification/success signal | required for several rich writes | `ctx.certified`, benchmark victory, SWE repair success | mostly no / not the relevant path | Semantic certified knowledge and benchmark-victory strategies are success-gated. |
| Benchmark victory with code diff | yes for `store_from_benchmark` | `benchmark_loop.py` | no | D3.0B/C used the study/night-runner protocol, not benchmark-loop victory learning. |
| Chronic-block pivot and evolved strategy | yes for EvoScientist update | `night_runner.py` pivot path | no | Forced one-cycle-per-topic D3 protocol does not accumulate same-topic fail streaks inside a single night-runner session. |
| Failure attribution structured as strategy candidate | needed for post-failure strategy learning | no general path found | no | Failure memories are stored, but not converted into append-only strategy records. |
| Persistence across sessions | needed for longitudinal learning | D3 snapshot/restore harness | yes | D3.0C persistence checks passed; persistence is not the primary blocker. |

## Failure-Path Learning

There is a failure-memory path, but not a general failure-to-strategy-update path.

Observed failure handling:

- `CertifyRetryGroup.run` stores `EPISODE_FAILURE` via `_store_failure_memory(ctx)` when a topic is not certified and the best score is high enough.
- `PostStudyPhase.run` stores episodic outcomes and semantic error patterns for failed sessions with a classified error.
- Init/load paths can later inject previous failures into context.

Missing path:

- No normal append-only `failed_strategy` / `failure_mode` / `recovery_hint` / `avoid_this_next_time` strategy-memory record is created after uncertified study failure.
- Failure attribution is persisted as memory/context, not as a StrategyMemory update.
- The existing strategy memory behaves as a retrieval store for prior successful or special-case strategies, not as a complete learning store for failed-session strategy deltas.

## Why D3.0B/C Saw Zero Updates

D3.0B/C saw zero updates because the D3 protocol does not activate the available StrategyMemory write gates:

- It reaches `StrategyMemory.query`, so reads are visible.
- It reaches memory/failure-memory storage, so memory writes are visible.
- It does not produce `ctx.strategy_obj`, because `StrategyExtractor.extract_from_experiment` currently returns `None`.
- It does not create benchmark-victory diffs, so `store_from_benchmark` is not reached.
- It does not trigger chronic-block pivot/EvoScientist inside the forced one-cycle topic sessions, so `update_evolved_strategy_score` is not reached.
- It does not have a post-failure StrategyMemory append path, so failed/near-miss D3 sessions do not become strategy updates.

The most precise diagnosis is: update path exists in narrow special cases, but the D3 study protocol does not call it; normal failures are stored as memory, not as strategy-learning records.

## Minimal Fix Options

### Option A -- instrumentation only

Add structured markers at the existing gates without adding any new writes:

- `strategy_extraction_attempted`
- `strategy_extraction_returned`
- `strategy_extraction_skip_reason`
- `strategy_object_extraction_attempted`
- `strategy_object_extraction_returned`
- `post_study_strategy_object_present`
- `evolved_strategy_available`
- `benchmark_strategy_store_path_hit`

This is appropriate if the next question is still observability: which existing gate is skipping and why.

### Option B -- minimal post-failure append-only update

Add one explicit, append-only post-failure strategy record after uncertified study completion, without changing scoring, retry, certification, or topic handling.

Candidate fields:

- `failed_strategy_summary`
- `failure_mode`
- `suggested_alternative_strategy`
- `topic_family`
- `source_session_id`
- `final_score`
- `certification_verdict`
- `outcome="failure_learning"`

This would make failure-path strategy learning real and measurable while preserving existing decision thresholds. It should be gated by a minimal structured failure attribution, and it should not overwrite successful strategies.

## Recommendation

Recommend Option B, preceded by a tiny marker-only guard if desired.

Reason: the core issue is no longer that the update path is invisible. The audit shows the normal D3 protocol has no general post-failure StrategyMemory update route. Existing writes are too narrow for D3 learning-curve validation: success/repair/benchmark/pivot/object-stub paths do not fire under the current longitudinal study protocol.

The next pre-registered experiment should therefore test a minimal append-only post-failure strategy update. It should not modify scoring, retry policy, certification threshold, `_WINNER_BIAS`, ValenceField, stress injection, or topic handling.

## Forbidden Claims

- GWT improves SHARD performance.
- SHARD learns autonomously.
- Strategy learning is proven.
