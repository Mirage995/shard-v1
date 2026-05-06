# D3.0B Memory/Strategy Instrumentation Plan

## Status

Planning only.
No code changes.
No benchmark run.
No operational performance claim.

## Rationale

D3.0A finally tested SHARD as a longitudinal system rather than a single-run enhancer. The result was `PASS_WEAK`: ARM_ON improved on loop-risk and repeated-strategy proxy slopes, but `final_score_slope` regressed and the memory/strategy evidence stayed flat.

The flat memory/strategy metrics may mean one of several things:

- SHARD is not actually using memory/strategy persistence in this protocol.
- The current metrics do not capture real memory/strategy use.
- Snapshot/restore isolation is preserving arm separation but obscuring useful persistence evidence.
- The topic sequence does not stimulate enough retrieval or strategy update behavior.

## Experimental Question

Are memory and strategy-memory components actually participating in the D3 learning curve, or is the benchmark mostly measuring repeated isolated sessions?

## Scope

Instrumentation/planning only.
No behavior change.
No benchmark run.
No `_WINNER_BIAS` changes.
No ValenceField changes.
No stress injection changes.
No topic handling changes.
No scoring or certification threshold changes.

## Metrics To Harden

- `memory_recall_count`
- `memory_recall_relevance`
- `failure_memory_reused`
- `strategy_update_count`
- `strategy_reuse_count`
- `strategy_success/failure attribution`
- `prior_failure_referenced`
- `avoided_previous_failure`
- `cross_session_strategy_delta`
- `session_to_session_learning_event`

## Checks Needed Before D3.0B Run

- Verify memory persistence within each arm.
- Verify no arm leakage.
- Verify strategy memory writes happen.
- Verify strategy memory reads happen.
- Verify failure attribution is stored.
- Verify later sessions can retrieve earlier failures.
- Verify snapshot/restore does not erase within-arm learning.

## Candidate D3.0B

D3.0B should reuse the D3.0A shape:

- same 5-session sequence
- same 2 arms
- memory/strategy persistence enabled within each arm
- arm isolation preserved
- cached sources only
- no full night run
- no stronger directive changes
- no scoring changes

The difference should be explicit structured memory/strategy instrumentation. The analyzer should prefer structured events over log proxies and report `MISSING` or `UNAVAILABLE` when evidence is not reliable.

## Success Criteria

### PASS_STRONG

- Structured evidence shows memory/strategy writes and reads.
- ARM_ON shows stronger cross-session adaptation than ARM_OFF.
- `final_score` or certification slope is not worse.

### PASS_WEAK

- Structured memory/strategy events become visible, but outcome slopes remain mixed.

### FAIL

- No memory/strategy events are observed despite persistence being enabled.
- Or ARM_ON remains worse with no adaptation evidence.

### INCONCLUSIVE

- Instrumentation cannot distinguish memory use from prompt/context reuse.
- Session boundaries or arm isolation are not reliable enough.

## Risks

- Instrumentation may still be too log-derived.
- Adding structured markers could accidentally miss hidden memory paths.
- Memory relevance is harder to score than memory presence.
- The current topic sequence may not require enough retrieval.
- Snapshot/restore may need additional validation before larger D3 runs.

## Recommendation

Do not scale D3 yet.

Run D3.0B first as a memory/strategy instrumentation hardening pass or diagnostic probe. The next useful question is not whether ARM_ON can produce another weak proxy trend, but whether SHARD is measurably writing, retrieving, and adapting from memory across sessions.

## Allowed Claim

D3.0B prepares SHARD for better longitudinal evaluation by hardening memory and strategy-learning observability.

## Forbidden Claim

GWT improves SHARD performance.
