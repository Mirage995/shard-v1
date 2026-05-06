# D2.2D Micro Decision Coupling Report

Planning commit: `8b10327ad5f2c5e9ffcd75cd14b71e74ca8503ed`
Run root: `shard_workspace/d2_2d_runs/20260506_152450`
Expected subprocesses: `8`
Actual subprocesses: `8`
Aborted: `False`

## Experimental Question

If calibrated GWT/Mood signal is connected as a minimal reflection directive, does ARM_ON show measurable differences in strategy shift, repeated strategy, retry quality, recovery, or loop-risk?

## Micro-Fix Applied

- Target gate: `reflection_trigger` / retry reflection prompt path.
- Modified path: `backend/study_phases.py::_retry_gap_fill`.
- Mechanism: when L3 is active, the dominant workspace winner is `tensions`, mood is stressed, and repeated failure is detected, inject a reflection/strategy-shift directive into the next retry prompt.
- The directive is a modifier, not an override.

Behavior/scoring guardrails:
- `MAX_RETRY` unchanged.
- Certification threshold unchanged.
- Scoring logic unchanged.
- `_WINNER_BIAS` unchanged in D2.2D.
- `ValenceField` unchanged.
- Stress injection unchanged.
- Topic sequence and topic handling unchanged.

## Protocol

- Same cached-source harness lineage as D2.1A/D2.1E.
- Zero live DDGS/Brave/Playwright calls expected during benchmark subprocesses.
- Subprocess isolation.
- ARM_OFF vs ARM_ON.
- Controlled stress injection.
- 2 topic sequences x 2 replicas x 2 arms = 8 subprocesses.
- D2.2D micro decision coupling only, not D2.2 full.

Topic sequences:
- `seq_01_oop_to_asyncio`: `python OOP design patterns` -> `asyncio advanced patterns`
- `seq_02_sql_to_error_handling`: `sql injection prevention python` -> `python error handling patterns`

**Final verdict: `PASS_WEAK`**

> ARM_ON applies the reflection micro-coupling and shows decision-adjacent metric movement, but not enough outcome-level improvement for a strong claim.

## Harness Sanity

| Check | Result |
|---|---|
| `expected_subprocess_count` | PASS |
| `all_exit_zero` | PASS |
| `zero_live_calls` | PASS |
| `cache_hits_ok` | PASS |
| `cache_hash_stable` | PASS |
| `no_contamination_flag` | PASS |
| `stress_observed_all` | PASS |
| `sequence_observed_all` | PASS |
| `mood_samples_present` | PASS |
| `fallback_threshold_ok` | PASS |
| `abort_reason_absent` | PASS |

## Raw Traces Aggregate

| sequence | rep | arm | mood_traj | wb_traj | observer_mood | observer_wb | tensions_trace_count | fallback_provenance |
|---|---:|---|---|---|---|---|---:|---|
| `seq_01_oop_to_asyncio` | 1 | `ARM_OFF` | `[-0.5, -0.5, 0.0, -0.65, 0.0]` | `[0.0, 0.0, 0.0, -0.15, 0.0]` | `[0.0, -0.65, 0.0]` | `[0.0, -0.15, 0.0]` | 0 | `synthetic_ignition_failure_fallback` |
| `seq_01_oop_to_asyncio` | 1 | `ARM_ON` | `[-0.5, -0.5, 0.0, -0.595, 0.0]` | `[0.0, 0.0, 0.0, -0.095, 0.0]` | `[0.0, -0.595, 0.0]` | `[0.0, -0.095, 0.0]` | 4 | `not_observed` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_OFF` | `[-0.5, -0.5, 0.0, -0.65, 0.0]` | `[0.0, 0.0, 0.0, -0.15, 0.0]` | `[0.0, -0.65, 0.0]` | `[0.0, -0.15, 0.0]` | 0 | `synthetic_ignition_failure_fallback` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_ON` | `[-0.5, -0.5, 0.0, -0.595, 0.0]` | `[0.0, 0.0, 0.0, -0.095, 0.0]` | `[0.0, -0.595, 0.0]` | `[0.0, -0.095, 0.0]` | 4 | `not_observed` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_OFF` | `[-0.5, -0.5, 0.0, -0.65, 0.0]` | `[0.0, 0.0, 0.0, -0.15, 0.0]` | `[0.0, -0.65, 0.0]` | `[0.0, -0.15, 0.0]` | 0 | `synthetic_ignition_failure_fallback` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_ON` | `[-0.5, -0.5, 0.0, -0.595, 0.0]` | `[0.0, 0.0, 0.0, -0.095, 0.0]` | `[0.0, -0.595, 0.0]` | `[0.0, -0.095, 0.0]` | 4 | `not_observed` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_OFF` | `[-0.5, -0.5, 0.0, -0.65, 0.0]` | `[0.0, 0.0, 0.0, -0.15, 0.0]` | `[0.0, -0.65, 0.0]` | `[0.0, -0.15, 0.0]` | 0 | `synthetic_ignition_failure_fallback` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_ON` | `[-0.5, -0.5, 0.0, -0.348, 0.0]` | `[0.0, 0.0, 0.0, 0.152, 0.0]` | `[0.0, -0.348, 0.0]` | `[0.0, 0.152, 0.0]` | 4 | `not_observed` |

## Per Run Behavioral Metrics

| sequence | rep | arm | recovery_success | retries_count | strategy_shift_detected | certification_verdict | final_score | benchmark_score | repeated_strategy_count | loop_risk_proxy | mood_min | mood_recovery_delta | workspace_bias_present | micro_coupling_applied | reflection_directive_present |
|---|---:|---|---|---:|---|---|---:|---|---:|---|---:|---:|---|---|---|
| `seq_01_oop_to_asyncio` | 1 | `ARM_OFF` | `False` | `2` | `True` | `FAILED` | `3.5` | `UNAVAILABLE` | `1` | `4` | `-0.65` | `0.65` | `True` | `False` | `False` |
| `seq_01_oop_to_asyncio` | 1 | `ARM_ON` | `False` | `2` | `True` | `FAILED` | `3.5` | `UNAVAILABLE` | `1` | `4` | `-0.595` | `0.595` | `True` | `True` | `True` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_OFF` | `False` | `2` | `True` | `FAILED` | `3.5` | `UNAVAILABLE` | `1` | `4` | `-0.65` | `0.65` | `True` | `False` | `False` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_ON` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.595` | `0.595` | `True` | `True` | `True` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_OFF` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.65` | `0.65` | `True` | `False` | `False` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_ON` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.595` | `0.595` | `True` | `True` | `True` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_OFF` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.65` | `0.65` | `True` | `False` | `False` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_ON` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.348` | `0.348` | `True` | `True` | `True` |

## Aggregate ARM_OFF vs ARM_ON

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `n` | `4` | `4` |
| `recovery_success_rate` | `0` | `0` |
| `certification_rank_mean` | `0` | `0` |
| `final_score_mean` | `3.625` | `3.688` |
| `benchmark_score_mean` | `UNAVAILABLE` | `UNAVAILABLE` |
| `retries_count_mean` | `2` | `2` |
| `loop_risk_proxy_mean` | `4` | `4` |
| `repeated_strategy_count_mean` | `1` | `1` |
| `strategy_shift_rate` | `1` | `1` |
| `mood_min_mean` | `-0.65` | `-0.5333` |
| `mood_recovery_delta_mean` | `0.65` | `0.5333` |
| `workspace_bias_present_rate` | `1` | `1` |
| `tensions_trace_count_total` | `0` | `16` |
| `reflection_trigger_count_total` | `16` | `16` |
| `reflection_directive_present_rate` | `0` | `1` |
| `reflection_directive_count_total` | `0` | `14` |
| `strategy_shift_directive_present_rate` | `0` | `1` |
| `micro_coupling_applied_rate` | `0` | `1` |
| `micro_coupling_applied_count_total` | `0` | `14` |
| `repeated_failure_detected_rate` | `1` | `1` |
| `fallback_count` | `4` | `0` |
| `real_signal_count` | `0` | `4` |

## Aggregate By Sequence

| sequence | arm | final_score_mean | retries_count_mean | loop_risk_proxy_mean | mood_min_mean | mood_recovery_delta_mean | real_signal_count |
|---|---|---:|---:|---:|---:|---:|---:|
| `seq_01_oop_to_asyncio` | `ARM_OFF` | `3.5` | `2` | `4` | `-0.65` | `0.65` | `0` |
| `seq_01_oop_to_asyncio` | `ARM_ON` | `3.625` | `2` | `4` | `-0.595` | `0.595` | `2` |
| `seq_02_sql_to_error_handling` | `ARM_OFF` | `3.75` | `2` | `4` | `-0.65` | `0.65` | `0` |
| `seq_02_sql_to_error_handling` | `ARM_ON` | `3.75` | `2` | `4` | `-0.4715` | `0.4715` | `2` |

## Missing / Unavailable Metrics

- Primary metrics: ['recovery_success', 'certification_verdict', 'final_score', 'benchmark_score', 'retries_count', 'loop_risk_proxy', 'repeated_strategy_count']
- Secondary metrics: ['mood_min', 'mood_recovery_delta', 'workspace_bias_present', 'strategy_shift_detected', 'fallback_provenance', 'tensions_trace_count', 'reflection_trigger_count', 'reflection_directive_present', 'micro_coupling_applied']
- Missing/limited comparisons: `['higher_benchmark_score']`
- `benchmark_score` is `UNAVAILABLE` in aggregate because no reliable benchmark score was parsed.

## Behavioral Comparison

- Primary advantages: `['higher_final_score']`
- Primary regressions: `[]`
- Secondary advantages: `['less_severe_mood_min', 'higher_reflection_directive_rate', 'higher_micro_coupling_applied_rate']`
- Secondary regressions: `['better_mood_recovery_delta']`
- Sequence primary-positive count: `1`
- Sequence secondary-positive count: `2`
- ARM_OFF fallback bias is excluded from GWT signal when classified as synthetic ignition-failure fallback.
- ARM_ON workspace_bias is interpreted as signal/provenance, not as performance.

## Risk / Limitation

- N is still small: 2 sequences x 2 reps.
- LLM stochasticity can dominate small aggregate differences.
- Several metrics remain log-derived proxies.
- Stress injection is controlled but artificial.
- Certification/final score may be too coarse for subtle strategy changes.
- D2.2D is not D2.2 full and cannot support a general performance claim.

## Disciplined Claim Boundary

Allowed if supported:

```text
Under a controlled micro-coupling protocol, calibrated GWT/Mood signal influences a specific decision-adjacent behavior such as reflection or strategy-shift prompting.
```

Forbidden:

```text
GWT improves SHARD performance.
```