# D2.2E Decision Effect Measurement Report

Planning commit: `b5e87815136c9452e26278e3a51c1c899776c73a`
Run root: `shard_workspace/d2_2e_runs/20260506_171020`
Expected subprocesses: `8`
Actual subprocesses: `8`
Aborted: `False`

## Experimental Question

Does the existing D2.2D reflection micro-coupling already produce measurable retry-strategy divergence, before strengthening the directive?

## Option Implemented

- Planning choice: Option B - Better Retry Quality Metrics First.
- The D2.2D reflection directive was not strengthened.
- The D2.2D micro-coupling behavior is kept unchanged.
- Added measurement: log-derived retry strategy proxy hashes from observer-cycle `Focus` and `gaps` retry lines.

Behavior/scoring guardrails:
- `MAX_RETRY` unchanged.
- Certification threshold unchanged.
- Scoring logic unchanged.
- `_WINNER_BIAS` unchanged in D2.2E.
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
- D2.2E decision effect measurement only, not D2.2 full.

Topic sequences:
- `seq_01_oop_to_asyncio`: `python OOP design patterns` -> `asyncio advanced patterns`
- `seq_02_sql_to_error_handling`: `sql injection prevention python` -> `python error handling patterns`

**Final verdict: `FAIL`**

> ARM_ON signal and micro-coupling are present, but strategy hashes show no ARM_ON divergence and hard metrics remain unchanged.

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

| sequence | rep | arm | recovery_success | retries_count | certification_verdict | final_score | repeated_strategy_count | loop_risk_proxy | retry_hash_available | retry_strategy_hash_changed | material_strategy_shift | repeated_strategy_count_by_hash | micro_coupling_applied | reflection_directive_present |
|---|---:|---|---|---:|---|---:|---:|---:|---|---|---|---:|---|---|
| `seq_01_oop_to_asyncio` | 1 | `ARM_OFF` | `False` | `2` | `FAILED` | `3.75` | `1` | `4` | `True` | `True` | `True` | `0` | `False` | `False` |
| `seq_01_oop_to_asyncio` | 1 | `ARM_ON` | `False` | `2` | `FAILED` | `3.5` | `1` | `4` | `True` | `True` | `True` | `0` | `True` | `True` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_OFF` | `False` | `2` | `FAILED` | `3.5` | `1` | `4` | `True` | `True` | `True` | `0` | `False` | `False` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_ON` | `False` | `2` | `FAILED` | `3.5` | `1` | `4` | `True` | `True` | `True` | `0` | `True` | `True` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_OFF` | `False` | `2` | `FAILED` | `2.75` | `1` | `4` | `True` | `True` | `True` | `0` | `False` | `False` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_ON` | `False` | `2` | `FAILED` | `3.75` | `1` | `4` | `True` | `True` | `True` | `0` | `True` | `True` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_OFF` | `False` | `2` | `FAILED` | `3.75` | `1` | `4` | `True` | `True` | `True` | `0` | `False` | `False` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_ON` | `False` | `2` | `FAILED` | `3.75` | `1` | `4` | `True` | `True` | `True` | `0` | `True` | `True` |

## Retry Strategy Hash Metrics

| sequence | rep | arm | retry_hash_method | retry_hashes | retry_strategy_hash_changed | material_strategy_shift | repeated_strategy_count_by_hash | limitations |
|---|---:|---|---|---|---|---|---:|---|
| `seq_01_oop_to_asyncio` | 1 | `ARM_OFF` | `log_focus_gap_proxy_sha256_12` | `['6c2913a9f1b9', '6ac3e181993a']` | `True` | `True` | `0` | `hashes are derived from retry Focus/gaps log lines, not full semantic retry plans; hash changes indicate proxy text changes, not guaranteed semantic strategy shifts; prior_strategy_named is unavailable because full retry prompt text is not logged` |
| `seq_01_oop_to_asyncio` | 1 | `ARM_ON` | `log_focus_gap_proxy_sha256_12` | `['1f90b6379ddb', 'a9f7f6fc1ce8']` | `True` | `True` | `0` | `hashes are derived from retry Focus/gaps log lines, not full semantic retry plans; hash changes indicate proxy text changes, not guaranteed semantic strategy shifts; prior_strategy_named is unavailable because full retry prompt text is not logged` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_OFF` | `log_focus_gap_proxy_sha256_12` | `['5c7e10c9d3d2', 'dcc57abbf55c']` | `True` | `True` | `0` | `hashes are derived from retry Focus/gaps log lines, not full semantic retry plans; hash changes indicate proxy text changes, not guaranteed semantic strategy shifts; prior_strategy_named is unavailable because full retry prompt text is not logged` |
| `seq_01_oop_to_asyncio` | 2 | `ARM_ON` | `log_focus_gap_proxy_sha256_12` | `['2218e228310e', '6603df3355f9']` | `True` | `True` | `0` | `hashes are derived from retry Focus/gaps log lines, not full semantic retry plans; hash changes indicate proxy text changes, not guaranteed semantic strategy shifts; prior_strategy_named is unavailable because full retry prompt text is not logged` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_OFF` | `log_focus_gap_proxy_sha256_12` | `['ea791d4e9c0e', '635424400a0b']` | `True` | `True` | `0` | `hashes are derived from retry Focus/gaps log lines, not full semantic retry plans; hash changes indicate proxy text changes, not guaranteed semantic strategy shifts; prior_strategy_named is unavailable because full retry prompt text is not logged` |
| `seq_02_sql_to_error_handling` | 1 | `ARM_ON` | `log_focus_gap_proxy_sha256_12` | `['fdb89a203f2c', '482cc5710da4']` | `True` | `True` | `0` | `hashes are derived from retry Focus/gaps log lines, not full semantic retry plans; hash changes indicate proxy text changes, not guaranteed semantic strategy shifts; prior_strategy_named is unavailable because full retry prompt text is not logged` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_OFF` | `log_focus_gap_proxy_sha256_12` | `['ad8855c9f354', '305ba52d1c5b']` | `True` | `True` | `0` | `hashes are derived from retry Focus/gaps log lines, not full semantic retry plans; hash changes indicate proxy text changes, not guaranteed semantic strategy shifts; prior_strategy_named is unavailable because full retry prompt text is not logged` |
| `seq_02_sql_to_error_handling` | 2 | `ARM_ON` | `log_focus_gap_proxy_sha256_12` | `['a05876bb4f9f', '48c15777b2c2']` | `True` | `True` | `0` | `hashes are derived from retry Focus/gaps log lines, not full semantic retry plans; hash changes indicate proxy text changes, not guaranteed semantic strategy shifts; prior_strategy_named is unavailable because full retry prompt text is not logged` |

## Aggregate ARM_OFF vs ARM_ON

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `n` | `4` | `4` |
| `recovery_success_rate` | `0` | `0` |
| `certification_rank_mean` | `0` | `0` |
| `final_score_mean` | `3.438` | `3.625` |
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
| `retry_hash_available_rate` | `1` | `1` |
| `retry_strategy_hash_changed_rate` | `1` | `1` |
| `prior_strategy_named_rate` | `UNAVAILABLE` | `UNAVAILABLE` |
| `material_strategy_shift_rate` | `1` | `1` |
| `repeated_strategy_count_by_hash_mean` | `0` | `0` |
| `fallback_count` | `4` | `0` |
| `real_signal_count` | `0` | `4` |

## Aggregate By Sequence

| sequence | arm | final_score_mean | retry_strategy_hash_changed_rate | material_strategy_shift_rate | repeated_strategy_count_by_hash_mean | mood_min_mean | real_signal_count |
|---|---|---:|---:|---:|---:|---:|---:|
| `seq_01_oop_to_asyncio` | `ARM_OFF` | `3.625` | `1` | `1` | `0` | `-0.65` | `0` |
| `seq_01_oop_to_asyncio` | `ARM_ON` | `3.5` | `1` | `1` | `0` | `-0.595` | `2` |
| `seq_02_sql_to_error_handling` | `ARM_OFF` | `3.25` | `1` | `1` | `0` | `-0.65` | `0` |
| `seq_02_sql_to_error_handling` | `ARM_ON` | `3.75` | `1` | `1` | `0` | `-0.4715` | `2` |

## Missing / Unavailable Metrics

- Primary metrics: ['retry_strategy_hash_changed', 'prior_strategy_named', 'material_strategy_shift', 'repeated_strategy_count_by_hash', 'final_score', 'certification_verdict', 'recovery_success']
- Secondary metrics: ['reflection_directive_present', 'micro_coupling_applied', 'workspace_bias_present', 'tensions_trace_count', 'mood_min', 'mood_recovery_delta', 'loop_risk_proxy', 'retries_count']
- Missing/limited comparisons: `['higher_benchmark_score', 'higher_prior_strategy_named_rate']`
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

## Retry Strategy Hash Method

- Method: `log_focus_gap_proxy_sha256_12`.
- Source: observer-cycle retry `Focus` and `gaps` log lines.
- `retry_strategy_hash_changed` compares adjacent retry proxy hashes within the observer cycle.
- `material_strategy_shift` is a conservative proxy equal to observed hash divergence.
- `prior_strategy_named` remains `UNAVAILABLE` unless full retry prompt text is logged.

## Risk / Limitation

- N is still small: 2 sequences x 2 reps.
- LLM stochasticity can dominate small aggregate differences.
- Several metrics remain log-derived proxies.
- Stress injection is controlled but artificial.
- Certification/final score may be too coarse for subtle strategy changes.
- Retry strategy hashes are log-derived from observer retry `Focus` and `gaps`, not full semantic plans.
- Hash changes indicate proxy text changes, not guaranteed semantic strategy shifts.
- `prior_strategy_named` is `UNAVAILABLE` unless full retry prompt text is logged.
- D2.2E is not D2.2 full and cannot support a general performance claim.

## Next Step

- If retry hashes show no ARM_ON divergence, consider D2.2F with a pre-registered stronger reflection directive.
- If retry hashes show ARM_ON divergence, consider D2.3 or D2.2 full only after improving outcome-level metrics.

## Disciplined Claim Boundary

Allowed if supported:

```text
Under the D2.2D micro-coupling, ARM_ON shows structured evidence of retry-strategy divergence in the observer cycle.
```

Forbidden:

```text
GWT improves SHARD performance.
```