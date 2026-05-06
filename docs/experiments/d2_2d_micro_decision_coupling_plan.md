# D2.2D Micro Decision Coupling Plan

## Status

Planning only. No code changes. No benchmark run. No behavioral claim.

## Background

D2.1D validated internal next-cycle signal propagation after calibrating the stress-dominant `tensions` winner.

D2.1E and D2.2A confirmed repeatable observer-cycle signal and a less severe `mood_min` in ARM_ON.

D2.2C traced the decision path and found that the calibrated GWT/Mood signal reaches mood/context pathways, but does not directly enter the main operational gates: retry policy, strategy retrieval, reflection trigger, certification verdict, final_score / benchmark_score path, or loop-risk proxy.

## Experimental Question

Se il segnale GWT/Mood viene collegato in modo minimale a un singolo decision gate operativo, produce differenze misurabili su strategy shift, repeated strategy, retry quality, recovery o loop-risk?

## Target Decision Gate

Recommended target: reflection trigger.

Options considered:

- A. retry policy
- B. reflection trigger

Reflection trigger is the preferred target because it is safer than retry policy. It does not change `MAX_RETRY`, certification threshold, score calculation, topic sequence or stress injection. It can only increase the priority or explicitness of a reflective/strategy-shift directive when stress plus repeated failure are present.

Retry policy is a stronger intervention and should be deferred unless reflection coupling fails. Direct retry-policy changes risk confounding the experiment by changing the number of attempts rather than the quality of strategy adaptation.

## Proposed Micro-Fix

Small, pre-registered, non-invasive fix:

```text
if ARM_ON and real_workspace_signal indicates tensions/stress and repeated failure is detected:
    add or prioritize reflection/strategy-shift directive for next retry
```

Operational framing:

- use the existing GWT/Mood signal as a modifier;
- do not override the retry loop;
- do not force certification;
- do not force a strategy;
- only make the reflective/strategy-shift prompt more explicit when the signal and repeated failure agree.

Rules:

- do not change `MAX_RETRY`;
- do not change certification threshold;
- do not change scoring logic;
- do not change `_WINNER_BIAS`;
- do not change ValenceField;
- do not change stress injection;
- do not change topic sequence;
- signal must be a modifier, not an override.

## Expected Mechanism

Expected causal chain:

```text
workspace_bias / tensions signal
-> MoodEngine + context state
-> micro-coupled reflection trigger
-> more explicit strategy-shift or anti-repetition directive
-> less repeated strategy or better retry quality
-> possible improvement in loop-risk or recovery
```

This tests whether the missing link after D2.2C is signal-to-decision coupling, not signal propagation.

## Protocol

Rerun the D2.2A micro protocol:

- same 2 sequences;
- 2 reps;
- ARM_OFF vs ARM_ON;
- cached sources;
- zero live calls;
- subprocess isolation;
- controlled stress injection;
- same topic sequence;
- same analyzer and hardened metrics.

Topic sequences:

1. `python OOP design patterns` -> `asyncio advanced patterns`
2. `sql injection prevention python` -> `python error handling patterns`

## Primary Metrics

- `strategy_shift_detected`
- `repeated_strategy_count`
- `loop_risk_proxy`
- `recovery_success`
- `retries_count`
- `certification_verdict`
- `final_score`

## Secondary Metrics

- `mood_min`
- `mood_recovery_delta`
- `workspace_bias_present`
- `tensions_trace_count`
- `reflection_trigger_count`
- `reflection_directive_present`

## Success Criteria

### PASS_STRONG

- harness clean;
- ARM_ON shows real signal;
- ARM_ON improves at least 2 primary metrics related to decision behavior, not only `mood_min`;
- no severe regression in `final_score` or certification.

### PASS_WEAK

- ARM_ON improves reflection/strategy/repeated-strategy metrics;
- recovery/certification may remain unchanged;
- signal provenance remains clear.

### FAIL

- signal present but no decision metric changes;
- or ARM_ON worsens `final_score` or certification meaningfully.

### INCONCLUSIVE

- metrics missing or ambiguous;
- reflection trigger not observable;
- stochasticity dominates.

### CONTAMINATED

- live calls;
- cache mismatch;
- subprocess failure;
- stress injection missing;
- topic sequence missing.

## Risks

- micro-fix too weak to change behavior;
- micro-fix too strong and causes over-reflection;
- prompt-only directive may still be ignored by LLM;
- strategy metrics remain proxy-based;
- final_score may regress due to extra reflection;
- the observed difference may still be limited to mood/context rather than outcome-level value.

## Forbidden Claims

- "GWT improves SHARD performance"
- "D2.2D proves operational value"
- "SHARD is more intelligent"

## Allowed Claim

If positive:

```text
Under a controlled micro-coupling protocol, calibrated GWT/Mood signal influences a specific decision-adjacent behavior such as reflection or strategy-shift prompting.
```

## Recommendation

Proceed with this planning commit first. Implementation should happen in a separate commit after approval.

D2.2D should not become D2.2 full. It should test exactly one micro-coupling point: reflection trigger as a small modifier under stress plus repeated failure.
