# D2 Final Checkpoint

## One-line conclusion

D2 validated internal and decision-adjacent GWT/Mood signal propagation, but did not demonstrate robust operational performance improvement.

## What worked

- Clean harness: D2.1A validated cached-source execution, subprocess isolation, stable cache hashes, and zero live DDGS/Brave/Playwright calls during benchmark runs.
- Cached sources / zero live provider contamination: later D2 runs reused the clean harness lineage instead of relying on live providers.
- Next-cycle signal propagation: D2.1B showed that single-cycle protocols cannot observe MoodWorkspaceCoupling properly, because workspace winners affect the next mood computation.
- `tensions` zero-bias bug found and calibrated: D2.1C identified that the stress-dominant winner was numerically silent; D2.1D calibrated `tensions` and produced observable next-cycle `workspace_bias`.
- ARM_ON real signal repeatable: D2.2A and later runs repeatedly observed ARM_ON real workspace signal while excluding ARM_OFF synthetic fallback bias.
- `mood_min` improved: ARM_ON consistently showed less severe mood minima under the controlled micro protocols.
- Reflection directive applied in ARM_ON: D2.2D and D2.2F confirmed that the calibrated signal can reach a decision-adjacent retry/reflection prompt path.

## What did not work

- `recovery_success` did not improve.
- `retries_count` did not improve.
- `loop_risk_proxy` did not improve.
- Certification did not improve.
- `benchmark_score` remained unavailable in the micro protocol.
- Stronger prompt directive did not improve strategy metrics and regressed `final_score_mean` in D2.2F.

## Main interpretation

D2 is a mechanism-validation phase, not a performance-validation phase.

The signal arrives: GWT/Mood coupling can propagate internally, affect next-cycle mood state, and reach decision-adjacent prompt construction. However, the D2 micro protocols show that prompt-level coupling is not enough to produce robust operational gains in single-run retry behavior.

The key result is disciplined and negative-positive at the same time:

- positive: the mechanism is real and observable under controlled conditions;
- negative: immediate operational value is not demonstrated.

## Why stop D2 here

Continuing with stronger prompt directives risks prompt tuning rather than architecture validation.

D2.2E showed that retry strategy hash divergence did not distinguish ARM_ON from ARM_OFF. D2.2F showed that strengthening the directive still did not improve decision-quality metrics and slightly worsened `final_score_mean`.

The next experiment should not ask whether SHARD can beat the LLM in a single inference. It should ask whether SHARD improves across sessions and cycles.

## Next phase

D3.0 Learning Curve Validation:

test improvement across sessions/cycles using memory, strategy memory, failure attribution, and meta-learning.

D3 should evaluate SHARD as a learning system:

- repeated topic or topic-family exposure;
- memory and strategy persistence intentionally enabled;
- ARM_OFF vs ARM_ON over multiple sessions;
- improvement slope measured over time;
- causal caveats tracked explicitly.

## Allowed claims

- D2 validates internal and decision-adjacent signal propagation.
- D2 does not prove operational performance improvement.
- D3 should test longitudinal learning.

## Forbidden claims

- GWT improves SHARD performance.
- SHARD is more intelligent.
- D2 proves operational value.
