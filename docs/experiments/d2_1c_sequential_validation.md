# D2.1C Sequential Multi-Topic Validation

## Verdict

`INCONCLUSIVE_MECHANISM_DISCONNECTED`

D2.1C did not satisfy the pre-registered PASS condition. The observed pattern was inverted: ARM_OFF showed non-zero cycle-2 `workspace_bias`, while ARM_ON stayed at zero.

The run is not a generic GWT/Mood failure. Log and code inspection show a mechanism-level calibration disconnect: ARM_OFF produced synthetic ignition-failure fallback bias, while ARM_ON reached real workspace competition but the dominant stress winner, `tensions`, maps to zero MoodWorkspaceCoupling bias.

## Pre-Registered Prediction

After Topic 1 generated workspace winners under stress, Topic 2 was expected to observe propagated next-cycle bias:

- ARM_ON cycle-2 `workspace_bias != 0`
- ARM_OFF cycle-2 `workspace_bias ~= 0`
- harness clean
- cache stable
- stress injection observed
- topic sequence observed

## Protocol

Run root inspected:

```text
shard_workspace/d2_1c_runs/20260505_173153
```

Sequential protocol:

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

## Observed Result

The observed pattern was inverted relative to the prediction:

- ARM_OFF showed `workspace_bias = -0.15`
- ARM_ON remained at `workspace_bias = 0.00`

Raw mood traces:

```text
ARM_OFF mood:
[-0.36, -0.36, +0.14, -0.51]

ARM_OFF workspace_bias:
[0.00, 0.00, 0.00, -0.15]

ARM_ON mood:
[-0.36, -0.36, -0.36, +0.14]

ARM_ON workspace_bias:
[0.00, 0.00, 0.00, 0.00]
```

## Harness Sanity

From `d2_1c_summary.json`:

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
| stress_injection_count | 2 | 2 |
| force_topic_seq_count | 4 | 4 |
| retry_attempt_count | 8 | 10 |
| contaminated flag | false | false |
| fallback_count | 5 | 6 |
| http_error_count | 0 | 2 |

Cache hashes matched across arms for both topics:

```text
python OOP design patterns:
sha256:72d7c85843ff74cf96da78dd372b3c9eef9a1cd1a7facd0b652b284f45b666e4

asyncio advanced patterns:
sha256:b03916f343231d9aec396808a698474fd062e5a8a5124e0d778aeca34aeb2969
```

The current analyzer does not classify this run as contaminated: subprocesses exited cleanly, live search/browser calls were zero, cache hooks fired, stress was observed, and the topic sequence was observed. The two ARM_ON HTTP errors should remain visible in the report, but they are not the primary explanation for the inverted `workspace_bias` pattern.

## Mechanism Diagnosis

### ARM_OFF: fallback bias, not real GWT coupling

ARM_OFF did not show true workspace-derived GWT bias.

Relevant flow in `backend/night_runner.py`:

```python
_winners = _core_env.drain_session_winners()

if not _winners:
    _winners = [{"module": _core_env.last_workspace_winner, "ignition_failed": True}]

for w in _winners:
    _mood_coupling.on_workspace_result(
        winner_module=w["module"],
        ignition_failed=w["ignition_failed"],
    )
```

D2.1C ARM_OFF uses `no_l3=True`, so relational context is skipped. With no workspace winners, `drain_session_winners()` returns `[]`, the fallback path marks `ignition_failed=True`, and `MoodWorkspaceCoupling` applies:

```python
_IGNITION_FAILURE_BIAS = (-0.15, +0.10)
```

Therefore:

```text
ARM_OFF workspace_bias -0.15 = synthetic ignition-failure fallback bias.
```

It is not evidence of real GWT winner propagation.

### ARM_ON: real winner, zero bias

ARM_ON did reach the workspace path.

In `arm_on/stdout.log`, `relational_context` fired during retry/stress paths and `tensions` dominated the bid trace:

```text
tensions block=behavior_directive base=0.85 val=1.20 fb=1.00 aff=1.00 -> bid=1.020
tensions block=behavior_directive base=0.85 val=1.20 fb=0.95 aff=1.00 -> bid=0.969
tensions block=behavior_directive base=0.85 val=1.20 fb=0.90 aff=1.00 -> bid=0.921
tensions block=behavior_directive base=0.85 val=1.20 fb=0.86 aff=1.00 -> bid=0.875
```

This is semantically plausible: under stress, `ValenceField` boosts behavior directives and the `tensions` block becomes the dominant workspace winner.

But `backend/cognition/mood_workspace_coupling.py` currently maps that winner to zero:

```python
_WINNER_BIAS = {
    ...
    "tensions": (0.00, 0.00),
    ...
}
```

Therefore:

```text
ARM_ON reaches GWT/MoodWorkspaceCoupling, but the stress-dominant winner is numerically silent.
```

Short form:

```text
The stress-dominant Global Workspace winner is numerically silent in MoodWorkspaceCoupling.
```

## Why This Is Not A Simple FAIL

D2.1C failed the pre-registered PASS condition, so it cannot be treated as a positive result.

However, the run revealed a more specific mechanism-level problem:

1. `workspace_bias != 0` can be produced by synthetic ignition-failure fallback.
2. Real workspace winners can remain invisible when their configured MoodWorkspaceCoupling delta is zero.

That means `workspace_bias` alone is not enough as a GWT signal. Future analyzers need bias provenance:

- `real_workspace_winner`
- `synthetic_ignition_failure_fallback`
- `winner_module`
- `ignition_failed`
- applied `valence_delta`
- applied `arousal_delta`

## Scientific Conclusion

D2.1C is best classified as:

```text
INCONCLUSIVE_MECHANISM_DISCONNECTED
```

It does not falsify GWT/Mood coupling in general. It shows that the intended stress-path signal is currently unobservable because of calibration asymmetry:

```text
ValenceField boosts "tensions" under stress.
MoodWorkspaceCoupling assigns "tensions" zero bias.
```

This makes the ARM_ON signal silent exactly in the regime where it was expected to emerge.

## Next Step: D2.1D

D2.1D should pre-register a single targeted calibration patch and rerun the same sequential protocol.

Candidate hypothesis:

```text
If the dominant stress winner "tensions" receives a non-zero MoodWorkspaceCoupling bias,
then ARM_ON should show non-zero next-cycle workspace_bias under the same D2.1C protocol.
```

Candidate patch for D2.1D only:

```python
_WINNER_BIAS["tensions"] = (-0.05, +0.15)
```

Do not include that patch in D2.1C. Applying it now would be post-hoc tuning.

Allowed claim if D2.1D passes:

```text
D2.1D confirms that the previously silent stress-dominant winner can propagate into next-cycle MoodEngine computation once calibrated with a non-zero coupling bias.
```

Still not allowed:

```text
An outcome-level performance claim from GWT activation.
```

That requires a later outcome-level recovery/cert-rate experiment.
