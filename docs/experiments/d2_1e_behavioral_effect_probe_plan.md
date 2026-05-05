# D2.1E Behavioral Effect Probe Plan

## Status

Planning only. No code changes, no benchmark run, and no operational claim.

D2.1D validated internal next-cycle signal propagation after calibrating:

```python
_WINNER_BIAS["tensions"] = (-0.05, +0.15)
```

D2.1E should test whether that internal signal has any observable behavioral effect. It must not assume that signal propagation implies performance improvement.

## Experimental Question

Now that the GWT/Mood bias propagates into the next cycle, does anything observable change in recovery behavior, retry strategy, certification outcome, or loop escape?

More concretely:

```text
When Topic 1 induces controlled stress and Topic 2 observes next-cycle behavior,
does ARM_ON behave measurably differently from ARM_OFF after the calibrated tensions bias?
```

## Pre-Registered Hypothesis

ARM_ON, with calibrated `tensions` bias, should show at least one disciplined behavioral improvement relative to ARM_OFF:

- faster recovery after forced failure
- fewer useless retries
- clearer strategy shift after forced failure
- equal or better certification verdict
- equal or better final score if score is available
- more orderly mood recovery after stress

The hypothesis does not require all metrics to improve. It also does not require immediate certification improvement if the primary effect is strategy routing or loop escape.

## Candidate Protocol

Use the same clean harness family as D2.1A/D2.1D:

- cached MAP/AGGREGATE sources
- zero live DDGS calls
- zero live Brave calls
- zero live Playwright calls
- subprocess isolation per arm
- manifest per run
- mood sample archiving
- same sequential two-topic structure
- controlled stress injection

Candidate sequence:

```text
cycle 1: python OOP design patterns
role: stress inducer

cycle 2: asyncio advanced patterns
role: behavioral observer
```

Arms:

```text
ARM_OFF:
  no_l3=True

ARM_ON:
  no_l3=False
  calibrated tensions bias active
```

The protocol should preserve the D2.1C/D2.1D topic sequence unless there is a documented reason to change it. If the topic sequence changes, that change must be pre-registered before running.

## Behavioral Metrics

Metrics should be computable from logs, manifests, mood samples, and existing study outputs. Avoid qualitative interpretation unless it is backed by explicit regex or structured fields.

Proposed primary metrics:

| Metric | Definition | Source |
|---|---|---|
| `recovery_success` | Topic 2 exits the forced-failure/retry loop and reaches a non-failure final state | manifest/log |
| `retries_count` | Number of retry attempts during Topic 2 | manifest/log regex |
| `strategy_shift_detected` | A new strategy, pivot directive, or materially different retry plan appears after forced failure | log regex or structured marker |
| `certification_verdict` | Certified / near-miss / failed, if available | manifest/study output |
| `final_score` | Final study/benchmark score, if emitted | manifest/log |
| `repeated_strategy_count` | Count of repeated retry plans or repeated gap language | log parser |
| `loop_risk_proxy` | Composite proxy: high retries + repeated strategy + no score movement | analyzer-derived |
| `mood_min` | Minimum mood score during the run | mood samples |
| `mood_recovery_delta` | Last mood score minus minimum mood score in Topic 2 window | mood samples |
| `workspace_bias_present` | Non-zero cycle-2 workspace_bias above near-zero threshold | mood samples |

Recommended derived fields:

```text
topic2_retries_delta = ARM_ON.topic2_retries_count - ARM_OFF.topic2_retries_count
topic2_mood_recovery_delta = final_topic2_mood - min_topic2_mood
strategy_shift_advantage = ARM_ON.strategy_shift_detected and not ARM_OFF.strategy_shift_detected
cert_non_regression = ARM_ON.certification_verdict >= ARM_OFF.certification_verdict
```

The analyzer should report all raw values even when the verdict is inconclusive.

## Signal vs Performance

D2.1D result:

```text
internal next-cycle signal propagation validated after calibration
```

D2.1E target:

```text
behavioral effect probe
```

These must remain separate. A non-zero `workspace_bias` is a signal metric. It is not itself evidence of recovery, improved retry policy, or better certification.

Allowed D2.1E claim if positive:

```text
Under this controlled sequential protocol, calibrated GWT/Mood coupling is associated with measurable behavioral differences in the observer cycle.
```

Not allowed:

```text
GWT improves SHARD performance.
```

That would require larger N, repeated runs, and outcome-level validation beyond one probe.

## Verdicts

### PASS_STRONG

Harness clean, ARM_ON has non-zero real workspace-winner signal, and ARM_ON shows at least two behavioral advantages without any major regression:

- fewer retries or lower loop-risk proxy
- strategy shift detected only in ARM_ON or stronger in ARM_ON
- equal or better certification verdict/final score
- better mood recovery delta

ARM_OFF fallback bias must be classified separately and excluded from GWT signal.

### PASS_WEAK

Harness clean and ARM_ON shows one behavioral advantage, or a plausible behavioral difference with incomplete provenance.

Examples:

- ARM_ON has better mood recovery but no score/cert change
- ARM_ON changes strategy but retry count is unchanged
- ARM_ON avoids repeated strategy loops but final verdict remains equal

### FAIL

Harness clean, ARM_ON has calibrated internal signal, but no behavioral metric improves versus ARM_OFF, or ARM_ON is worse on the main behavioral metrics.

### INCONCLUSIVE

Harness clean but behavioral metrics are too sparse, missing, contradictory, or too qualitative to support a verdict.

Examples:

- no final score emitted
- retry logs too ambiguous
- both arms behave identically but sample count is too small
- ARM_ON signal appears, but Topic 2 does not enter a meaningful observer regime

### CONTAMINATED

Any of:

- live DDGS/Brave/Playwright calls
- cache mismatch
- subprocess failure
- stress injection missing
- forced topic sequence not observed
- missing mood samples
- unexpected fallback threshold breach

## Risks

- N is too small for performance claims.
- LLM stochasticity may dominate behavioral differences.
- Behavioral metrics may be too qualitative unless structured markers are added first.
- Stress injection may be too artificial and may not generalize.
- ARM_ON may get worse because negative valence increases frustration.
- Certification rate may not change even if strategy routing changes.
- Mood recovery may improve while code/study outcome remains flat.
- ARM_OFF fallback bias can still confuse interpretation unless provenance is explicit.

## Recommendation

Run D2.1E as a small, surgical behavioral probe before any broader D2.2 operational validation.

Reason:

- D2.1D only validated internal propagation.
- D2.2 would be too broad before metrics/provenance are hardened.
- D2.1E can test whether there is any behavioral signal worth scaling.

Recommended next step before implementation:

```text
Add or reuse structured analyzer fields for Topic 2 behavior:
retries_count, recovery_success, strategy_shift_detected,
certification_verdict, final_score, mood_recovery_delta,
workspace_bias_present, and fallback provenance.
```

Only after D2.1E should D2.2 test repeated runs, larger topic sets, and recovery/cert-rate value.
