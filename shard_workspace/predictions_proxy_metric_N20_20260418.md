# Pre-registration: proxy_metric_gate N=20
**Date:** 2026-04-18  
**Commit at launch:** see tag `proxy_metric_gate_pre_N20`  
**Fix being tested:** proxy metric gate + MECHANISM TESTABILITY RULE (commit 6f3015f)

---

## Primary outcome

**FA (falsifiability)**  
- Baseline (run 233916, N=5 attempts=8): 0.613  
- Expected range: [0.68, 0.75]  
- Null hypothesis: FA not different from 0.613  
- Decision threshold: FA > 0.68 to reject null

## Secondary outcomes (regression monitoring)

| Metric | Baseline (run 233916) | Expected range | Max acceptable drop |
|---|---|---|---|
| VALID% | 80% (N=5, CI [37.6%, 96.4%]) | [65%, 85%] | −15pp |
| DF | 0.700 | [0.65, 0.75] | −0.05 |
| IM | 0.825 | [0.75, 0.85] | −0.05 |
| CL | 0.650 | [0.68, 0.72] | no drop expected — recovery |
| Coercions | 0 | 0 | any > 0 = investigate |
| Regressions | 0 | 0 | any > 0 = investigate |

## Decision rules (evaluated in order)

1. **Fix works → ship:** FA > 0.68 AND no secondary drops > max acceptable
2. **Inconclusive:** FA in [0.61, 0.68] → need N=40 or different gate design
3. **Fix backfired:** FA < 0.61 → revert commit 6f3015f
4. **Secondary regression:** any metric drops > 0.10 below run 233916 → investigate before shipping regardless of FA

## Stratification note

Pipeline does not support explicit domain stratification (`--force-domain` unavailable).  
Domain selection is random from the internal pool.  
**Post-run analysis required:** check if FA improvement is distributed across domains or concentrated in a subset. Use calibration report `domain_pairs` section.  
Known confound: if the 20 cycles happen to sample "easy" cross-domain pairs (ML→CS), VALID% may inflate independent of the fix. Domain distribution logged in calibration JSONL and checkable post-hoc.

## What is NOT being tested here

- Absolute quality of generated hypotheses (no ground truth)
- Whether the mechanism described is scientifically correct (out of scope for this gate)
- Whether IM=0.825 is stable or an artifact of N=5 (secondary concern, N=20 will clarify)

---

*Pre-registered before any results observed. Do not modify this file after the run starts.*

---

## AMENDMENT — 2026-04-18 (post qualitative inspection N=6, pre-run)

### Section 1 — Empirical findings from qualitative inspection

Qualitative inspection of H1-H6 from run 233916 revealed **two distinct problems**, not one:

- **IM** saturated at 0.95 across H2-H6. Not a bottleneck — ceiling effect, no fix needed.
- **FA** inconsistent but not systematically low: H2-H6 scored 0.7; H1 scored 0.6. FA inconsistency appears isolated to H1.
- **DF** systematically low (0.3–0.5) across H2-H6 with **identical penalty pattern** in validator issues: all penalized for synthetic/non-domain-specific data. This is a systematic confound, not noise.
- **H1 is a separate problem**: structural malformation (2× INTERVENTION sections, 2 metrics, no V chain). H1's FA=0.6 is correctly low for structural reasons, unrelated to the DF confound. Treat as separate ticket — do NOT conflate with the DF fix.

### Section 2 — Metric validity issue

The current `domain_fidelity` score **conflates two distinct properties**:

- **(a) Causal structure fidelity** — does the experiment instantiate the mechanism correctly?
- **(b) Data realism** — does the experiment use domain-appropriate data sources?

The CAPABILITY CONTRACT introduced in commit 6f3015f forces synthetic-only experiments. The validator then penalizes `domain_fidelity` because synthetic data "may not represent real-world distributions" — this is a **circular penalty**: the gate forces (b) = synthetic, then the validator lowers DF for it.

Consequence: **all historical DF scores are not directly comparable post-amendment**. The pre-registered DF baseline of 0.700 conflated both components and cannot be used as a valid comparison point for post-split DF_mechanism scores.

**Validator temperature = 0.25 → re-scoring is stochastic, not deterministic.** Re-scoring historical hypotheses would produce different scores on each run. Re-scoring strategy to be decided post-implementation.

### Section 3 — Fix scope and new baseline definition

Fix: **surgical DF split** in `_validate_experiment_alignment()`:

- `domain_fidelity_mechanism` (causal fidelity, weight 1.0) — the only score that matters for synthetic-forced experiments
- `domain_fidelity_data_realism` (data sourcing, weight 0.0 when synthetic forced)
- Composite: `domain_fidelity = df_mechanism × 1.0` when `synthetic_declared(min_exp)` is True

**Primary outcome FA is unchanged** — not affected by the DF split. The N=20 pre-registered FA > 0.68 threshold and decision rules remain valid.

**New DF baseline**: will be established from the first post-amendment run (N=20). Historical DF=0.700 is **retired as a comparison baseline** for domain_fidelity_mechanism.

*Amendment written before implementation. Implementation commit to follow immediately.*

---

## Launch conditions for N=20 with amended rubric

**Primary outcome: FA > 0.68 (unchanged)**
Rationale: FA measurement not affected by DF split.

**Secondary outcomes (MONITORING, not decision-binding):**
- `DF_mechanism`: no prior baseline. Report absolute value only.
- `DF_data_realism`: reported when synthetic=False; ignored when synthetic=True by design.
- `IM`, `CL`, `VALID%`: compared against run 233916 values, acknowledging those were pre-split measurements.

**Decision rules (UPDATED — replaces originals in §Decision rules above):**
1. FA > 0.68 AND IM not regressed > 0.10 → proxy_metric_gate ships
2. FA in [0.61, 0.68] → inconclusive, analyze per-hypothesis
3. FA < 0.61 → revert proxy_metric_gate
4. Any secondary metric collapse > 0.15 below run 233916 → investigate before shipping (may indicate new confound introduced by fix)

**Sample structure:** domain_pair logged per hypothesis for post-hoc stratification. No a-priori stratification available (no `--force-domain` support).

**Re-scoring strategy (decided 2026-04-18):**
Triple re-score on H1-H6 (18 validator calls, ~4-5 min) using new split rubric.
Purpose: establish `DF_mechanism` reference baseline with variance reduced by ~√3 vs single-score.
Output: `rescore_df_split_H1H6_20260418.json` — mean + std per hypothesis.
This is NOT a primary outcome — used only as sanity check that split removed the circular penalty.

*Launch conditions section added 2026-04-18 post-amendment, pre-run.*
