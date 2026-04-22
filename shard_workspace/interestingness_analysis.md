# Interestingness regression analysis
Date: 2026-04-20
Samples extracted from:
- VECCHIE (pre-6f3015f, before 2026-04-18 14:06): 16 files, alignment_log_20260416_* and alignment_log_20260417_*
- NUOVE (post-6f3015f): alignment_log_20260418_145930.jsonl (N=17 run)

## Data limitations (IMPORTANT — read before interpreting)

1. **hypothesis field truncated to 100 chars in ALL logs** — hardcoded `[:100]` in `_calib_append`
   (experiment_phases.py L688/L715). Neither old nor new logs contain the full hypothesis statement.

2. **minimum_experiment absent in ALL 73 VECCHIE** — this field was added in commit 5a90774
   (2026-04-18, same session as 6f3015f). Old logs predate the fix.

3. **No logs exist before 2026-04-16** — the SSJ29/SSJ30 JEPA era (2026-04-10/11) has no
   corresponding alignment_log files. The earliest log is alignment_log_20260416_142959.jsonl.
   Git history confirms no older alignment_log files were ever committed.

4. **Temporal split**: 6f3015f commit was 2026-04-18 14:06:00. Logs 20260418_140802 and
   20260418_141715 (14:08, 14:17) fall AFTER the commit and are excluded from VECCHIE.

Total hypothesis counts: 73 VECCHIE (16 files) + 17 NUOVE (1 file) = 90 total.

---

## Vecchie (pre-6f3015f)

### Hypothesis V1
**Statement (100 chars, truncated):**
Applying quaternionic differential geometry to the field of climate modeling can improve the accurac

**minimum_experiment:** NOT PRESENT (pre-logging-fix era)
**Source:** shard_workspace/experiments/alignment_log_20260416_185040.jsonl, line 4
**Date generated:** 2026-04-16T18:59:21
**domain_from:** Differential Geometry
**domain_to:** Climate Modeling
**final_verdict in log:** VALID (score 1.0, 0 rewrites, kaggle_feasible=True)

---

### Hypothesis V2
**Statement (100 chars, truncated):**
Applying techniques from psychophysics, such as just-noticeable difference models, to 3D mesh genera

**minimum_experiment:** NOT PRESENT (pre-logging-fix era)
**Source:** shard_workspace/experiments/alignment_log_20260417_170540.jsonl, line 1
**Date generated:** 2026-04-17T17:05:40
**domain_from:** Psychophysics
**domain_to:** 3D Mesh Generation
**final_verdict in log:** REWRITE_EXHAUSTED (score 0.625, 2 rewrites, kaggle_feasible=False)
**Issues logged:** "experiment does not specify how perceived quality is measured", "success criterion too vague"

---

### Hypothesis V3
**Statement (100 chars, truncated):**
Applying principles from quantum key distribution to the implementation of custom UDP protocols can

**minimum_experiment:** NOT PRESENT (pre-logging-fix era)
**Source:** shard_workspace/experiments/alignment_log_20260417_210523.jsonl, line 5
**Date generated:** 2026-04-17T21:17:34
**domain_from:** quantum physics
**domain_to:** computer networking
**final_verdict in log:** REWRITE_EXHAUSTED (score 0.6, 2 rewrites, kaggle_feasible=False)
**Issues logged:** "experiment does not specify how QKD principles are applied to UDP", "success criterion too vague"

---

## Nuove (post-6f3015f, run di oggi)

### Hypothesis N1
**Statement (100 chars, truncated):**
The application of the Gumbel-Softmax method to topology optimization of graded lattice structures c

**minimum_experiment (610 chars, complete):**
MECHANISM: The Gumbel-Softmax method reduces the computational cost of optimizing graded lattice structures by enabling the use of gradient-based optimizers. VARIABLE: V = computational_cost
INTERVENTION: Simulated as: generate a graded lattice structure with varying densities and optimize it using the Gumbel-Softmax method and a gradient-based optimizer, using numpy and scipy with a uniform distribution.
MEASUREMENT: Metric: V, computed as the time taken to optimize the structure.
SUCCESS CRITERION: V exceeds baseline by < 1000
CONTROL: Random seed fixed at 42; learning rate identical across conditions

**Source:** shard_workspace/experiments/alignment_log_20260418_145930.jsonl, record 4
**Date generated:** 2026-04-18T15:13:44
**domain_from:** Gumbel-Softmax Method
**domain_to:** Topology Optimization of Graded Lattice Structures

---

### Hypothesis N2
**Statement (100 chars, truncated):**
Applying derandomization techniques from computational complexity theory to the field of economics c

**minimum_experiment (406 chars, complete):**
MECHANISM: Derandomization techniques reduce the uncertainty in auction outcomes. VARIABLE: V = auction_efficiency
INTERVENTION: Technique vs baseline. Simulated as: generate auction_data using numpy.random with uniform distribution
MEASUREMENT: Metric: V, computed as revenue / optimal_revenue
SUCCESS CRITERION: V exceeds baseline by > 0.90
CONTROL: Random seed fixed; sample size equal across conditions

**Source:** shard_workspace/experiments/alignment_log_20260418_145930.jsonl, record 9
**Date generated:** 2026-04-18T15:26:30
**domain_from:** computational complexity
**domain_to:** economics

---

### Hypothesis N3
**Statement (100 chars, truncated):**
The integration of arbitrary polynomial chaos theory with deep artificial neural networks can improv

**minimum_experiment (462 chars, complete):**
MECHANISM: integration of arbitrary polynomial chaos theory with deep artificial neural networks reduces uncertainty in complex systems via improved representation of uncertainty INTERVENTION: compare aPC-DANN model with baseline DANN model on synthetic data generated using numpy/scipy MEASUREMENT: metric V, computed as the difference between the original and aPC-encoded signals SUCCESS CRITERION: aPC-DANN model exceeds baseline DANN model by >5% on metric V

**Source:** shard_workspace/experiments/alignment_log_20260418_145930.jsonl, record 15
**Date generated:** 2026-04-18T15:43:20
**domain_from:** Homogeneous Chaos Theory
**domain_to:** Deep Artificial Neural Networks

---

## Gate simulation on VECCHIE

NOTE: Eyeball evaluation only — no validator called. Based on logged text and known gate logic.
VECCHIE lack minimum_experiment — gates evaluated on hypothesis statement + logged issues only.

### V1 — quaternionic differential geometry → climate modeling
- **Formato:** LIKELY_FAIL — minimum_experiment absent; hypothesis statement ends mid-sentence at 100 chars; no VARIABLE binding, no 4-section structure present in log
- **DF_mechanism:** LIKELY_PASS — quaternionic differential operators could plausibly model atmospheric curvature dynamics; mechanism not obviously wrong
- **FA:** LIKELY_FAIL — no V defined, no SUCCESS CRITERION with numeric threshold; "can improve accuracy" is a proxy metric (forbidden by current rubric)
- **IM:** LIKELY_FAIL — quaternionic differential geometry simulation requires specialized math; not trivially feasible in 60s numpy/scipy sandbox without custom quaternion algebra code
- **CL:** LIKELY_FAIL — causal chain unspecified: which quaternionic property maps to which climate prediction mechanism via what process

### V2 — psychophysics JND models → 3D mesh generation
- **Formato:** LIKELY_FAIL — REWRITE_EXHAUSTED in original run; no minimum_experiment; existing issues confirm missing measurement spec
- **DF_mechanism:** LIKELY_PASS — JND (just-noticeable difference) thresholds have a plausible mechanism for adaptive mesh LOD; mechanism structurally sound
- **FA:** LIKELY_FAIL — "can improve robustness" without V definition; validator issues in log explicitly flagged missing measurement specification
- **IM:** LIKELY_PASS — mesh LOD simulation + JND scoring with synthetic geometry data is feasible in numpy in under 60s
- **CL:** LIKELY_FAIL — causal link between perceptual threshold model and mesh generation algorithm not formalized; validator flagged this in rewrites

### V3 — quantum key distribution → custom UDP protocols
- **Formato:** LIKELY_FAIL — REWRITE_EXHAUSTED; no minimum_experiment; issues confirm mechanism application unspecified
- **DF_mechanism:** FAIL — QKD relies on quantum states and entanglement; applying "principles" to classical UDP protocol design requires deep reinterpretation that the hypothesis does not specify; without a classical analog, DF_mechanism has no valid instantiation
- **FA:** LIKELY_FAIL — "can significantly improve" without V definition; no testable numeric threshold
- **IM:** FAIL — actual QKD simulation requires quantum computing libraries not available in standard sandbox; classical approximation would not test the stated mechanism
- **CL:** FAIL — no causal chain stated between quantum key distribution properties and UDP protocol improvement; validator issues in log confirm this

---

## Feature extraction

Scores are subjective estimates (1–5 scales) based on hypothesis statement text only.
**domain_pair_distance:** 1=same subfield, 5=completely different scientific domains
**vocab_obscurity:** count of terms a general-purpose reader would not know
**mechanism_ambiguity:** 1=fully specified with formula, 5=vague "X influences Y"
**implementation_feasibility:** 1=requires GPU/domain data, 5=trivial numpy sandbox

| Hypothesis | domain_dist | vocab_obscurity | mech_ambiguity | impl_feasibility |
|------------|-------------|-----------------|----------------|------------------|
| V1 (quat. geom → climate)    | 5 | 3 (quaternionic, differential geometry, climate modeling) | 4 | 2 |
| V2 (psychophysics → 3D mesh) | 4 | 2 (psychophysics, just-noticeable difference)            | 3 | 3 |
| V3 (QKD → UDP)               | 5 | 3 (quantum key distribution, UDP, cryptographic)         | 4 | 1 |
| N1 (Gumbel-Softmax → topology opt.) | 3 | 2 (Gumbel-Softmax, topology optimization, graded lattice) | 2 | 4 |
| N2 (derandomization → economics)    | 4 | 2 (derandomization, auction efficiency)                   | 3 | 4 |
| N3 (poly chaos → deep NNs)          | 4 | 3 (polynomial chaos, aPC, DANN, uncertainty quantification) | 3 | 3 |

---

## Analisi pattern (solo factual)

**Media domain_pair_distance:**
- Vecchie: (5 + 4 + 5) / 3 = **4.67**
- Nuove:   (3 + 4 + 4) / 3 = **3.67**
- Delta: −1.00

**Media vocab_obscurity:**
- Vecchie: (3 + 2 + 3) / 3 = **2.67**
- Nuove:   (2 + 2 + 3) / 3 = **2.33**
- Delta: −0.33

**Media mech_ambiguity:**
- Vecchie: (4 + 3 + 4) / 3 = **3.67**
- Nuove:   (2 + 3 + 3) / 3 = **2.67**
- Delta: −1.00

**Media impl_feasibility:**
- Vecchie: (2 + 3 + 1) / 3 = **2.00**
- Nuove:   (4 + 4 + 3) / 3 = **3.67**
- Delta: +1.67

**Quale gate avrebbe fatto fallire più vecchie:**
- IM (implementation feasibility): tutti e 3 i campioni VECCHIE mostrano LIKELY_FAIL o FAIL su questo gate (punteggi 2, 3, 1)
- FA (falsifiability con V binding): tutti e 3 LIKELY_FAIL per assenza di V e SUCCESS CRITERION numerico
- CL (causal link precision): V2 e V3 LIKELY_FAIL o FAIL; V1 LIKELY_FAIL
- Il gate IM avrebbe eliminato V3 con FAIL diretto, V1 con LIKELY_FAIL
- Il gate FA avrebbe eliminato tutti e 3 (in assenza di minimum_experiment strutturato)
