# D2.1D Tensions-Bias Calibration

## Verdict

`PASS_STRONG`

D2.1D tests whether the previously silent stress-dominant winner can propagate into next-cycle MoodEngine computation once assigned a non-zero coupling bias.

It does not test operational improvement, recovery rate, certification rate, or general performance.

## Pre-Registered Hypothesis

```text
If the dominant stress winner "tensions" receives a non-zero MoodWorkspaceCoupling bias,
then ARM_ON should show non-zero next-cycle workspace_bias under the same D2.1C sequential protocol.
```

## Experimental Patch

File:

```text
backend/cognition/mood_workspace_coupling.py
```

Patch under test:

```python
_WINNER_BIAS["tensions"] = (-0.05, +0.15)
```

Interpretation:

- `valence_delta = -0.05`: frustration/stress signal
- `arousal_delta = +0.15`: urgency/activation signal

These values are experimental calibration hypotheses, not final biological or architectural truths.

## Protocol

Run root inspected:

```text
shard_workspace/d2_1d_runs/20260505_233731
```

The protocol intentionally reuses D2.1C:

```text
cycle 1: python OOP design patterns
cycle 2: asyncio advanced patterns
```

Arms:

```text
ARM_OFF: no_l3=True
ARM_ON:  no_l3=False
```

Stress profile:

```text
controlled_validation_failure
```

## Harness Sanity

From `d2_1d_summary.json` and `backend/d2_1d_analyze.py`:

| Check | ARM_OFF | ARM_ON |
|---|---:|---:|
| subprocess exit code | 0 | 0 |
| DDGS calls | 0 | 0 |
| Brave calls | 0 | 0 |
| Playwright calls | 0 | 0 |
| cache_hit_map | 2 | 2 |
| cache_hit_aggregate | 2 | 2 |
| stress_injection_observed | true | true |
| force_topic_seq_observed | true | true |
| contaminated flag | false | false |
| tensions bid traces | 0 | 4 |

The harness was clean for this run: no live search/browser calls, cache hooks fired for both topics in both arms, subprocesses exited successfully, stress injection was observed, and the forced topic sequence was observed.

## Raw Traces

ARM_OFF:

```text
mood:
[-0.36, -0.36, -0.545, +0.105]

workspace_bias:
[0.00, 0.00, -0.15, 0.00]

cycle-2 workspace_bias window:
[-0.15, 0.00]
```

ARM_ON:

```text
mood:
[-0.43, -0.43, -0.56, +0.035]

workspace_bias:
[0.00, 0.00, -0.095, 0.00]

cycle-2 workspace_bias window:
[-0.095, 0.00]
```

## Provenance Classification

ARM_OFF:

```text
cycle-2 workspace_bias = -0.15
classified as synthetic ignition-failure fallback artifact
excluded from GWT signal
```

Reason: ARM_OFF runs with `no_l3=True`; if no workspace winners are drained, the fallback path calls `on_workspace_result(..., ignition_failed=True)`, which applies `_IGNITION_FAILURE_BIAS = (-0.15, +0.10)`.

ARM_ON:

```text
cycle-2 workspace_bias = -0.095
tensions bid traces = 4
classified as compatible with real workspace-winner bias after calibration
```

Reason: ARM_ON keeps L3/GWT enabled, and parsed logs show `tensions` active in GWT bid traces. With the D2.1D patch, the previously silent stress-dominant winner now contributes non-zero valence bias.

## Interpretation

D2.1D confirms the D2.1C mechanism diagnosis at signal level:

```text
ValenceField boosts "tensions" under stress.
D2.1C mapped "tensions" to zero bias, making the stress winner silent.
D2.1D assigns "tensions" non-zero bias.
ARM_ON then shows non-zero next-cycle workspace_bias.
```

This is a calibration result for internal signal propagation. It does not show that GWT improves SHARD performance.

## Allowed Claim

```text
D2.1D confirms that the previously silent stress-dominant winner can propagate into next-cycle MoodEngine computation once assigned a non-zero coupling bias.
```

## Disallowed Claim

```text
An outcome-level performance claim from GWT activation.
```

That requires a later recovery/cert-rate experiment such as D2.1E or D2.2.

## Next Step

The next experiment should keep bias provenance structured in the harness:

- `winner_module`
- `ignition_failed`
- bias source (`real_workspace_winner` vs `synthetic_ignition_failure_fallback`)
- applied `valence_delta`
- applied `arousal_delta`

Only after provenance is explicit should a later experiment test behavioral outcomes.
