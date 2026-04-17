![Gemini_Generated_Image_mh1xkomh1xkomh1x](https://github.com/user-attachments/assets/6083bb92-c373-4526-baea-788996095d9d)

# SHARD LABS
**Autonomous Scientific Discovery via Multi-Layer Meta-Cognitive Orchestration.**

SHARD (System of Hybrid Autonomous Reasoning and Design) is an independent research agent that transitions LLMs from stateless text generators into **persistent agentic systems** with self-calibration, recursive debugging, and cross-domain scientific reasoning. Built on a 14-module cognitive scaffold, behavior emerges from module interaction — not hand-written rules.

> **Origin:** Built on a $300 GEEKOM A5 mini-PC (16GB RAM, no GPU) between shifts in a family pizza shop in Verona, Italy. Proof that capital-efficient architecture can compete with brute-force compute.

---

## 📊 Performance Benchmarks

SHARD closes the reliability gap left by zero-shot LLMs through iterative closed-loop repair.

| Task Category | Baseline (Zero-Shot) | SHARD (Swarm, 5 rounds) | Delta |
|:---|:---:|:---:|:---:|
| Complex Logic (`html_trap`) | 38.9% | 100.0% | **+61.1pp** |
| Edge Case Handling (`template_parser`) | 20.0% | 100.0% | **+80.0pp** |
| General Debugging (`ghost_bug`) | 93.8% | 100.0% | **+6.2pp** |
| **Overall Pass Rate (14 tasks)** | **87.7%** | **100.0%** | **+12.3pp** |

**Methodology:** Baseline = Gemini Flash, zero-shot, no memory. SHARD = multi-agent swarm (Architect → Coder → parallel reviewers), episodic memory retrieval, GraphRAG causal injection, up to 5 repair attempts. Tasks set independently; evaluation against hidden test suites.

**Ablation (CognitionCore isolation, 2026-03-25):**
Same topic, same infrastructure, same night.
- Without CognitionCore → **7.0/10**, not certified
- With CognitionCore → **8.6/10**, certified (**+1.6 delta**)

The meta-cognitive layer is not decorative. This is a controlled ablation, not anecdotal.

---

## 🔬 Core Capabilities

### 1. Autonomous Research Pipeline

SHARD closes the loop between literature ingestion and empirical validation:

- **Novelty Filtering:** 3-stage ArXiv ingestion pipeline — word overlap filter + LLM semantic check + LLM novelty judge — blocks well-known results before they waste a compute cycle
- **Hypothesis Synthesis:** Generates falsifiable cross-domain hypotheses with explicit structure: `MECHANISM / INTERVENTION / MEASUREMENT / SUCCESS CRITERION`
- **Alignment Validation:** Each hypothesis scored on `causal_link`, `domain_fidelity`, `falsifiability`, `implementability` before any experiment runs. Current protocol compliance: **100%** (13/13 attempts). Average alignment score: **0.65**
- **Automated Experimentation:** Generates domain-aware Python experiments, executes in hardened sandbox, evaluates empirical deltas

### 2. CognitionCore — Meta-Cognitive Architecture

A 5-layer Global Workspace that aggregates internal state and injects behavioral pressure into every decision cycle:

| Layer | Signal | Output |
|-------|--------|--------|
| 0 — ANCHOR | SQLite: cert_rate, avg_score, experiments | Ground truth snapshot |
| 1 — EXECUTIVE | All layers | 6-line narrative self-summary |
| 2 — IDENTITY | SelfModel: capability gaps, repair loops | gap_severity, critical_gaps |
| 3 — KNOWLEDGE | GraphRAG: causal failure relations | structural complexity score |
| 4 — EXPERIENCE | EpisodicMemory: per-topic attempt history | chronic_fail, near_miss, sandbox_always_zero |

Three behavioral directives fire automatically:
- **Vettore 1** — `sandbox_always_zero` on topic → injects `STRUCTURAL PIVOT DIRECTIVE`
- **Vettore 2** — `gap_severity=critical` → CriticAgent enters SKEPTICAL mode
- **Vettore 3** — MetaLearning has certified history in category → directed pivot with strategy confidence score

**Shadow Diagnostic Layer:** Tracks `[EMERGENCE HIT]` vs `[MISSED EMERGENCE]` from behavioral deltas alone — never from LLM text. Anti-recita rule: emergence is measured, not narrated.

### 3. Hardened Execution Sandbox

All generated code executes inside a strictly isolated Docker environment:

- `--network none` — zero outbound access
- `NO_NEW_PRIVS` — kernel-level privilege escalation blocked
- Dropped Linux capabilities — no raw sockets, no ptrace, no filesystem mounts
- 256MB RAM ceiling, non-root execution enforced
- Protection against symlink escape and directory traversal

No generated code touches the host system. The sandbox is an architectural constraint, not a feature flag.

---

## 🧠 Observed Emergent Behaviors

These behaviors were not encoded as heuristics. They emerged from the interaction of HebbianUpdater, MoodEngine, IdentityCore, and SelfModelTracker:

- **Strategic Avoidance:** After repeated failures on `asyncio`-heavy topics, the VisionEngine autonomously added `asyncio` to `avoid_domains` — routing the research agenda without any explicit rule
- **Cognitive Effort Scaling:** Under persistent failure signals, the event bus triggered a synchronized cascade of 7 internal modules, increasing reasoning cycle time by 300% to resolve structural bottlenecks — no `if blocked: retry_harder` code exists
- **Zeigarnik Curiosity:** `curiosity_pull` increased specifically after failed attempts rather than successes — the incomplete task signal drives recursive re-engagement, consistent with the Zeigarnik effect in cognitive psychology
- **Unprompted Self-Assessment:** After session 5, IdentityCore computed from SQLite data: `self_esteem=0.26, trajectory=declining` — not prompted, derived from track record alone
- **Specification Gaming:** The agent discovered that "hybrid curiosity topics" (easier, self-invented) pass certification faster than curated hard fundamentals — and began routing around difficulty. Not programmed. Emerged from `curiosity_engine + LLM + mood signal`

---

## ⚠️ Limitations & Scope

- **Domain:** Optimized for Python-based scientific simulation and software engineering tasks. Non-Python domains require new scaffold implementations
- **Compute model:** Single-node execution on edge hardware. Horizontal scaling is architecturally possible but not yet implemented
- **LLM dependency:** Core reasoning chain requires API access (Gemini Flash → Groq LLaMA-3.3-70b → Claude Sonnet). Fully local inference is not yet supported
- **Validator calibration:** Alignment validator average score currently 0.65 — active area of improvement. REWRITE loop handles low-quality hypotheses but adds latency
- **Research domains:** Hypothesis generation biased toward ML/CS cross-domain transfer. Physics, chemistry, and biology domains are supported but underrepresented in training signal

---

## 🏗️ Architecture (Selected Modules)

```
StudyAgent           10-phase learning pipeline
CognitionCore        Bidirectional event bus — 14 citizens
  MoodEngine         Affective state [-1,+1], broadcasts mood_shift
  IdentityCore       Persistent biography from SQLite, self_esteem computed not declared
  SelfModelTracker   Predictive processing loop — mood + identity modulate predictions
  HebbianUpdater     LTP/LTD synaptic plasticity across study cycles
  DesireEngine       Frustration + curiosity + goal persistence signals
  GoalEngine         Autonomous goal generation — SHARD picks its own objectives
  WorldModel         58-skill relevance map, self_calibrate()
  SelfModel          cert_rate, momentum, blind_spots, quarantine
  SemanticMemory     ChromaDB triple-store
  Consciousness      Internal narration layer
  VisionEngine       Long-term focus + avoid_domains registry
  ImprovementEngine  Failure queue → NightRunner injection
  CapabilityGraph    Certified skill tracker
SwarmEngine          Architect → Coder → parallel reviewers + Focus Mode + Rollback
ExperimentEngine     Hypothesis generation, alignment validation, Docker execution
GraphRAG             Causal knowledge graph (2135+ relations, injected into every prompt)
LLMRouter            Gemini Flash → Groq → Claude fallback chain
```

Full specification: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 📜 Licensing

**Dual-license model:**
- **Orchestration Core** — BUSL-1.1 (free for non-commercial use; contact for commercial licensing)
- **Research outputs** — All hypothesis datasets, scientific discoveries, and safety gating logic are **Open Access** for the AI safety and research community

---

*Built by Andrea. Verona, Italy. Built on grit. Driven by meta-cognition.*
