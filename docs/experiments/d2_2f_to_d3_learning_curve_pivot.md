# D2.2F to D3 Learning Curve Pivot

## Status

Planning/interpretation only.
No code changes.
No benchmark run.
No operational claim.

## Why The D2.2 Prompt-Directive Path Is Exhausted

D2.1D and D2.2A validated calibrated GWT/Mood signal propagation.

D2.2D validated decision-adjacent prompt coupling: the calibrated signal can reach the retry/reflection prompt path and activate a reflection/strategy-shift directive.

D2.2E and D2.2F showed that stronger prompt directives do not separate ARM_ON from ARM_OFF on immediate operational metrics:

- retry strategy hash changes do not distinguish ARM_ON from ARM_OFF;
- recovery does not improve;
- retry count does not improve;
- loop-risk proxy does not improve;
- D2.2F slightly regresses `final_score_mean`.

Continuing to increase prompt-level directive strength risks prompt tuning rather than architecture validation. The D2.2 prompt-directive path has therefore reached a useful stopping point.

## Core Insight

SHARD should not be evaluated only as:

```text
better than the LLM in a single run
```

SHARD should be evaluated as a system with a learning curve:

- memory
- strategy memory
- failure attribution
- meta-learning
- repeated exposure improvement
- cross-cycle adaptation

The central hypothesis of SHARD is not that one inference becomes magically better. The stronger claim is that the system can accumulate structured experience and improve across sessions or cycles.

## New Experimental Question

Does calibrated GWT/Mood coupling improve SHARD's learning curve across repeated sessions, rather than immediate single-run performance?

## Proposed D3.0 Learning Curve Validation

Candidate protocol:

- same topic or topic family repeated across N sessions
- ARM_OFF vs ARM_ON
- same cached sources
- subprocess isolation where possible
- memory/strategy persistence intentionally enabled for learning condition
- compare improvement slope across sessions

The key change is that persistence is no longer treated only as contamination risk. For D3.0, persistence becomes part of the experimental object because learning curve is the target.

## Candidate Metrics

Primary metrics:

- final_score slope across sessions
- certification rate over sessions
- repeated failure reduction
- recovery success over sessions
- strategy update quality
- failure attribution accuracy
- memory recall relevance
- loop recurrence reduction

Secondary metrics:

- mood_min trend
- workspace_bias trend
- strategy reuse quality
- number of retries before recovery
- semantic similarity between failed strategy and later strategy

## Key Distinction

D2 tested immediate mechanism and single-run effects.

D3 should test longitudinal learning.

D2 answered whether the signal can propagate and reach decision-adjacent prompt construction. D3 should ask whether the architecture improves its behavior across repeated exposure.

## Possible Arms

### Option A

```text
ARM_OFF = GWT/Mood disabled, memory/strategy persistence enabled
ARM_ON  = GWT/Mood enabled, memory/strategy persistence enabled
```

This is the simplest learning-curve comparison.

### Option B

Add memory-disabled controls if feasible:

- ARM_OFF memory off
- ARM_ON memory off
- ARM_OFF memory on
- ARM_ON memory on

This better separates GWT/Mood from memory persistence, but it is more expensive and may require more harness work.

## Risks

- memory contamination
- harder causal attribution
- longer runtime
- stochasticity
- need clear session boundaries
- need stable scoring
- risk that LLM variability hides slope

## Recommendation

Stop adding stronger prompt directives in D2.

Write a D2 final synthesis:

- mechanism validated
- immediate operational value not demonstrated
- prompt-level coupling insufficient

Then move to D3.0 Learning Curve Validation.

Recommended sequence:

```text
D2 Final Synthesis -> D3.0 Learning Curve Validation Plan
```

## Allowed Claims

```text
D2 validated internal and decision-adjacent signal propagation.
```

```text
D2 did not demonstrate robust immediate operational improvement.
```

```text
D3 should test whether SHARD's architecture improves learning across sessions.
```

## Forbidden Claims

```text
GWT improves SHARD performance.
```

```text
SHARD is more intelligent.
```

```text
D2 proves operational value.
```
