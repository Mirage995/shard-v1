# D2.1B Stress Validation — Post-hoc Analysis

## Verdict

**FAIL (pre-registered) — but with an important structural finding.**

The pre-registered verdict criteria were not met: workspace_bias
remained 0.0 in every arm, including ARM_ON. The expected GWT coupling
signal did not appear in the data.

However, the failure is informative. D2.1B did not falsify GWT or
MoodWorkspaceCoupling. It falsified the adequacy of a single-topic /
single-cycle protocol for detecting an inter-topic coupling effect.

## Key finding

`MoodWorkspaceCoupling` is structurally inter-topic / next-cycle by
design. The execution flow inside one `night_runner` cycle is:

1. cycle start — `MoodEngine.compute(workspace_bias=PREV_CYCLE_BIAS)`
2. `study_topic` runs (synthesis, sandbox, validation, retry loop)
3. workspace winners accumulate inside `CognitionCore`
4. cycle end — `drain_session_winners()` calls
   `MoodWorkspaceCoupling.on_workspace_result(...)` per winner
5. bias becomes available for the **next** cycle's `MoodEngine.compute`
6. benchmark ends before another cycle runs, so the bias is never
   consumed within the observation window

Single-topic D2.1B benchmarks therefore cannot observe the coupling
even when the mood pipeline is correctly wired and stress is induced.

## Protocol

- Harness: D2.1A-validated (cached MAP/AGGREGATE, subprocess isolation,
  manifest-per-run).
- Arms: `ARM_OFF` (`no_l3=True`, GWT disabled) vs `ARM_ON`
  (`no_l3=False`, GWT enabled). Identical cache, identical stress.
- Stress injection: env-gated cognitive failure at the validation
  boundary. `D2_STRESS_MODE=1`, `D2_STRESS_PROFILE=controlled_validation_failure`
  caps the score on `attempt == 1` so the agent is forced into retry.
  No I/O failure, no fake exception, no harness contamination.
- Topics: `asyncio advanced patterns` (tactical positive control) and
  `python OOP design patterns` (realistic stress topic).
- 4 subprocess runs total, 2 topics × 2 arms.

## Harness sanity (prerequisite)

| Check                             | Result |
|-----------------------------------|--------|
| All subprocess `exit_code == 0`   | PASS   |
| Zero live DDGS/Brave/Playwright   | PASS   |
| Cached MAP and AGGREGATE hits     | PASS   |
| No contamination flag             | PASS   |
| Stress injection observed in all  | PASS   |

The infrastructure was clean. Whatever the cognitive layer did or did
not do, it did so without external interference.

## Per-topic comparative signal

| topic                       | arm     | mood_min | crossed -0.3 | wb_max_abs | wb_nonzero | retry_attempts |
|-----------------------------|---------|---------:|--------------|-----------:|------------|---------------:|
| asyncio advanced patterns   | ARM_OFF |    -0.29 | no           |        0.0 | no         |              3 |
| asyncio advanced patterns   | ARM_ON  |    -0.29 | no           |        0.0 | no         |              5 |
| python OOP design patterns  | ARM_OFF |   -0.325 | YES          |        0.0 | no         |              5 |
| python OOP design patterns  | ARM_ON  |    -0.36 | YES          |        0.0 | no         |              5 |

Raw mood traces:

- `OOP ARM_ON`:   `[-0.36, -0.36, +0.14]`
- `OOP ARM_OFF`:  `[-0.325, -0.325]`
- `asyncio ARM_ON`:  `[-0.29, -0.29]`
- `asyncio ARM_OFF`: `[-0.29, -0.29]`

## Qualitative signals (weak, N=2 topics)

These are too small for any claim, but they are direction-coherent
with the GWT/MoodCoupling design:

- `OOP ARM_ON` reaches a deeper minimum than `OOP ARM_OFF` (-0.36 vs
  -0.325), consistent with MoodCoupling amplifying frustration when
  active.
- `OOP ARM_ON` produces a third mood sample at +0.14 (focused,
  recovery), `OOP ARM_OFF` does not. ARM_ON's compute loop ran one
  extra time, and that extra computation showed recovery.
- `asyncio ARM_ON` issued 5 retry attempts vs `ARM_OFF` 3, suggesting
  more persistence under controlled stress.

These are hints, not evidence. The hard verdict is the
`workspace_bias = 0.0` row across all four arms.

## Why workspace_bias is 0.0 (mechanism)

`MoodWorkspaceCoupling.get_bias()` returns the accumulator state at
the moment `MoodEngine.compute()` is called. In a single-cycle run,
that state is read at cycle start (always 0.0 on first cycle) and the
accumulator is only mutated *after* cycle work. The benchmark process
exits before another `compute()` can read the new value.

This is consistent with the precautionary docstring added in commit
`9d45efb`:

> workspace_bias may remain 0.0 during easy benchmark runs where
> topics certify without post-failure workspace cycles. ... A zero
> workspace_bias in natural runs is therefore not evidence that the
> GWT layer is broken; it usually means the benchmark did not enter
> the stress/retry regime where the coupling is designed to activate.

D2.1B added stress and retry. The remaining missing piece is *time*
(a second cycle in which the accumulated bias is observable).

## Conclusion

D2.1B does not falsify GWT/Mood coupling. It falsifies the adequacy
of a single-topic / single-cycle protocol for detecting an inter-topic
coupling effect.

## Next protocol: D2.1C

D2.1C must keep two consecutive topics inside the **same subprocess**
so the bias accumulated after Topic 1's `drain_session_winners()` is
read by Topic 2's `MoodEngine.compute()`.

Design sketch:

- `Topic 1` (stress inducer): `python OOP design patterns` —
  already shows mood crossing -0.3 under stress injection.
- `Topic 2` (bias observer): `asyncio advanced patterns` —
  more stable, suitable for reading the accumulated bias clearly.
- Arms: ARM_OFF (`no_l3=True`) vs ARM_ON (`no_l3=False`), with stress
  injection on Topic 1 in both arms.
- Subprocess command runs `night_runner.py --cycles 2` with the topic
  sequence forced (or via a small wrapper that calls the runner twice
  inside one Python process).
- Reads `mood_history.jsonl` per arm and looks for `workspace_bias`
  becoming non-zero after Topic 1, observable in Topic 2 mood samples
  in ARM_ON, while staying near-zero in ARM_OFF.

D2.1C verdict criteria (draft):

- `PASS_STRONG`: ARM_ON Topic 2 has `workspace_bias != 0`,
  ARM_OFF Topic 2 stays near-zero, harness clean.
- `PASS_WEAK`: ARM_ON has non-zero bias but no behavioral metric
  difference.
- `FAIL`: ARM_ON Topic 2 bias still zero after sequential exposure.
- `CONTAMINATED`: live calls, cache mismatch, subprocess error,
  stress injection missing.

D2.1C will only test whether the coupling is *observable*, not whether
it improves outcomes. Outcome causality remains a later milestone.

---

*Run completed 2026-05-05. Files: `backend/d2_1b_benchmark.py`,
`backend/d2_1b_analyze.py`, `backend/study_phases.py` stress hook
(env-gated, default off). Runtime artifacts under
`shard_workspace/d2_1b_runs/` are out of repo intentionally; they
remain locally for inspection.*
