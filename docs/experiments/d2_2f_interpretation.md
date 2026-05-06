# D2.2F Interpretation Checkpoint

## Status

Interpretation checkpoint only.
No code changes.
No benchmark run.
No operational performance claim.

## Reference

D2.2F commit: `eb3c83d83f7a1091a287901cff38c7ca783d6f0b`

Run directory: `shard_workspace/d2_2f_runs/20260506_180229`

Run artifacts are ignored and were not committed.

## Verdict

`FAIL`

D2.2F shows that the stronger reflection directive is applied in ARM_ON, but it does not create ARM_ON-specific retry strategy divergence or operational improvement.

## Micro-Fix Applied

Modified file/function:

- `backend/study_phases.py::_retry_gap_fill`

Effective behavior:

- When ARM_ON has real `tensions` signal, stressed mood, and repeated failure, SHARD injects a stronger reflection/strategy-shift directive.
- The directive asks the model to identify the prior failed strategy, explain why it failed, and produce a materially different recovery plan.
- The directive remains a prompt modifier, not an override.

Guardrails held:

- `MAX_RETRY` unchanged.
- Certification threshold unchanged.
- Scoring logic unchanged.
- `_WINNER_BIAS` unchanged.
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

## Stronger Directive Metrics

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `real_signal_count` | `0` | `4` |
| `micro_coupling_applied_rate` | `0` | `1` |
| `reflection_directive_present_rate` | `0` | `1` |
| `stronger_directive_present_rate` | `0` | `1` |
| `stronger_directive_count_total` | `0` | `14` |
| `tensions_trace_count_total` | `0` | `16` |

## Retry Strategy Metrics

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `retry_strategy_hash_changed_rate` | `1` | `1` |
| `material_strategy_shift_rate` | `1` | `1` |
| `repeated_strategy_count_by_hash_mean` | `0` | `0` |
| `prior_strategy_named_rate` | `UNAVAILABLE` | `UNAVAILABLE` |

Retry strategy metrics do not separate ARM_ON from ARM_OFF. The stronger directive is observable, but the measured retry proxy changes are not ARM_ON-specific.

## Hard Outcomes

| metric | ARM_OFF | ARM_ON |
|---|---:|---:|
| `final_score_mean` | `3.688` | `3.5` |
| `recovery_success_rate` | `0` | `0` |
| `retries_count_mean` | `2` | `2` |
| `loop_risk_proxy_mean` | `4` | `4` |
| `benchmark_score_mean` | `UNAVAILABLE` | `UNAVAILABLE` |

`final_score_mean` regressed in ARM_ON while recovery, retry count, loop-risk, and benchmark score did not improve.

## Interpretation

```text
stronger prompt-level reflection directive applied, but no ARM_ON-specific retry strategy divergence or operational improvement; final_score_mean regressed.
```

The disciplined conclusion is that the issue is not simply that the D2.2D directive was too weak. Strengthening the prompt-level directive still did not move decision-quality metrics under the current D2.2 micro protocol.

## Conclusion

Prompt-level reflection coupling is insufficient under the current protocol.

The calibrated GWT/Mood signal is repeatable and can reach decision-adjacent prompt construction, but prompt-level nudging does not appear to create robust operational improvements in this benchmark setup.

## Forbidden Claim

```text
GWT improves SHARD performance.
```
