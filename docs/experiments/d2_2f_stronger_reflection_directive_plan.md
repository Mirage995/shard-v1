# D2.2F Stronger Reflection Directive Plan

## Status

Planning only.
No code changes.
No benchmark run.
No operational performance claim.

## Background

D2.2D showed that calibrated GWT/Mood signal reaches the retry/reflection path and can activate a reflection/strategy-shift directive in ARM_ON.

D2.2E showed that the existing D2.2D directive does not produce retry-strategy divergence distinguishable from ARM_OFF under the current hash proxy:

- `retry_strategy_hash_changed_rate`: `1 -> 1`
- `material_strategy_shift_rate`: `1 -> 1`
- `repeated_strategy_count_by_hash_mean`: `0 -> 0`
- `prior_strategy_named_rate`: `UNAVAILABLE`

Therefore, the next test should check whether a stronger but still non-overriding reflection directive produces clearer decision-related differences.

## Experimental Question

If the D2.2D reflection directive is made more explicit while remaining a prompt modifier, does ARM_ON show clearer decision-adjacent retry behavior than ARM_OFF under the controlled micro protocol?

## Target

Same target point:

- `backend/study_phases.py::_retry_gap_fill`

The target remains reflection/strategy-shift prompting, not retry policy.

## Proposed Stronger Directive

When ARM_ON has:

- real `tensions` signal
- stressed mood
- repeated failure

add a stronger reflection directive:

```text
You must explicitly identify the prior failed strategy, explain why it failed, and produce a materially different recovery plan. Do not reuse the same approach unless you justify why it should now work.
```

## Constraints

- Do not change `MAX_RETRY`.
- Do not change certification threshold.
- Do not change scoring logic.
- Do not change `_WINNER_BIAS`.
- Do not change `ValenceField`.
- Do not change stress injection.
- Do not change topic sequence/topic handling.
- The directive remains a prompt modifier, not an override.
- Do not force a specific strategy.
- Do not force certification.

## Expected Mechanism

```text
workspace_bias/tensions signal
-> stressed MoodEngine state
-> stronger reflection directive in retry prompt
-> explicit prior-strategy naming and recovery-plan differentiation
-> possible changes in retry strategy hash, repeated strategy, loop-risk, or final score
```

## Protocol

Rerun the D2.2A/D2.2D micro protocol:

- 2 topic sequences
- 2 reps
- ARM_OFF vs ARM_ON
- cached sources
- zero live DDGS/Brave/Playwright calls
- subprocess isolation
- controlled stress injection
- same topic sequence
- same `_WINNER_BIAS`
- same `ValenceField`
- same scoring/certification logic
- D2.2E retry hash metrics included
- same hardened analyzer lineage

## Primary Metrics

- `prior_strategy_named_rate`
- `retry_strategy_hash_changed_rate`
- `material_strategy_shift_rate`
- `repeated_strategy_count_by_hash_mean`
- `loop_risk_proxy_mean`
- `final_score_mean`
- `certification_verdict`
- `recovery_success_rate`

## Secondary Metrics

- `reflection_directive_present_rate`
- `micro_coupling_applied_rate`
- `mood_min_mean`
- `workspace_bias_present`
- `tensions_trace_count`

## Verdict Criteria

### PASS_STRONG

- Harness clean.
- ARM_ON real signal present.
- Stronger directive applied in ARM_ON.
- ARM_ON improves at least two decision-quality metrics over ARM_OFF, including `prior_strategy_named_rate` or `material_strategy_shift_rate`.
- No severe regression in `final_score_mean`, certification, or recovery.

### PASS_WEAK

- Harness clean.
- Stronger directive applied.
- ARM_ON improves one decision-quality metric, or `prior_strategy_named_rate` becomes available/distinct.
- Hard outcomes remain unchanged.

### FAIL

- Harness clean.
- Stronger directive applied but no decision-quality metric changes.
- Or `final_score_mean`/certification regresses meaningfully.

### INCONCLUSIVE

- Metrics remain too proxy/log-derived.
- Retry plan boundaries are unclear.
- Stochasticity dominates.

### CONTAMINATED

- Live calls observed.
- Cache mismatch.
- Subprocess failure.
- Stress injection missing.
- Topic sequence missing.
- Mood samples missing.

## Risks

- Over-reflection.
- Prompt rigidity.
- Worse `final_score_mean`.
- LLM spends effort explaining instead of fixing.
- Still no semantic strategy shift.
- Small N.
- Hash metrics may remain too proxy-derived to capture semantic differences.

## Allowed Claim

If positive:

```text
Under a stronger but still non-overriding reflection directive, ARM_ON shows clearer decision-adjacent retry behavior than ARM_OFF under the controlled micro protocol.
```

## Forbidden Claims

```text
GWT improves SHARD performance.
```

```text
D2.2F proves operational value.
```

```text
SHARD is more intelligent.
```

## Recommendation

Proceed with planning commit first. Implementation should happen separately after approval.
