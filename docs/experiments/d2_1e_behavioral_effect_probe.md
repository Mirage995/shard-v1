# D2.1E Behavioral Effect Probe

## Verdict

`PASS_WEAK`

D2.1E is a small behavioral probe, not D2.2. It tests whether the calibrated GWT/Mood signal from D2.1D is associated with observable behavior in the observer cycle.

The result is weak and mixed:

- ARM_ON had real workspace signal in the observer cycle.
- ARM_ON had a less severe observer-cycle `mood_min` than ARM_OFF.
- ARM_ON did not improve retries, certification verdict, final score, repeated strategy count, or loop-risk proxy.
- ARM_ON had a slightly worse `mood_recovery_delta`.

This does not support a general performance claim.

## Experimental Question

Now that the GWT/Mood bias propagates into the next cycle, does ARM_ON change behavior relative to ARM_OFF in recovery, retry strategy, loop escape, mood recovery, certification, or final score?

## Pre-Registered Hypothesis

ARM_ON, with calibrated `tensions` bias, should show at least one observable behavioral difference relative to ARM_OFF:

- faster recovery after forced failure
- fewer useless retries
- clearer strategy shift after forced failure
- equal or better certification verdict
- equal or better final score if score is available
- more orderly mood recovery after stress

## Protocol

Run root inspected:

```text
shard_workspace/d2_1e_runs/20260506_002708
```

Harness:

- cached MAP/AGGREGATE sources
- zero live DDGS calls
- zero live Brave calls
- zero live Playwright calls
- subprocess isolation per arm
- same sequential two-topic protocol as D2.1D
- controlled stress injection

Topic sequence:

```text
cycle 1: python OOP design patterns
role: stress inducer

cycle 2: asyncio advanced patterns
role: behavioral observer
```

Arms:

```text
ARM_OFF: no_l3=True
ARM_ON:  no_l3=False
```

## Harness Sanity

| Check | Result |
|---|---|
| All subprocess exit_code == 0 | PASS |
| Zero live DDGS/Brave/Playwright | PASS |
| Cached MAP/AGG hooks fired >= 2x per arm | PASS |
| No contamination flag | PASS |
| Stress injection observed | PASS |
| Force-topic-sequence observed >= 2x | PASS |
| Mood samples present | PASS |
| Fallback threshold not breached | PASS |

Run summary:

| Arm | Exit | cache_hit_map | cache_hit_aggregate | stress observed | sequence observed | contaminated |
|---|---:|---:|---:|---|---|---|
| ARM_OFF | 0 | 2 | 2 | true | true | false |
| ARM_ON | 0 | 2 | 2 | true | true | false |

## Raw Traces

ARM_OFF:

```text
mood:
[-0.465, -0.465, 0.035, -0.615, 0.035]

workspace_bias:
[0.0, 0.0, 0.0, -0.15, 0.0]

observer mood:
[0.035, -0.615, 0.035]

observer workspace_bias:
[0.0, -0.15, 0.0]
```

ARM_ON:

```text
mood:
[-0.465, -0.465, 0.035, -0.56, 0.035]

workspace_bias:
[0.0, 0.0, 0.0, -0.095, 0.0]

observer mood:
[0.035, -0.56, 0.035]

observer workspace_bias:
[0.0, -0.095, 0.0]
```

Signal provenance:

| Arm | Observer workspace_bias present | tensions traces | classification |
|---|---|---:|---|
| ARM_OFF | true | 0 | fallback artifact, excluded from GWT signal |
| ARM_ON | true | 4 | compatible with real workspace-winner signal |

## Behavioral Metrics

| Metric | ARM_OFF | ARM_ON | Interpretation |
|---|---:|---:|---|
| `recovery_success` | false | false | no recovery advantage |
| `retries_count` | 2 | 2 | equal |
| `strategy_shift_detected` | true | true | equal, not discriminative |
| `certification_verdict` | FAILED | FAILED | equal |
| `final_score` | 3.75 | 3.75 | equal |
| `benchmark_score` | UNAVAILABLE | UNAVAILABLE | unavailable because benchmark tests did not yield a usable score |
| `repeated_strategy_count` | 1 | 1 | equal |
| `loop_risk_proxy` | 4 | 4 | equal |
| `mood_min` | -0.615 | -0.56 | ARM_ON less severe |
| `mood_recovery_delta` | 0.65 | 0.595 | ARM_ON slightly worse |
| `workspace_bias_present` | true | true | ARM_OFF is fallback artifact; ARM_ON is GWT-compatible signal |

Unavailable / limited metrics:

- `benchmark_score`: UNAVAILABLE in both arms.
- `strategy_shift_detected`: available as a coarse log proxy only; both arms triggered it, so it does not discriminate.
- provenance is log-derived, not yet structured as `winner_module`, `ignition_failed`, `valence_delta`, and `arousal_delta`.

## Behavioral Comparison

Advantages:

```text
ARM_ON less_severe_mood_min
```

Regressions:

```text
ARM_ON lower mood_recovery_delta
```

No observed change:

```text
retries_count
certification_verdict
final_score
repeated_strategy_count
loop_risk_proxy
```

## Interpretation

D2.1E provides weak evidence of a behavioral difference in the observer cycle, limited to mood severity:

```text
ARM_ON observer mood_min = -0.56
ARM_OFF observer mood_min = -0.615
```

However, the operational metrics did not improve:

```text
retries_count: equal
certification_verdict: equal FAILED
final_score: equal 3.75
loop_risk_proxy: equal 4
```

Therefore the disciplined interpretation is:

```text
Under this controlled sequential protocol, calibrated GWT/Mood coupling is associated with a small mood-severity difference in the observer cycle, but not with demonstrated recovery, certification, score, or loop-escape improvement.
```

## Signal vs Performance

D2.1D validated internal signal propagation.

D2.1E probes behavioral effect. It does not convert signal propagation into a performance claim.

Not allowed:

```text
GWT improves SHARD performance.
```

## Next Step

Before any D2.2-scale validation, the harness should improve provenance and behavioral observability:

- structured `winner_module`
- structured `ignition_failed`
- structured bias source (`real_workspace_winner` vs `synthetic_ignition_failure_fallback`)
- applied `valence_delta`
- applied `arousal_delta`
- structured Topic 2 final score/certification fields
- structured retry reason and strategy-shift markers

Recommended next step:

```text
D2.1F or D2.2-prep: add structured provenance and behavioral fields before scaling to repeated runs.
```
