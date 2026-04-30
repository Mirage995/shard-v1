# D2.0 Frustration Benchmark — Post-hoc Analysis

## Verdict

**INCONCLUSIVE_HARNESS**

D2.0 cannot support either H1 or H0. Both arms degraded progressively
across pairs, external-service instability exceeded the contamination
threshold, and the intended stress regime was not reached.

## Key Results

| Metric    | ARM_A / GWT_ON | ARM_B / GWT_OFF |   Delta |
| --------- | -------------: | --------------: | ------: |
| Cert rate |          11.1% |           11.1% |  +0.0pp |
| Avg score |           0.84 |            1.58 |   -0.74 |

Pair trend (cert rate):

- ARM_A: 33.3% → 0% → 0%
- ARM_B: 33.3% → 0% → 0%

Both arms collapse together pair-by-pair. This rules out a clean
GWT_ON vs GWT_OFF causal attribution.

## Harness Contamination

Detected anomalous external-service events during the run:

- LLM fallback / provider-switch events: 46
- HTTP errors (Brave 429, provider 5xx): 15
- Total anomalous events: 61

These exceeded the recommended contamination threshold (>10 fallback
or >3 HTTP per arm) and affect the interpretability of the run. The
749 `[LLM_ROUTER]` markers in the raw log were largely routine routing
traces, NOT errors — overcounting them as "errors" would have been an
overstatement.

## Stress Regime Check

The intended stress regime was not reached:

- mood never crossed -0.3
- lowest observed mood was approximately **-0.290** (literally on the
  doorstep of the ValenceField activation threshold, but not across)
- workspace_bias stayed at 0.0 across all six (pair, arm) trajectories
- MoodWorkspaceCoupling remained dormant

This means D2.0 did not truly test GWT behavior under stress; it tested
the GWT flag plus an unstable long-run harness with no actual stress
activation.

## Recovery Metrics

SERR (same-error repeat rate), SSR (strategy shift rate), and TNA
(time to novel attempt) were marked **UNAVAILABLE**. Per-attempt
`error_signature` and `strategy_used` data are captured at runtime by
SHARD but not serialized into `d2_frustration_results.json` in the
current schema. Missing data was not coerced into zero / "no change",
preserving methodological honesty.

## Interpretation

D2.0 was inconclusive as a causal GWT benchmark. Both arms degraded
across pairs, external-service instability exceeded the contamination
threshold, and the intended stress regime was not reached: mood never
crossed -0.3 and workspace coupling remained dormant. The next protocol
must isolate each arm in a fresh subprocess, use cached/fixed sources,
and validate harness stability before testing GWT recovery effects.

## Next Protocol: D2.1

D2.1 must be split into two phases:

### D2.1A — Harness validation (no forced stress)

- single-pair diagnostic run
- restore baseline snapshot
- spawn fresh subprocess for ARM_A; process exits
- restore baseline snapshot
- spawn fresh subprocess for ARM_B; process exits
- use cached / fixed MAP-phase sources to avoid Brave Search 429
- log provider/model per attempt
- abort thresholds:
  - fallback events > 10 per arm → mark contaminated, abort
  - HTTP 4xx/5xx errors > 3 per arm → mark contaminated, abort
  - or normalized: fallback rate > 5% of LLM calls

The goal is to prove the harness is stable. No GWT conclusion drawn.

### D2.1B — Stress validation

Only after D2.1A demonstrates harness stability:

- inject controlled repeated failures or use harder topics
- verify mood actually crosses -0.3
- measure GWT recovery dynamics under proven stress
- compute SERR / SSR / TNA from extended schema

## Methodological notes

- The 749 → 61 correction (router traces vs real anomalies) follows
  the same pattern as the GWT diagnosis correction the day before:
  evidence is precise, not gonfiata.
- mood_history trajectories were identical across (ARM_A, ARM_B) of
  the same pair. Plausibly innocuous (deterministic MoodEngine with
  identical inputs and `workspace_bias=0`), but D2.1 should embed
  `run_id` / `arm` / `pair` inside each mood sample so the origin is
  not inferred from filename.

---

*Run completed 2026-04-30 with `backend/d2_run_all.sh` (3 paired
sessions × 3 topics). Raw artifacts stay local under
`shard_workspace/d2_*` — out of repo intentionally.*
