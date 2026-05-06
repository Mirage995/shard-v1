# D3.0A Learning Curve Probe

## Status

Run analyzed.

Planning commit: `326cc7f`

Cache prefetch note: `docs/experiments/d3_0a_cache_prefetch.md`

Run directory: `shard_workspace/d3_0a_runs/20260506_232248`

## Experimental Question

Does calibrated GWT/Mood coupling improve SHARD's learning curve across repeated sessions, rather than immediate single-run performance?

## Protocol

- Topic family: Python async / error handling / retry/backoff patterns
- Arms: ARM_OFF vs ARM_ON
- Sessions per arm: 5
- Memory/strategy persistence: enabled within each arm
- Arm isolation: `shard_memory_snapshot_restore_between_arms`
- Source mode: cached sources only

## Harness Sanity

- Expected sessions: 10
- Actual sessions: 10
- Contaminated sessions: 0
- Abort reasons: []
- Live DDGS/Brave/Playwright during benchmark: 0
- Arm leakage control: baseline `shard_memory` snapshot restored before each arm; original memory restored after the run.

## Session Metrics

| Arm | Session | Topic | Final score | Cert | Recovery | Retries | Loop risk | Memory recall | Strategy updates | Mood min | Workspace bias |
| --- | ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| ARM_OFF | 1 | python error handling patterns | 3.5 | FAILED | False | 2 | 4 | 88 | 21 | -0.5 | False |
| ARM_OFF | 2 | async retry/backoff patterns | 3.75 | FAILED | False | 2 | 4 | 88 | 21 | -0.5 | False |
| ARM_OFF | 3 | asyncio advanced patterns | 3.5 | FAILED | False | 2 | 4 | 88 | 21 | -0.5 | False |
| ARM_OFF | 4 | python OOP design patterns | 3.5 | FAILED | False | 2 | 4 | 88 | 21 | -0.5 | False |
| ARM_OFF | 5 | resilient python service design | 3.25 | FAILED | False | 2 | 4 | 88 | 21 | -0.5 | False |
| ARM_ON | 1 | python error handling patterns | 3.75 | FAILED | False | 2 | 5 | 92 | 21 | -0.5 | False |
| ARM_ON | 2 | async retry/backoff patterns | 3.75 | FAILED | False | 2 | 4 | 92 | 21 | -0.5 | False |
| ARM_ON | 3 | asyncio advanced patterns | 3.75 | FAILED | False | 2 | 4 | 92 | 21 | -0.5 | False |
| ARM_ON | 4 | python OOP design patterns | 3.5 | FAILED | False | 2 | 4 | 92 | 21 | -0.5 | False |
| ARM_ON | 5 | resilient python service design | 2.5 | FAILED | False | 2 | 4 | 92 | 21 | -0.5 | False |

## Aggregate Slopes

| Metric | ARM_OFF | ARM_ON |
| --- | ---: | ---: |
| final_score_slope | -0.075 | -0.275 |
| certification_rank_slope | 0.0 | 0.0 |
| recovery_success_slope | 0.0 | 0.0 |
| retries_count_slope | 0.0 | 0.0 |
| loop_risk_proxy_slope | 0.0 | -0.2 |
| repeated_strategy_count_slope | 0.0 | -0.2 |
| mood_min_slope | 0.0 | 0.0 |
| memory_recall_count_slope | 0.0 | 0.0 |
| strategy_update_count_slope | 0.0 | 0.0 |
| strategy_reuse_count_slope | 0.1 | 0.1 |

## Slope Comparison

```json
{
  "final_score_slope_delta": -0.2,
  "certification_rank_slope_delta": 0.0,
  "recovery_success_slope_delta": 0.0,
  "retries_count_slope_delta_lower_is_better": 0.0,
  "loop_risk_proxy_slope_delta_lower_is_better": 0.2,
  "repeated_strategy_slope_delta_lower_is_better": 0.2,
  "mood_min_slope_delta": 0.0,
  "memory_recall_slope_delta": 0.0,
  "strategy_update_slope_delta": 0.0,
  "strategy_reuse_slope_delta": 0.0
}
```

## Memory / Strategy Evidence

- Memory metrics source: log-derived proxy unless structured fields become available.
- ARM_OFF memory_recall_count slope: 0.0
- ARM_ON memory_recall_count slope: 0.0
- ARM_OFF strategy_update_count slope: 0.0
- ARM_ON strategy_update_count slope: 0.0

## Missing / Unavailable Metrics

- benchmark_score
- memory_recall_relevance

## Verdict

PASS_WEAK

Reasons:

- loop_risk_proxy_slope_delta_lower_is_better
- repeated_strategy_slope_delta_lower_is_better
- hard outcome slope regression prevents PASS_STRONG
- memory/strategy evidence does not support PASS_STRONG

## Interpretation

D3.0A tests longitudinal learning behavior, not a single-run performance claim. Any positive result should be interpreted as learning-curve evidence under this controlled probe, not as a general claim that GWT improves SHARD performance.

## Limitations

- D3.0A is more realistic than D2 micro protocols but less causally isolated.
- Memory/strategy metrics are still partly log-derived.
- Filesystem snapshot/restore reduces arm leakage risk but is not a native memory namespace.
- `benchmark_score` remains unavailable unless emitted by the core pipeline.

## Forbidden Claim

GWT improves SHARD performance.

## Next Step

If D3.0A is promising, harden memory/strategy instrumentation before a larger D3 learning-curve validation.
