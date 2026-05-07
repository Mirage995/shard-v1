# Research Engine Epistemic Hardening Checkpoint

**Date:** 2026-05-07
**Status:** Checkpoint — all safeguards committed and tested

---

## 1. Executive Summary

This block does not increase the ambition of the Research Engine. It reduces epistemic risk.

Before these changes, SHARD's research pipeline had five latent failure modes that would silently degrade the quality of scientific output without any visible error:

- **Auto-confirmation:** the antagonist reviewer, sharing the same LLM priors as the generator, almost always issued VALID without genuine adversarial pressure.
- **Internal duplication:** hypotheses already in the DB could be regenerated repeatedly; SKIPPED_KNOWN was defined in the code but never actually written.
- **Sandbox over-weighting:** local Docker sandbox results were implicitly treated as equivalent to GPU-replicated or externally validated results in the GraphRAG knowledge graph.
- **Antagonist rubber stamp:** the previous text-format antagonist response had no structural requirement for alternative mechanisms, confounds, or sufficient confidence — making it trivially bypassed.
- **Ungoverned GPU queue:** KAGGLE_READY hypotheses were queued with no budget awareness, no dispatch guard, and no estimation of resource cost.

These changes close those gaps without touching the core science loop.

---

## 2. Premortem Risks Addressed

| Failure Mode | Risk | Safeguard Implemented |
|---|---|---|
| **F3** Antagonist rubber stamp | Same-LLM reviewer approves its own output unconditionally | Structured JSON antagonist + `normalize_antagonist_review()` gates |
| **F4** GraphRAG noise accumulation | Unverified sandbox results enter the knowledge graph at full confidence | Provenance schema + tier-based GraphRAG weighting |
| **F5** Feedback loop / re-discovery | SHARD re-generates hypotheses it already confirmed or refuted | DB-backed dedup gate + SKIPPED_KNOWN actually written |
| **F6** Sandbox does not generalize | Local synthetic results treated as strong scientific validation | `validation_tier` = `sandbox_replicated` → `verified_provisional`, weight 0.35 |
| **F7** No budget awareness | GPU-hours consumed without priority ordering or quota enforcement | Kaggle quota guard with ledger, `check_quota`, `try_enqueue`, `can_dispatch` |

---

## 3. Implemented Safeguards

### 3.1 Provenance Schema

Added three columns to `research_hypotheses` (migration-safe, idempotent `ALTER TABLE`):

| Column | Meaning | Default |
|---|---|---|
| `execution_backend` | Where the experiment ran | `local_sandbox` |
| `data_provenance` | What data was used | `synthetic` |
| `validation_tier` | How strong the validation is | `sandbox_replicated` |
| `manual_backfill` | Set by human retroactively | `0` |

**Backfill applied:**
- Hypothesis #14 (ANV+OGD, Split-MNIST 2-task, Kaggle GPU run): `kaggle / public_benchmark / gpu_replicated / manual_backfill=true`
- All other prior CONFIRMED hypotheses: honest defaults `local_sandbox / synthetic / sandbox_replicated`

Helper: `experiment_store.set_provenance(id, backend, provenance, tier)` for future manual backfills.

---

### 3.2 GraphRAG Tier Weighting

`graph_rag._VALIDATION_TIER_WEIGHT` maps each tier to a `(confidence, verified_status)` pair used when inserting relations into the knowledge graph:

| Tier | Confidence | Status |
|---|---|---|
| `code_runs` | 0.20 | `verified_provisional` |
| `sandbox_replicated` | 0.35 | `verified_provisional` |
| `gpu_replicated` | 0.75 | `verified` |
| `benchmark_validated` | 0.85 | `verified` |
| `external_replicated` | 0.90 | `verified` |

`insert_verified_relation()` applies this override automatically when `validation_tier` is supplied. Prior sandbox results in the graph retain their stored confidence (not retroactively downgraded); new inserts are weighted correctly from now on.

---

### 3.3 Antagonist Structured Gate

`_antagonist_review()` in `study_agent.py` now requires a structured JSON response with eight fields:

```
verdict, confidence, alternative_mechanism, confounds,
missing_controls, reason, corrected_code, review_quality
```

`normalize_antagonist_review()` in `experiment_phases.py` applies five post-processing gates:

| Gate | Trigger | Result |
|---|---|---|
| G1 | Malformed / missing `verdict` | `INVALID_CORRECTABLE` + `INVALID_FORMAT` |
| G2 | Fatal keyword in `missing_controls` (hardcoded, data leakage, …) | `INVALID_FATAL` |
| G3 | `VALID` with `confidence < 0.70` | `INVALID_CORRECTABLE` |
| G4 | `VALID` with empty `alternative_mechanism` | `INVALID_CORRECTABLE` |
| G5 | `VALID` with empty `confounds` | `INVALID_CORRECTABLE` |

Every gate application is logged as `[ANTAGONIST_GATE]` with 8 structured fields. On error, the fallback sets `_parse_error: True` (fails to `INVALID_CORRECTABLE`, not to a permissive VALID).

---

### 3.4 DB-Backed Dedup Gate

`_dedup_check_against_rows()` in `study_agent.py` compares a new hypothesis against all CONFIRMED/REFUTED/INCONCLUSIVE rows using Python `difflib.SequenceMatcher`. Two thresholds:

| Ratio | Action |
|---|---|
| `>= 0.82` (hard duplicate) | `SKIPPED_KNOWN` written to DB with 6-field diagnostic metadata; retry synthesis with `[DB DUPLICATE BLOCK]` constraint |
| `0.70–0.82` (suspicious) | Retry synthesis with `[DB SIMILARITY WARNING]` constraint; no immediate DB write |
| Same domain pair, different statement | Warning log only; pipeline proceeds |
| `< 0.70` | No action; hypothesis proceeds normally |

**SKIPPED_KNOWN diagnostic metadata** (stored in `experiment_result`):
```json
{
  "skip_reason": "DUPLICATE_CONFIRMED",
  "matched_hypothesis_id": 1,
  "similarity_ratio": 0.97,
  "matched_status": "CONFIRMED",
  "matched_statement": "...",
  "duplicate_check_source": "db_sequence_matcher"
}
```

For REFUTED duplicates, `reason` includes: *"a future variant is admissible only if it declares a strong novelty_delta (different mechanism, dataset, or regime)"*.

---

### 3.5 Smoke Test Checkpoint

`tests/smoke_research_engine.py` verifies all five gate integration points without real LLM calls, Docker, or GPU dispatch:

| Checkpoint | What is verified |
|---|---|
| CP1 NOVELTY_EXTERNAL | arxiv word-overlap fast-path + LLM NOVEL/KNOWN response |
| CP2 DB_DEDUP | Hard duplicate → SKIPPED_KNOWN; novel → passes; REFUTED → novelty_delta note |
| CP3 ANTAGONIST_GATE | G4 forces INVALID_CORRECTABLE; 8-field log structure confirmed |
| CP4 GRAPHRAG_PROVENANCE | All 5 tiers present with correct weights; tier override applied by `insert_verified_relation` |
| CP5 NO_GPU_DISPATCH | Synthetic spec → `requires_real_world_data=False`; fMRI/clinical → KAGGLE_READY routing; test DB has 0 GPU rows |

---

### 3.6 Kaggle Quota Guard

`backend/kaggle_quota.py` treats 28 free Kaggle GPU-hours as a scientific budget. Before any KAGGLE_READY entry enters the dispatch queue:

**Config (env vars, safe defaults):**

| Variable | Default | Meaning |
|---|---|---|
| `KAGGLE_GPU_HOURS_AVAILABLE` | `28` | Total free hours remaining |
| `KAGGLE_MAX_HOURS_PER_RUN` | `2` | Hard cap per individual run |
| `KAGGLE_DISPATCH_ENABLED` | `false` | Auto-dispatch disabled by default |
| `KAGGLE_REQUIRE_MANUAL_APPROVAL` | `true` | Manual go-ahead required |

**Ledger table** `kaggle_quota_ledger` (persistent in `shard.db`): `run_id`, `hypothesis_id`, `estimated_gpu_hours`, `actual_gpu_hours`, `status`, `created_at`, `completed_at`, `backend`, `validation_tier_target`, `validation_goal`, `priority_score`.

**`try_enqueue()` logic:**
1. Estimate GPU hours from hypothesis content (light 0.5h / medium 1.0h / heavy 1.5h, capped at `KAGGLE_MAX_HOURS_PER_RUN`)
2. If `estimated > max_per_run`: block, log `KAGGLE_QUOTA_EXCEEDED`
3. If `pending + estimated > available`: block, log `KAGGLE_QUOTA_EXCEEDED`
4. Otherwise: insert PENDING row into ledger

The underlying `research_hypotheses` row is **always** stored as KAGGLE_READY — quota only gates the dispatch queue, not the hypothesis record.

**Dispatch control:** `can_dispatch()` returns `True` only when **both** `KAGGLE_DISPATCH_ENABLED=true` AND `KAGGLE_REQUIRE_MANUAL_APPROVAL=false`. With defaults, dispatch is always blocked. Modal/cloud paid remains disabled and unchanged.

---

## 4. Current Epistemic Policy

| Claim | Basis |
|---|---|
| **Not scientific validation** | `sandbox_replicated` — local Docker, synthetic data — yields `verified_provisional` at weight 0.35. Suitable for initial filtering only. |
| **Stronger, not conclusive** | `gpu_replicated` — real GPU, public benchmark — yields `verified` at weight 0.75. Meaningful evidence, but not yet external replication. |
| **Strongest tier available** | `external_replicated` — independent group replicates the result — yields `verified` at weight 0.90. This is the threshold for treating a result as robust. |
| **Internal novelty** | `SKIPPED_KNOWN` prevents SHARD from re-discovering its own prior results and inflating internal confirmation counts. |
| **VALID antagonist requires** | Alternative mechanism explaining the result, at least one named confound, confidence ≥ 0.70, no fatal control keywords. Failing any condition forces INVALID_CORRECTABLE or INVALID_FATAL. |

---

## 5. Current Limitations

These limitations are acknowledged honestly. They do not invalidate the implemented safeguards, but they set the ceiling on what the system can claim:

1. **Dedup is lexical, not semantic.** `SequenceMatcher` catches near-verbatim duplicates. A hypothesis that restates the same claim with different terminology will pass. Semantic embedding dedup (e.g., ChromaDB cosine similarity gate) remains future work.

2. **arXiv novelty check can fail silently.** If arXiv is unavailable, `_check_hypothesis_novelty` falls back to the LLM Stage 2 judge without external evidence. The system defaults to NOVEL on error — intentional (fail open) but means network outages weaken the novelty filter.

3. **Antagonist is still an LLM, not a peer reviewer.** The gate structure makes rubber-stamping harder, but cannot prevent a well-formed confident VALID verdict on a flawed experiment. The system has no access to actual domain experts.

4. **Kaggle quota manages the queue, not execution.** `try_enqueue` gates ledger insertion. The actual execution of a Kaggle kernel, its real runtime, and result ingestion into SHARD are not yet automated end-to-end. Human operator remains in the loop.

5. **Hypothesis #14 is not benchmark-validated.** It is a GPU-replicated candidate (Split-MNIST 2-task, classes 0–4 vs 5–9, Kaggle run). It has not been tested against the full 5-task protocol or the Split-CIFAR benchmark suite, nor has it been replicated by an independent group. It is a promising result, not a confirmed finding.

6. **No guarantee of genuine scientific novelty.** SHARD's novelty filter (arXiv + LLM judge) cannot access paywalled literature, conference proceedings, or unpublished preprints. A result marked NOVEL by SHARD may still be known to domain experts.

---

## 6. Recommended Next Experiment: D14-B Validation Pack

**Hypothesis #14:** ANV+OGD reduces catastrophic forgetting in continual learning compared to OGD-only, on Split-MNIST.

**Goal:** Determine whether the Kaggle-observed advantage (ANV+OGD beats OGD-only) is stable across seeds and representative enough to promote to `benchmark_validated`.

**Protocol:**

| Parameter | Value |
|---|---|
| Dataset | Split-MNIST, 5 tasks |
| Seeds | 5 (fixed: 0, 1, 2, 3, 4) |
| Conditions | Baseline SGD, ANV only, OGD only, ANV+OGD |
| Primary metric | `forgetting_magnitude` (mean ± std across seeds) |
| Secondary metrics | Signed BWT, final average accuracy |
| Reporting | Table: condition × metric, mean ± std, p-value (Wilcoxon) |

**Promotion gate:**
ANV+OGD must beat OGD-only on mean forgetting_magnitude **and** not materially degrade final average accuracy (threshold: ≤ 1.0 pp loss). If both conditions hold across all 5 seeds, promote to `validation_tier = benchmark_validated`.

**If the gate passes:** update Hypothesis #14 via `set_provenance(14, "kaggle", "public_benchmark", "benchmark_validated")` and re-run `insert_verified_relation` to upgrade the GraphRAG edge weight to 0.85.

---

## 7. Claim Discipline

**Do not claim:**
> "SHARD discovers scientific truth."

**Correct claim:**
> "SHARD generates, filters, tracks, and prioritizes plausible scientific hypotheses with explicit evidence provenance."

**For Hypothesis #14 specifically:**
> "Promising GPU-replicated candidate (Split-MNIST 2-task, Kaggle), not yet benchmark-validated. Requires D14-B replication pack (5-task) before promotion."

**For sandbox-only results:**
> "Code runs in local sandbox on synthetic data. Proof-of-mechanism only. Not generalizable without GPU replication on public benchmark."

These distinctions must be preserved in any external communication, report, or grant application that references SHARD's research output.

---

## 8. Verification

All safeguards are covered by automated tests. Current status as of this checkpoint:

| Test file | Tests | Status |
|---|---|---|
| `tests/test_antagonist_gates.py` | 6 | PASSED |
| `tests/test_hypothesis_dedup.py` | 6 | PASSED |
| `tests/test_kaggle_quota.py` | 19 | PASSED |
| `tests/smoke_research_engine.py` | 14 | PASSED |
| **Total** | **45** | **45/45** |

Run: `python -m pytest tests/test_antagonist_gates.py tests/test_hypothesis_dedup.py tests/test_kaggle_quota.py tests/smoke_research_engine.py -v`

---

## 9. Commits Included in This Block

| Hash | Message |
|---|---|
| `6a0ec33` | `feat(research): P0 provenance schema` |
| `13659c4` | `experiment(research): harden antagonist review gates` |
| `9b956a8` | `experiment(research): add db-backed hypothesis dedup gate` |
| `473705c` | `experiment(research): add kaggle quota guard` |
| *(this doc)* | `docs(research): document epistemic hardening checkpoint` |
