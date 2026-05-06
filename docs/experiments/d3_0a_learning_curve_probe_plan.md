# D3.0A Learning Curve Probe Plan

## Status

Planning only.
No code changes.
No benchmark run.
No operational claim.

## Background

D2 validated the internal and decision-adjacent GWT/Mood mechanism under controlled protocols.

D2 did not demonstrate robust prompt-level operational value in immediate single-run micro protocols.

SHARD should now be tested as a system with memory, strategy memory, failure attribution, and cross-session adaptation rather than as a single-inference enhancer.

## Experimental Question

Does calibrated GWT/Mood coupling improve SHARD's learning curve across repeated sessions, rather than immediate single-run performance?

## Core Hypothesis

ARM_ON may not outperform ARM_OFF in session 1, but should improve faster across sessions by:

- recalling failure memories better
- avoiding repeated failure modes
- updating strategies more effectively
- reducing loop recurrence
- improving final_score/certification slope over time

## Protocol Candidate

D3.0A small probe:

- one coherent topic family
- 5 sessions per arm
- ARM_OFF vs ARM_ON
- memory/strategy persistence intentionally enabled
- same topic family repeated or varied slightly across sessions
- cached/reproducible sources where possible
- stable scoring
- no D3 full autonomous night run yet

Suggested topic family:

```text
Python async / error handling / retry/backoff patterns
```

Candidate session sequence:

1. python error handling patterns
2. async retry/backoff patterns
3. asyncio advanced patterns
4. python OOP design patterns
5. resilient python service design

## Arms

Minimum:

ARM_OFF:

- GWT/Mood disabled
- memory/strategy persistence enabled

ARM_ON:

- GWT/Mood enabled
- memory/strategy persistence enabled

Optional future controls:

- memory off + GWT off
- memory off + GWT on
- memory on + GWT off
- memory on + GWT on

D3.0A should start with 2 arms only.

## Primary Metrics

- final_score slope across sessions
- certification rate over sessions
- repeated failure reduction
- recovery_success trend
- strategy update quality
- failure attribution accuracy
- memory recall relevance
- loop recurrence reduction

## Secondary Metrics

- mood_min trend
- workspace_bias trend
- retries before recovery
- strategy reuse quality
- semantic distance from failed strategies
- failure memory reuse count
- successful strategy reuse count

## Required Instrumentation

Available or approximated fields needed:

- session_id
- arm
- topic family
- prior session memory recall
- failure attribution record
- strategy update record
- strategy reuse record
- final_score
- certification_verdict
- retry count
- loop risk
- memory items retrieved
- memory item relevance if available

## Learning Curve Criteria

### PASS_STRONG

- ARM_ON shows better positive slope on at least 2 primary metrics.
- Improvement appears after repeated sessions, not just session 1.
- Memory/strategy evidence supports the improvement.
- No severe regression.

### PASS_WEAK

- ARM_ON shows better slope on secondary metrics or one primary metric.
- Evidence suggests learning but outcome metrics remain mixed.

### FAIL

- No slope advantage.
- Or ARM_ON degrades over sessions.

### INCONCLUSIVE

- Scoring unstable.
- Memory contamination.
- Metrics missing.
- Stochasticity dominates.

### CONTAMINATED

- Source/cache mismatch.
- Uncontrolled live provider contamination if disallowed.
- Session persistence broken.
- Memory reset accidentally.
- Arm leakage.

## Causal Caveat

D3.0A is more realistic but less causally isolated than D2.

It tests system-level learning, not isolated micro-coupling.

## Risks

- memory contamination
- causal attribution harder
- LLM stochasticity
- runtime/API cost
- scoring instability
- topic drift
- benchmark_score still unavailable unless instrumented
- dirty preexisting `backend/night_runner.py` and `backend/study_agent.py` should be reviewed before implementation

## Recommendation

Start with D3.0A as a small learning curve probe.

Do not run a full autonomous night benchmark yet.

Do not claim performance improvement unless slopes support it.

## Allowed Claims

- D3.0A tests whether SHARD learns better across sessions.
- D2 validated mechanism; D3 tests longitudinal learning.

## Forbidden Claims

- GWT improves SHARD performance.
- SHARD is more intelligent.
- D3 proves autonomous learning before results.
