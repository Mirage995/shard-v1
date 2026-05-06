# D2.2B Metric Hardening

Planning commit: `02dc5e34574cdf1fa25683262cf8eb83468f0291`

## Status

Instrumentation implemented. No benchmark was run in this step.

## Objective

D2.2B hardens D2.2A behavioral metrics so future validation runs can read structured manifest fields before falling back to log parsing.

This is instrumentation only. It does not change SHARD behavior.

## Structured Fields Added

Future D2.2A benchmark manifests now include:

- `observer_window`
- `behavior_metrics`
- `bias_provenance`
- `mood_metrics`
- `signal_metrics`
- `metric_hardening`

### `behavior_metrics`

Structured observer-cycle fields:

- `retries_count`
- `recovery_success`
- `strategy_shift_detected`
- `repeated_strategy_count`
- `certification_verdict`
- `certification_rank`
- `final_score`
- `benchmark_score`
- `benchmark_score_status`
- `loop_risk_proxy`

### `bias_provenance`

Structured provenance fields:

- `workspace_bias_present`
- `real_workspace_signal`
- `fallback_bias_excluded`
- `workspace_bias_source`
- `dominant_winner`
- `winner_module`
- `ignition_failed`
- `fallback_source`
- `tensions_trace_count`
- `gwt_bid_trace_count`

### `observer_window`

Structured Topic 2 boundary fields:

- `topic`
- `start_marker`
- `found`
- `start_index`
- `source`

## Analyzer Behavior

`backend/d2_2a_analyze.py` now consumes structured manifest fields when present:

- `behavior_metrics` is preferred over observer stdout parsing.
- `bias_provenance` is preferred over inferred fallback/signal classification.
- `mood_metrics` is preferred over recomputing mood trajectories from archived mood samples.
- `signal_metrics` is preferred over GWT trace parsing.

If structured fields are absent, the analyzer falls back to the previous conservative log-derived extraction path. Missing or unreliable metrics remain `MISSING` or `UNAVAILABLE`.

## Still Log-Derived

The first D2.2B pass intentionally avoids changing runtime behavior or core pipeline logic. The following fields are still derived from existing emitted events by the benchmark instrumentation:

- observer window boundary from the existing `Starting study of '<topic>'` marker;
- retry count from existing retry event text;
- strategy shift from existing critic/swarm/pivot markers;
- certification verdict and final score from existing `[CERTIFY]` lines;
- benchmark score from existing `[BENCHMARK_RUN]` lines when present;
- tensions trace count from existing `[GWT_BID_TRACE]` lines.

This is a hardening step because the extraction result is stored in structured manifests for future analyzer consumption, but it is not yet a core event schema emitted directly by `StudyAgent` or `NightRunner`.

## Still Missing / Unavailable

- `benchmark_score` remains `UNAVAILABLE` when no reliable `[BENCHMARK_RUN]` score is emitted in the observer cycle.
- `recovery_success` remains dependent on certification/final score availability.
- `strategy_shift_detected` and `repeated_strategy_count` are still proxy metrics until the study loop emits explicit strategy IDs or strategy transition events.

## Behavior Guardrails

This step does not modify:

- `_WINNER_BIAS`;
- ValenceField;
- stress injection;
- topic handling;
- subprocess command shape;
- D2.2A topic sequences;
- arms;
- scoring logic;
- decision logic.

The D2.2A benchmark command, stress mode, topic sequence, arms and cached-source harness remain unchanged.

## Validation Recommendation

After this hardening commit, rerun the same D2.2A protocol as D2.2B validation:

```text
python backend/d2_2a_benchmark.py
python backend/d2_2a_analyze.py shard_workspace/d2_2a_runs/<RUN_DIR>
```

Expected validation check:

- manifests contain `behavior_metrics`, `bias_provenance`, `mood_metrics`, `signal_metrics` and `observer_window`;
- analyzer reports the same verdict class or a refined verdict using structured fields;
- `MISSING`/`UNAVAILABLE` count is reduced where structured data exists;
- no run artifacts are committed.

## Claim Boundary

Allowed:

```text
D2.2B improves metric reliability for controlled operational validation of calibrated GWT/Mood coupling.
```

Forbidden:

```text
GWT improves SHARD performance.
```
