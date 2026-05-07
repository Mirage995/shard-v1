# D3.0C Strategy Update Activation Plan

## Status

Planning only.
No code changes.
No benchmark run.
No operational performance claim.

## Objective

Understand why `strategy_update_count` remains zero in D3.0B and prepare a diagnostic test that can observe the strategy-update path before any behavior changes are introduced.

## Experimental Question

Is strategy memory failing to update because:

- the update path is not reached;
- the update path is reached but not instrumented;
- update gating requires certification or success signals that D3.0A/B do not produce;
- failure/certification attribution is not structured enough to create updates;
- snapshot/restore or session boundaries prevent updates from persisting across sessions?

## Scope

Planning/instrumentation only.
No behavior change yet.
No benchmark run.
No `_WINNER_BIAS` changes.
No ValenceField changes.
No stress injection changes.
No topic handling changes.
No scoring or certification threshold changes.

## Hypotheses

- H1: strategy update path is not reached.
- H2: strategy update path is reached but not instrumented.
- H3: update gating requires certification/success signals that D3.0A/B do not produce.
- H4: failure attribution is not structured enough to create strategy updates.
- H5: persistence isolation prevents strategy updates from carrying across sessions.

## Audit Targets

- `strategy_memory.py` write/update functions.
- `study_agent` strategy retrieval/update path.
- certification/final score handoff to strategy memory.
- failure attribution storage.
- session boundary persistence.
- arm snapshot/restore logic.

## Proposed Instrumentation

- `strategy_update_attempt_count`
- `strategy_update_success_count`
- `strategy_update_skip_reason`
- `strategy_update_source`
- `failure_attribution_available`
- `success_signal_available`
- `strategy_memory_write_path_hit`
- `strategy_memory_read_path_hit`
- `persistence_after_session_check`

Instrumentation should prefer structured fields emitted at the point where decisions are made. If that is not safe because the relevant files are dirty or mixed with unrelated changes, D3.0C should start with benchmark/analyzer-side diagnostics and clearly label what remains log-derived.

## Candidate D3.0C

Diagnostic only:

- reuse the D3.0B protocol;
- same 5-session sequence;
- same 2 arms;
- cached sources only;
- arm isolation via snapshot/restore;
- memory/strategy persistence enabled within each arm;
- add structured markers for strategy update attempts/skips;
- do not change update conditions yet;
- do not force updates yet.

If the update path is never reached, D3.0D may test a minimal update trigger. If the update path is reached but skipped, inspect skip reasons before changing behavior.

## Success Criteria

### PASS_STRONG

- Structured skip reasons explain why `strategy_update_count` is zero.
- Memory/strategy persistence is verified across sessions.

### PASS_WEAK

- Some update attempts or skip reasons are visible, but coverage is incomplete.

### FAIL

- Instrumentation still cannot locate the strategy update path.

### INCONCLUSIVE

- Strategy update path is ambiguous or mixed with unrelated logging.

## Recommendation

Do not scale D3.

Do not alter learning behavior yet.

First run D3.0C as a strategy-update path diagnostic. The next useful result is not a higher score; it is a structured explanation for why strategy memory is read but not updated under the current longitudinal protocol.

## Allowed Claim

D3.0C tests whether the strategy update path is reachable and explainable under D3 longitudinal conditions.

## Forbidden Claim

GWT improves SHARD performance.
