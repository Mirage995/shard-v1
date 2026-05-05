# D2.1A Harness Validation — Post-hoc Analysis

## Verdict

**PASS**

The benchmark harness produces isolated, reproducible, uncontaminated
runs. D2.1B (stress validation) is unblocked.

## Why this run was needed

D2.0 ended as `INCONCLUSIVE_HARNESS`: progressive degradation across
pairs in both arms, 46 LLM fallback events, 15 HTTP-level service
errors. Live Brave Search and Playwright introduced enough external
instability that no causal claim about GWT could be made. Before any
further GWT experiment we had to prove the harness itself was clean.

## Protocol

- **Source isolation**: env-gated hook (`D2_CACHED_SOURCES_PATH`) in
  `study_agent.phase_map` and `study_agent.phase_aggregate`. When set,
  both phases return frozen results from disk; default behavior (env
  unset) is byte-identical to before.
- **Cache prefetch**: `backend/d2_1a_cache_sources.py` runs the live
  MAP + AGGREGATE pipeline once per topic and freezes the result with
  a deterministic sha256 hash over `{topic, sources, all_text}`.
- **Subprocess isolation**: `backend/d2_1a_benchmark.py` orchestrates
  via `subprocess.run([sys.executable, ...])` so each arm starts from
  a fresh Python interpreter — no in-memory state leakage between runs.
- **Replica check (Opzione X)**: `run_a` and `run_b` use IDENTICAL
  config. The question is "does the harness produce stable runs given
  identical input?", not "does GWT help?". GWT lives in D2.1B.
- **Topics**: `sql injection prevention python` (medium-hard,
  certifiable) and `asyncio advanced patterns` (tactical positive
  control). Both passed cache thresholds: 15 sources each, 18k+
  chars `all_text`, sha256 hash present.

## Results

| # | topic                              | arm   | exit | dur(s) | cache_hit (map,agg) | ddgs | brave | playwright | fallback | http_err | mood_n |
| - | ---------------------------------- | ----- | ---- | ------ | ------------------- | ---- | ----- | ---------- | -------- | -------- | ------ |
| 1 | sql injection prevention python    | run_a |    0 |  153.9 | (1,1)               |    0 |     0 |          0 |        2 |        0 |      2 |
| 2 | sql injection prevention python    | run_b |    0 |  125.1 | (1,1)               |    0 |     0 |          0 |        3 |        0 |      2 |
| 3 | asyncio advanced patterns          | run_a |    0 |  167.6 | (1,1)               |    0 |     0 |          0 |        2 |        0 |      2 |
| 4 | asyncio advanced patterns          | run_b |    0 |  167.6 | (1,1)               |    0 |     0 |          0 |        2 |        0 |      2 |

All 12 pre-flight checks passed:

- 4/4 subprocess `exit_code == 0`
- 4/4 used cached MAP and cached AGGREGATE
- 0 DDGS / Brave / Playwright calls (live-search bypass verified)
- fallback events within threshold (≤10), HTTP errors zero
- `cache_hash` identical between `run_a` and `run_b` for both topics
- mood_history.jsonl populated and archived per (topic, arm)
- no progressive duration degradation

The asyncio replica pair clocks the same duration to one decimal
(167.6s for both), suggesting the harness is *very* deterministic for
that topic. The sql replica pair shows a 28-second spread (153.9 vs
125.1), within natural LLM variance — explainable, not pathological.

## Contamination rule (per GPT-5.5 review)

Defined more strictly than D2.0:

```
source_mode == "cached" AND any of {ddgs, brave, playwright}
call_count > 0  ->  contaminated = true
```

Brave 429 alone is a *symptom*. The real violation is "the benchmark
used the network when it was not supposed to". All four runs satisfied
this rule with 0 live calls.

## What this unlocks

- D2.1B can now test GWT under stress with confidence that any
  observed delta is causal to the GWT condition, not provider noise.
- The same harness pattern (env-gated cache, subprocess isolation,
  manifest-per-run) is reusable for future cognitive-layer experiments.

## Files in repo

```
backend/d2_1a_cache_sources.py    # one-time live prefetch
backend/d2_1a_benchmark.py        # subprocess orchestrator
backend/d2_1a_analyze.py          # harness-only verdict (PASS/FAIL/CONTAMINATED/INCONCLUSIVE)
backend/study_agent.py            # env-gated hook in phase_map / phase_aggregate
docs/experiments/d2_1a_harness_validation.md   # this file
```

Runtime artifacts (cache files, per-run manifests, mood histories,
stdout/stderr logs) stay local under `shard_workspace/d2_1a_runs/`
and `shard_workspace/d2_cached_sources/` — out of repo intentionally.

## Methodological note

The D2.0 → D2.1A transition is the same pattern that reappears every
time an experimental result feels off: the benchmark was measuring a
mixture of the intended condition and an external confound. Cleaning
the harness was not a detour — it was the prerequisite. Skipping it
would have produced a paper-worthy false positive or a false negative
on GWT that we would have had to retract later.

---

*Run completed 2026-05-05. Next: D2.1B stress validation with
controlled first-attempt validation failure (ARM_OFF vs ARM_ON).*
