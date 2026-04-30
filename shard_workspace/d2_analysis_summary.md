# D2 Frustration Benchmark — Post-hoc Analysis (D2.0)

**Verdict: `INCONCLUSIVE_HARNESS`**

> D2.0 shows progressive degradation across pairs affecting both arms. The run also contains 46 LLM fallback events and 18 HTTP-level service/search errors. This is enough external instability to invalidate causal interpretation of GWT_ON vs GWT_OFF, even though most [LLM_ROUTER] log markers were normal routing traces.

## 1. Performance summary

- ARM_A (GWT_ON):  cert=11.1%  score=0.84
- ARM_B (GWT_OFF): cert=11.1%  score=1.58
- Delta:           cert=+0.0pp  score=-0.74
- Trend ARM_A cert by pair: [0.3333, 0.0, 0.0]
- Trend ARM_B cert by pair: [0.3333, 0.0, 0.0]

> WARNING: progressive pair degradation detected. D2.0 cannot support H1/H0.

## 2. Harness markers (3 categories)

### NORMAL ROUTER ACTIVITY
- `[LLM_ROUTER]` markers: 677 (routine traces, NOT errors)

### ANOMALOUS LLM ACTIVITY
- fallback / provider-switch events: 46
- timeouts: 0
- circuit breakers / providers exhausted: 0

### ANOMALOUS SOURCE/HTTP ACTIVITY
- HTTP 429 (Brave Search rate-limit): 12
- HTTP 503 (provider/service): 0
- HTTP 502: 3
- HTTP 500 (approximate count): 3

**Total anomalous external-service events: 61**

## 3. Mechanism check (mood + workspace_bias)

### pair1_arm_a
- n=7  mood: min=-0.255 max=+0.280 mean=-0.169 std=0.198
- below -0.3: 0.0%   above +0.3: 0.0%   dead zone: 100.0%
- workspace_bias mean=+0.0000  non-zero pct=0.0%
- labels: {'strained': 6, 'focused': 1}
- interpretation: Stress regime not reached (mood never crossed -0.3).

### pair1_arm_b
- n=7  mood: min=-0.255 max=+0.280 mean=-0.169 std=0.198
- below -0.3: 0.0%   above +0.3: 0.0%   dead zone: 100.0%
- workspace_bias mean=+0.0000  non-zero pct=0.0%
- labels: {'strained': 6, 'focused': 1}
- interpretation: Stress regime not reached (mood never crossed -0.3).

### pair2_arm_a
- n=7  mood: min=-0.290 max=+0.280 mean=-0.179 std=0.204
- below -0.3: 0.0%   above +0.3: 0.0%   dead zone: 100.0%
- workspace_bias mean=+0.0000  non-zero pct=0.0%
- labels: {'strained': 6, 'focused': 1}
- interpretation: Stress regime not reached (mood never crossed -0.3).

### pair2_arm_b
- n=7  mood: min=-0.290 max=+0.280 mean=-0.179 std=0.204
- below -0.3: 0.0%   above +0.3: 0.0%   dead zone: 100.0%
- workspace_bias mean=+0.0000  non-zero pct=0.0%
- labels: {'strained': 6, 'focused': 1}
- interpretation: Stress regime not reached (mood never crossed -0.3).

### pair3_arm_a
- n=7  mood: min=-0.290 max=+0.280 mean=-0.179 std=0.204
- below -0.3: 0.0%   above +0.3: 0.0%   dead zone: 100.0%
- workspace_bias mean=+0.0000  non-zero pct=0.0%
- labels: {'strained': 6, 'focused': 1}
- interpretation: Stress regime not reached (mood never crossed -0.3).

### pair3_arm_b
- n=7  mood: min=-0.290 max=+0.280 mean=-0.179 std=0.204
- below -0.3: 0.0%   above +0.3: 0.0%   dead zone: 100.0%
- workspace_bias mean=+0.0000  non-zero pct=0.0%
- labels: {'strained': 6, 'focused': 1}
- interpretation: Stress regime not reached (mood never crossed -0.3).

## 4. Recovery dynamics (SERR / SSR / TNA)

- SERR: `UNAVAILABLE`
- SSR:  `UNAVAILABLE`
- TNA:  `UNAVAILABLE`

> Per-attempt error_signature and strategy_used are present in study_phases / cycle_data at runtime but NOT serialized into d2_frustration_results.json. To compute SERR/SSR/TNA reliably, the benchmark schema must be extended OR benchmark_episodes.json must be cross-correlated with run timestamps. Marked UNAVAILABLE to avoid coercing missing data into 'no change'.

## 5. Harness risks found (static review of d2_frustration_benchmark.py)

- [OK] Arm differentiation correct: ARM_A no_l3=False, ARM_B no_l3=True; use_affective_layer=True for both.
- [OK] Snapshot/restore covers shard_memory/ recursively (filesystem level).
- [RISK] RISK: filesystem restore alone does NOT reset in-process state. ChromaDB clients, SQLite singletons, FeedbackField, MoodEngine, CognitionCore singletons, LLM router cache, strategy_memory in-memory may persist across arms IF the same Python process runs both arms. Current design exits process between arms (good), but only one arm per invocation. Re-running the script reuses fresh interpreter — OK.
- [OK] mood_history.jsonl is moved aside per (pair, arm) — clean trajectory per arm.
- [RISK] RISK: external services (Groq/Gemini/Claude routing, Brave Search) introduce non-deterministic noise. Current run shows 52 fallback events and 21 HTTP-level errors. No abort threshold implemented — a single bad slot can poison both arms differently.
- [RISK] Topic order is fixed across arms. If first topic is consistently hardest, it primes mood for the rest. Consider rotating order or seeding shuffles.

## 6. Recommended D2.1 protocol

**Single-pair diagnostic, subprocess isolation, abort thresholds.**

```
D2.1 protocol:
  1. restore baseline snapshot
  2. spawn subprocess for ARM_A; let it exit
  3. restore baseline snapshot
  4. spawn subprocess for ARM_B; let it exit
  5. collect logs + mood history per arm
  6. compare

Reduce surface area:
  - 1 hard topic + 1 medium topic (not 3)
  - lower API budget per arm
  - log provider/model per attempt
  - cache or freeze MAP-phase sources to avoid Brave 429

Abort thresholds (per arm):
  - LLM fallback events > 10  -> mark arm contaminated, abort
  - HTTP 4xx/5xx errors  > 3  -> mark arm contaminated, abort
  - or: fallback_rate > 5% of LLM calls -> contaminated

Do NOT run multi-pair long benchmarks until single-pair is stable.
```
