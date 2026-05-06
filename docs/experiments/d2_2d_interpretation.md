# D2.2D Interpretation Checkpoint

## Status

Interpretation checkpoint only.
No code changes.
No benchmark run.
No operational performance claim.

## Reference

D2.2D commit: `014604dbfd22a62cdb57481398892e6a08ce4f61`

Run directory: `shard_workspace/d2_2d_runs/20260506_152450`

Run artifacts are ignored and were not committed.

## Verdict

`PASS_WEAK`

D2.2D confirms that the calibrated GWT/Mood signal can activate a reflection/strategy-shift directive in a decision-adjacent retry path. It does not yet show full operational value.

## Micro-Fix Applied

Modified file/function:

- `backend/study_phases.py::_retry_gap_fill`

Effective behavior:

- When ARM_ON has a real `tensions` signal, stressed mood, and repeated failure, SHARD adds a reflection/strategy-shift directive to the next retry prompt.
- The directive is a modifier, not an override.

Guardrails held:

- `MAX_RETRY` unchanged.
- Certification thresholds unchanged.
- Scoring logic unchanged.
- `_WINNER_BIAS` unchanged in D2.2D.
- `ValenceField` unchanged.
- Stress injection unchanged.
- Topic sequence/topic handling unchanged.

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

## Raw Observer Workspace Bias

ARM_OFF observer workspace_bias:

- seq1 rep1: `[0.0, -0.15, 0.0]`
- seq1 rep2: `[0.0, -0.15, 0.0]`
- seq2 rep1: `[0.0, -0.15, 0.0]`
- seq2 rep2: `[0.0, -0.15, 0.0]`

ARM_ON observer workspace_bias:

- seq1 rep1: `[0.0, -0.095, 0.0]`
- seq1 rep2: `[0.0, -0.095, 0.0]`
- seq2 rep1: `[0.0, -0.095, 0.0]`
- seq2 rep2: `[0.0, 0.152, 0.0]`

ARM_OFF `-0.15` is classified as synthetic ignition-failure fallback and excluded from GWT signal.

## Aggregate Metrics

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `real_signal_count` | `0` | `4` |
| `micro_coupling_applied_rate` | `0` | `1` |
| `reflection_directive_present_rate` | `0` | `1` |
| `final_score_mean` | `3.625` | `3.688` |
| `mood_min_mean` | `-0.65` | `-0.5333` |
| `retries_count_mean` | `2` | `2` |
| `loop_risk_proxy_mean` | `4` | `4` |
| `repeated_strategy_count_mean` | `1` | `1` |
| `recovery_success_rate` | `0` | `0` |
| `benchmark_score_mean` | `UNAVAILABLE` | `UNAVAILABLE` |

## What Improved

- `real_signal_count`: ARM_ON observed real GWT/Mood signal in `4/4` runs.
- `micro_coupling_applied_rate`: ARM_ON applied the D2.2D micro-coupling in `4/4` runs.
- `reflection_directive_present_rate`: ARM_ON received the reflection/strategy-shift directive in `4/4` runs.
- `final_score_mean`: small increase from `3.625` to `3.688`.
- `mood_min_mean`: less severe minimum mood from `-0.65` to `-0.5333`.

## What Did Not Improve

- `retries_count_mean` stayed `2 -> 2`.
- `loop_risk_proxy_mean` stayed `4 -> 4`.
- `repeated_strategy_count_mean` stayed `1 -> 1`.
- `recovery_success_rate` stayed `0 -> 0`.
- `benchmark_score_mean` remains `UNAVAILABLE`.

## Interpretation

D2.2D confirms decision-adjacent coupling, but hard operational metrics remain unchanged.

The calibrated GWT/Mood signal reaches a retry/reflection directive path and is no longer confined to internal mood/context state. However, the current directive does not yet produce measurable changes in retry count, loop-risk proxy, repeated strategy count, or recovery success.

The most disciplined interpretation is:

```text
decision-adjacent coupling confirmed, but hard operational metrics remain unchanged
```

This supports a narrow mechanism claim, not an operational performance claim.

## Forbidden Claim

```text
GWT improves SHARD performance.
```
