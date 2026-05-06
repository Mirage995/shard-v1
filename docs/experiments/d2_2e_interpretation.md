# D2.2E Interpretation Checkpoint

## Status

Interpretation checkpoint only.
No code changes.
No benchmark run.
No operational performance claim.

## Reference

D2.2E commit: `6b407f41015380750561c7c25904a893a79de0c6`

Run directory: `shard_workspace/d2_2e_runs/20260506_171020`

Run artifacts are ignored and were not committed.

## Verdict

`FAIL`

D2.2E shows that the D2.2D reflection directive is applied, but current retry-quality measurements do not show ARM_ON-specific strategy divergence.

## Harness Sanity

- Expected subprocesses: `8`
- Actual subprocesses: `8`
- Subprocess exits: `8/8` successful
- Live DDGS calls: `0`
- Live Brave calls: `0`
- Live Playwright calls: `0`
- MAP cache hits: present for both cycles
- AGGREGATE cache hits: present for both cycles
- Stress injection observed: yes
- Topic sequence observed: yes
- Mood samples present: yes
- Contamination flags: none

## Signal And Micro-Coupling

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `real_signal_count` | `0` | `4` |
| `micro_coupling_applied_rate` | `0` | `1` |
| `reflection_directive_present_rate` | `0` | `1` |
| `workspace_bias_present_rate` | `1` | `1` |
| `tensions_trace_count_total` | `0` | `16` |

ARM_OFF workspace bias is classified as synthetic ignition-failure fallback and excluded from GWT signal.

## Retry Strategy Hash Metrics

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `retry_hash_available_rate` | `1` | `1` |
| `retry_strategy_hash_changed_rate` | `1` | `1` |
| `material_strategy_shift_rate` | `1` | `1` |
| `repeated_strategy_count_by_hash_mean` | `0` | `0` |
| `prior_strategy_named_rate` | `UNAVAILABLE` | `UNAVAILABLE` |

The retry hash metrics do not separate ARM_ON from ARM_OFF. Both arms show hash changes in the observer cycle, so the current D2.2D directive does not produce a measurable ARM_ON-specific retry-strategy divergence under this proxy.

## Hard Outcomes

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `final_score_mean` | `3.438` | `3.625` |
| `recovery_success_rate` | `0` | `0` |
| `retries_count_mean` | `2` | `2` |
| `loop_risk_proxy_mean` | `4` | `4` |
| `benchmark_score_mean` | `UNAVAILABLE` | `UNAVAILABLE` |

The small `final_score_mean` increase is not enough to support an operational value claim because recovery, retry count, loop-risk, and benchmark score remain unchanged or unavailable.

## Hash Measurement Limitation

D2.2E retry hashes are log-derived from observer-cycle `Focus` and `gaps` retry lines.

Limitations:

- They are not hashes of full semantic retry plans.
- They can detect proxy text changes, not guaranteed strategy changes.
- They cannot confirm whether the prior failed strategy was explicitly named.
- `prior_strategy_named_rate` remains `UNAVAILABLE`.
- The measurement may miss semantic shifts or over-count superficial focus/gap changes.

## Interpretation

```text
D2.2D directive is applied, but current retry-quality measurements do not show ARM_ON-specific strategy divergence.
```

The disciplined conclusion is that D2.2D successfully routes calibrated GWT/Mood signal into a reflection directive, but the directive is not yet strong enough, or not measured deeply enough, to distinguish ARM_ON retry behavior from ARM_OFF behavior.

## Forbidden Claim

```text
GWT improves SHARD performance.
```
