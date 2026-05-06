# D2.2C Decision Path Tracing

## Status

Tracing/documentation only.
No code changes.
No benchmark run.
No behavioral claim.

## Question

Il segnale GWT/Mood generato da `workspace_bias` entra davvero nei punti decisionali che controllano retry, recovery, certification, loop-risk e strategy shift?

## Finding summary

- Il segnale entra in MoodEngine, relational context e GWT diagnostics.
- Influenza probabilmente prompt/context in modo indiretto.
- Molti decision points operativi restano rule-based o score-based e non consumano direttamente `mood_score` o `workspace_bias`.
- Questo spiega perche D2.2A ha signal `4/4` e `mood_min` migliore, ma recovery/retry/cert/loop-risk invariati.

## Decision path map

| Decision point | File / function | Consumes mood/workspace_bias? | Influence type | Expected behavioral effect | Observed D2.2A result | Diagnosis |
|---|---|---|---|---|---|---|
| MoodEngine compute | `backend/mood_engine.py::MoodEngine.compute` | Yes. Reads `workspace_bias` and adds it to mood score. | DIRECT_CONTROL | Shift `mood_score`, mood label and behavior directives. | `mood_min_mean` improved in ARM_ON. | Signal reaches internal mood state. This is the strongest validated path. |
| relational_context / GWT proposal selection | `backend/cognition/cognition_core.py::relational_context`, `resolve_workspace`; `backend/cognition/workspace_arbiter.py::run_competition` | Yes. `mood_score` modulates workspace bids via ValenceField. | PROMPT_CONTEXT | Select different workspace winner/content under stress. | ARM_ON real signal `4/4`; `tensions` traces present. | GWT path activates and selects stress-relevant winner. This affects injected context, not final gates directly. |
| retry policy / retry loop | `backend/study_phases.py::CertifyRetryGroup.run`, `_retry_gap_fill` | Mostly no. Retry loop follows `ctx.attempt < MAX_RETRY` and `not ctx.certified`; retry prompt may include core context. | PROMPT_CONTEXT | Better retry content if prompt changes; retry count can change only if certification succeeds earlier. | `retries_count_mean` stayed `2 -> 2`. | Retry count is score/certification-gated, not directly mood-gated. Mood can alter retry prompt, but not retry policy itself. |
| strategy selection / strategy shift | `backend/study_phases.py::SandboxPhase.run`; `backend/study_agent.py::retrieve_strategy`; `backend/strategy_memory.py::query` | No direct `mood_score`/`workspace_bias` read in strategy retrieval. | NOT_CONSUMED | Could choose different past strategy if mood influenced ranking, but current ranking uses semantic similarity, success and recency. | `strategy_shift_detected` stayed true in both arms; repeated strategy unchanged. | Strategy retrieval is not directly coupled to mood. GWT may inject prompt context later, but strategy selector itself is unaffected. |
| reflection trigger | `backend/study_phases.py::CertifyRetryGroup.run`; critic/meta-critique path | No direct `workspace_bias` read. Trigger is attempt/score/gaps based. | NOT_CONSUMED | More reflection under stress if mood were consumed. | No operational separation in recovery/retry metrics. | Reflection/meta-critique is triggered by retry attempt and gaps, not by GWT/Mood signal. |
| memory retrieval / experience usage | `backend/study_phases.py::SynthesizePhase.run`; `backend/cognition/cognition_core.py::query_experience`; `backend/semantic_memory.py` | Mostly no direct `workspace_bias`; experience is queried from history/DB. | PROMPT_CONTEXT | Structural pivot or memory context if past failures exist. | No recovery/certification improvement. | Experience can affect synthesis prompt, but its trigger is historical failure pattern, not current GWT/Mood bias. |
| certification verdict | `backend/study_agent.py::phase_certify` | No. Uses score, synthesis, sandbox and benchmark gate. | NOT_CONSUMED | Certification changes only if score/sandbox/synthesis/pass_rate change. | `certification_rank_mean` stayed `0 -> 0`. | Certification path is explicitly score/verdict-based. Mood does not directly adjust threshold or verdict. |
| final_score / benchmark_score path | `backend/study_agent.py::phase_evaluate`, `phase_benchmark`; `backend/benchmark_runner.py` | No direct `mood_score`/`workspace_bias` read. | NOT_CONSUMED | Scores improve only if generated content/code improves. | `final_score_mean` did not improve in hardened rerun; `benchmark_score` stayed `UNAVAILABLE`. | Scoring is downstream of content quality, not directly coupled to mood signal. Benchmark score is unavailable because no reliable observer-cycle benchmark score is emitted/extracted. |
| loop_risk / repeated strategy logic | D2.2A analyzer proxy; strategy texts from observer logs | No direct runtime gate. Analyzer-derived proxy only. | DIAGNOSTIC_ONLY | Would change if retries, repeated strategy or recovery changed. | `loop_risk_proxy_mean` stayed `4 -> 4`; repeated strategy stayed `1 -> 1`. | This is currently an analyzer proxy, not a control mechanism. It cannot improve unless underlying retry/recovery/strategy behavior changes. |
| prompt policy / context construction | `backend/night_runner.py` mood compute + ContextArbiter block selection; `backend/context_arbiter.py::ContextArbiter.select` | Yes. Uses `mood_score`; MoodEngine directives can add mood hints and behavior directives. | PROMPT_CONTEXT | Different context blocks or behavior directive in prompt. | Mood improves; operational gates unchanged. | This is the main bridge from signal to behavior today, but it is indirect and LLM-mediated. |

## Key interpretation

D2.2A does not fail because the signal does not arrive. The signal arrives.

The limit is that the signal seems to affect internal state and prompt/context construction more than the hard operational gates that determine `retries_count`, `certification_verdict`, `loop_risk_proxy` and `recovery_success`.

In the current architecture, GWT/Mood has validated internal propagation and context-level influence. It has not yet been wired as a direct decision input for retry policy, reflection triggering, strategy selection, loop escape or certification.

## Most likely explanation for D2.2A PASS_WEAK

- `mood_min` improves because MoodEngine receives `workspace_bias`.
- `retries_count` does not change because retry policy does not seem to consume `mood_score` or `workspace_bias` directly.
- `loop_risk_proxy` does not change because it derives from retry/repeated-strategy proxy metrics.
- `certification_rank` does not change because certification remains score/verdict-based.
- `final_score` does not reliably improve because scoring is not directly coupled to the mood signal.
- `benchmark_score` remains `UNAVAILABLE` because a reliable observer-cycle benchmark score is not emitted or not extractable.

## Consequence

Before D2.2 full, choose one of three paths:

A. Leave GWT/Mood as context/prompt influence and run a broader benchmark.

B. Add controlled micro-gating in one operational decision point, such as retry policy or reflection trigger.

C. Improve benchmark/outcome instrumentation first, especially `benchmark_score` or an equivalent reliable outcome metric.

Path A risks repeating `PASS_WEAK`: signal and mood effect without clear outcome-level value.

Path B tests whether signal-to-decision coupling is the missing link.

Path C improves measurement, but may still not change behavior if decision gates do not consume the signal.

## Recommended next step

Do not run D2.2 full immediately.

Recommended next step: D2.2D Micro Decision Coupling, with one pre-registered micro-fix.

Preferred target:

- retry policy or reflection trigger;
- one small modifier, not an override;
- no broad retuning;
- no certification threshold change.

Conceptual example:

```text
if workspace_bias indicates stress/tensions and repeated failure detected:
    increase probability/priority of reflection or strategy shift
```

Then rerun the D2.2A micro protocol.

Success criteria:

- ARM_ON should show a difference in strategy shift, repeated strategy, retry quality or recovery metrics;
- improvement should not rely only on `mood_min`;
- ARM_OFF fallback bias must remain excluded from GWT signal.

## Forbidden claims

- Do not say "GWT improves SHARD performance".
- Do not say D2.2A demonstrated operational value.
- D2.2C only explains why internal signal has not yet translated into outcome-level metrics.

## Allowed claim

```text
D2.2C traces the calibrated GWT/Mood signal into internal mood/context pathways and identifies that several operational decision gates do not directly consume that signal yet.
```
