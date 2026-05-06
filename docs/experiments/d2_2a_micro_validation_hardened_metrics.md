# D2.2A Micro Validation With Hardened Metrics

D2.2B instrumentation commit: `f67bf13822d99ca974216c27737ff42e95d79709`

This report reruns the D2.2A micro protocol after D2.2B metric hardening.
It uses the same 2 sequences x 2 reps x 2 arms protocol, with no D2.2 full
run and no behavior/scoring/stress/topic-handling changes.

Allowed claim if positive:

```text
Under the hardened D2.2B instrumentation, calibrated GWT/Mood coupling shows repeatable observer-cycle signal and measurable behavioral differences under the D2.2A micro protocol.
```

Forbidden claim:

```text
GWT improves SHARD performance.
```

## Structured Metric Availability

The new run manifests include D2.2B structured fields:

- `behavior_metrics`
- `bias_provenance`
- `mood_metrics`
- `signal_metrics`
- `observer_window`
- `metric_hardening`

Analyzer behavior:

- structured `behavior_metrics` are preferred over observer stdout parsing;
- structured `bias_provenance` is preferred over inferred fallback/signal classification;
- structured `mood_metrics` are preferred over recomputing mood trajectories;
- structured `signal_metrics` are preferred over GWT trace parsing;
- log fallback remains available only when structured fields are absent.

## Comparison To Original D2.2A

Original D2.2A (`20260506_120828`) was `PASS_WEAK` with:

- ARM_ON real signal count `4/4`;
- `mood_min_mean`: `-0.65 -> -0.4472`;
- `final_score_mean`: `3.625 -> 3.688`;
- no improvement on recovery/retry/cert/loop-risk;
- `benchmark_score` `UNAVAILABLE`.

This hardened rerun is also `PASS_WEAK`, but the primary metric signal is weaker:

- ARM_ON real signal count remains `4/4`;
- `mood_min_mean`: `-0.65 -> -0.5333`;
- `final_score_mean`: `3.75 -> 3.625`;
- recovery/retry/cert/loop-risk remain unchanged;
- `benchmark_score` remains `UNAVAILABLE`.

Interpretation: D2.2B structured instrumentation confirms repeatable observer-cycle signal and a secondary mood effect, but does not establish full operational value.

---

# Analyzer Output

Planning commit: `4be493d8b8764a49e7f8f01aad56d1ac7c144920`
Run root: `shard_workspace/d2_2a_runs/20260506_132536`
Expected subprocesses: `8`
Actual subprocesses: `8`
Aborted: `False`

## Experimental Question

Does calibrated GWT/Mood coupling produce repeatable operational value across multiple topic sequences/runs, beyond the weak `mood_min` effect observed in D2.1E?

## Protocol

- Same cached-source harness lineage as D2.1A/D2.1E.
- Zero live DDGS/Brave/Playwright calls expected during benchmark subprocesses.
- Subprocess isolation.
- ARM_OFF vs ARM_ON.
- Controlled stress injection.
- 2 topic sequences x 2 replicas x 2 arms = 8 subprocesses.
- D2.2A micro validation only, not D2.2 full.

Topic sequences:
- `seq_01_oop_to_asyncio`: `python OOP design patterns` -> `asyncio advanced patterns`
- `seq_02_sql_to_error_handling`: `sql injection prevention python` -> `python error handling patterns`

**Final verdict: `PASS_WEAK`**

> ARM_ON shows a plausible but insufficient behavioral difference under the micro-validation protocol.

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

| sequence | rep | arm | recovery_success | retries_count | strategy_shift_detected | certification_verdict | final_score | benchmark_score | repeated_strategy_count | loop_risk_proxy | mood_min | mood_recovery_delta | workspace_bias_present |
|---|---:|---|---|---:|---|---|---:|---|---:|---|---:|---:|---|
| `seq_01_oop_to_asyncio` | 1 | `ARM_OFF` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.65` | `0.65` | `True` |
| `seq_01_oop_to_asyncio` | 1 | `ARM_ON` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.595` | `0.595` | `True` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_OFF` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.65` | `0.65` | `True` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_ON` | `False` | `2` | `True` | `FAILED` | `3.5` | `UNAVAILABLE` | `1` | `4` | `-0.595` | `0.595` | `True` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_OFF` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.65` | `0.65` | `True` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_ON` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.595` | `0.595` | `True` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_OFF` | `False` | `2` | `True` | `FAILED` | `3.75` | `UNAVAILABLE` | `1` | `4` | `-0.65` | `0.65` | `True` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_ON` | `False` | `2` | `True` | `FAILED` | `3.5` | `UNAVAILABLE` | `1` | `4` | `-0.348` | `0.348` | `True` |

## Aggregate ARM_OFF vs ARM_ON

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `n` | `4` | `4` |
| `recovery_success_rate` | `0` | `0` |
| `certification_rank_mean` | `0` | `0` |
| `final_score_mean` | `3.75` | `3.625` |
| `benchmark_score_mean` | `UNAVAILABLE` | `UNAVAILABLE` |
| `retries_count_mean` | `2` | `2` |
| `loop_risk_proxy_mean` | `4` | `4` |
| `repeated_strategy_count_mean` | `1` | `1` |
| `strategy_shift_rate` | `1` | `1` |
| `mood_min_mean` | `-0.65` | `-0.5333` |
| `mood_recovery_delta_mean` | `0.65` | `0.5333` |
| `workspace_bias_present_rate` | `1` | `1` |
| `tensions_trace_count_total` | `0` | `16` |
| `fallback_count` | `4` | `0` |
| `real_signal_count` | `0` | `4` |

## Aggregate By Sequence

| sequence | arm | final_score_mean | retries_count_mean | loop_risk_proxy_mean | mood_min_mean | mood_recovery_delta_mean | real_signal_count |
|---|---|---:|---:|---:|---:|---:|---:|
| `seq_01_oop_to_asyncio` | `ARM_OFF` | `3.75` | `2` | `4` | `-0.65` | `0.65` | `0` |
| `seq_01_oop_to_asyncio` | `ARM_ON` | `3.625` | `2` | `4` | `-0.595` | `0.595` | `2` |
| `seq_02_sql_to_error_handling` | `ARM_OFF` | `3.75` | `2` | `4` | `-0.65` | `0.65` | `0` |
| `seq_02_sql_to_error_handling` | `ARM_ON` | `3.625` | `2` | `4` | `-0.4715` | `0.4715` | `2` |

## Missing / Unavailable Metrics

- Primary metrics: ['recovery_success', 'certification_verdict', 'final_score', 'benchmark_score', 'retries_count', 'loop_risk_proxy', 'repeated_strategy_count']
- Secondary metrics: ['mood_min', 'mood_recovery_delta', 'workspace_bias_present', 'strategy_shift_detected', 'fallback_provenance', 'tensions_trace_count']
- Missing/limited comparisons: `['higher_benchmark_score']`
- `benchmark_score` is `UNAVAILABLE` in aggregate because no reliable benchmark score was parsed.

## Behavioral Comparison

- Primary advantages: `[]`
- Primary regressions: `['higher_final_score']`
- Secondary advantages: `['less_severe_mood_min']`
- Secondary regressions: `['better_mood_recovery_delta']`
- Sequence primary-positive count: `0`
- Sequence secondary-positive count: `2`
- ARM_OFF fallback bias is excluded from GWT signal when classified as synthetic ignition-failure fallback.
- ARM_ON workspace_bias is interpreted as signal/provenance, not as performance.

## Risk / Limitation

- N is still small: 2 sequences x 2 reps.
- LLM stochasticity can dominate small aggregate differences.
- Several metrics remain log-derived proxies.
- Stress injection is controlled but artificial.
- Certification/final score may be too coarse for subtle strategy changes.
- D2.2A is not D2.2 full and cannot support a general performance claim.

## Disciplined Claim Boundary

Allowed if supported:

```text
Under a controlled multi-sequence protocol, calibrated GWT/Mood coupling shows repeatable behavioral differences in observer cycles.
```

Forbidden:

```text
GWT improves SHARD performance.
```
