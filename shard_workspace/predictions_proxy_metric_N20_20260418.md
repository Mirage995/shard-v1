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
