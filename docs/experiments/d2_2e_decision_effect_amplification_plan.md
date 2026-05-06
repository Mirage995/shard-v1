# D2.2E Decision Effect Amplification Plan

## Status

Planning only.
No code changes.
No benchmark run.
No behavioral or operational claim.

## Background

D2.2D produced `PASS_WEAK`.

It confirmed that calibrated GWT/Mood signal can activate a reflection/strategy-shift directive in the retry path. ARM_ON showed real signal in `4/4` runs, micro-coupling application in `4/4` runs, and a less severe `mood_min_mean`. It also showed a small `final_score_mean` increase.

However, hard operational metrics did not move:

- `retries_count_mean`: `2 -> 2`
- `loop_risk_proxy_mean`: `4 -> 4`
- `repeated_strategy_count_mean`: `1 -> 1`
- `recovery_success_rate`: `0 -> 0`
- `benchmark_score_mean`: `UNAVAILABLE`

## Experimental Question

Does the D2.2D reflection micro-coupling fail to change hard operational metrics because the directive is too weak, or because current metrics cannot reliably detect material retry-strategy changes?

## Hypothesis

If the existing D2.2D micro-coupling already causes material retry-strategy changes, then structured retry strategy hashes should show ARM_ON diverging from prior strategy more often than ARM_OFF.

If strategy hashes show no material divergence, then a stronger reflection directive may be needed in a later experiment.

## Option A - Stronger Reflection Directive

Keep the same target point:

- `backend/study_phases.py::_retry_gap_fill`

Make the directive more binding while still avoiding override behavior.

Candidate wording:

```text
You must explicitly name the failed prior strategy and produce a materially different retry plan.
```

Constraints:

- Do not change `MAX_RETRY`.
- Do not change certification thresholds.
- Do not change scoring logic.
- Do not change `_WINNER_BIAS`.
- Do not change `ValenceField`.
- Do not change stress injection.
- Do not change topic sequence/topic handling.
- The directive remains a modifier, not a forced strategy.

Expected benefit:

- More observable reflection/strategy-shift behavior.
- Potential decrease in repeated strategy count or loop-risk proxy.

Risk:

- Over-reflection.
- Prompt rigidity.
- LLM may spend effort explaining the failed strategy instead of producing better code/study output.
- Final score may regress if the directive becomes too intrusive.

## Option B - Better Retry Quality Metrics First

Do not change behavior.

Add structured instrumentation to measure whether retry strategy materially changes.

Candidate structured fields:

- `retry_plan_id`
- `retry_strategy_hash`
- `prior_strategy_hash`
- `retry_strategy_hash_changed`
- `prior_strategy_named`
- `material_strategy_shift`
- `repeated_strategy_count_by_hash`

Analyzer behavior:

- Prefer structured fields.
- Fall back to conservative log parsing only if structured fields are absent.
- Keep metrics `MISSING` or `UNAVAILABLE` when extraction is not reliable.

Expected benefit:

- Separates "directive was emitted" from "retry strategy actually changed."
- Avoids tuning the prompt before measuring the real failure mode.
- Improves D2.2 full readiness.

Risk:

- Another instrumentation pass.
- Strategy hashing may still be sensitive to superficial wording.
- Requires careful normalization to avoid false positives.

## Proposed Balanced Plan

D2.2E should add minimal structured retry-strategy measurement and keep the existing D2.2D micro-coupling unchanged for one rerun.

Specifically:

- Add `retry_strategy_hash` and `prior_strategy_hash`.
- Add `retry_strategy_hash_changed`.
- Add `prior_strategy_named` if the retry prompt explicitly names the previous failed strategy.
- Add `material_strategy_shift` as a conservative structured or analyzer-derived field.
- Rerun the same D2.2A/D2.2D micro protocol.

If strategy hashes show no material ARM_ON difference, consider a stronger directive in D2.2F.

## Candidate Protocol

Reuse D2.2D protocol:

- 2 topic sequences
- 2 replicas
- ARM_OFF vs ARM_ON
- cached sources
- zero DDGS/Brave/Playwright calls during benchmark
- subprocess isolation
- controlled stress injection
- same topic sequence
- same `_WINNER_BIAS`
- same `ValenceField`
- same scoring and certification thresholds
- same existing D2.2D micro-coupling

## Primary Metrics

- `retry_strategy_hash_changed`
- `prior_strategy_named`
- `material_strategy_shift`
- `repeated_strategy_count_by_hash`
- `final_score`
- `certification_verdict`
- `recovery_success`

## Secondary Metrics

- `reflection_directive_present`
- `micro_coupling_applied`
- `workspace_bias_present`
- `tensions_trace_count`
- `mood_min`
- `mood_recovery_delta`
- `loop_risk_proxy`
- `retries_count`

## Verdict Criteria

### PASS_STRONG

- Harness clean.
- ARM_ON real signal present.
- Existing D2.2D micro-coupling applied.
- ARM_ON improves at least two decision-quality metrics, including `retry_strategy_hash_changed` or `material_strategy_shift`.
- No severe regression in final score, certification, or recovery.

### PASS_WEAK

- Harness clean.
- ARM_ON shows clearer retry-strategy divergence by hash or prior strategy naming.
- Hard outcomes remain unchanged.

### FAIL

- Harness clean.
- Micro-coupling applied but strategy hashes show no ARM_ON divergence and hard metrics remain unchanged.
- Or ARM_ON regresses meaningfully in final score/certification.

### INCONCLUSIVE

- Strategy hash extraction is fragile.
- Retry plan boundaries are unclear.
- Metrics are too sparse.
- Stochasticity dominates the small N.

### CONTAMINATED

- Live calls observed.
- Cache mismatch.
- Subprocess failure.
- Stress injection missing.
- Topic sequence missing.
- Mood samples missing.

## Risks

- Strategy hashing can over-count superficial wording changes.
- Instrumentation can become too invasive if it changes prompt construction.
- Metrics may still miss semantic strategy changes.
- Small N can hide or exaggerate effects.
- Keeping the existing D2.2D directive may be too weak to move behavior.
- A stronger directive may later be needed, but should be tested separately.

## Recommendation

Prefer Option B for rigor.

D2.2E should harden retry-quality measurement first while keeping the existing D2.2D micro-coupling unchanged. If structured retry strategy hashes show no material ARM_ON difference, then D2.2F can pre-register a stronger reflection directive.

If speed is more important than measurement clarity, Option A is available, but it increases the risk of prompt tuning without knowing whether the current directive already changes retry strategy.

## Allowed Claim

If positive:

```text
Under the D2.2D micro-coupling, ARM_ON shows structured evidence of retry-strategy divergence in the observer cycle.
```

## Forbidden Claims

```text
GWT improves SHARD performance.
```

```text
D2.2E proves operational value.
```
