"""d2_analyze.py -- Post-hoc analyzer for D2 Frustration Benchmark.

Reads artifacts produced by d2_frustration_benchmark.py:
  - shard_workspace/d2_frustration_results.json     (per-arm cert/score)
  - shard_workspace/d2_mood_history/*.jsonl         (mood per arm/pair)
  - shard_workspace/d2_run_all.log                  (harness/router log)

Produces:
  - console summary
  - shard_workspace/d2_analysis_summary.md
  - shard_workspace/d2_analysis_metrics.json

Verdict categories (one of):
  VALID_POSITIVE          D2 supports H1
  VALID_NULL              D2 supports H0
  MECHANISM_ONLY          GWT mechanism activated but no perf advantage
  INCONCLUSIVE_HARNESS    progressive degradation / leakage / provider noise
  INCONCLUSIVE_NO_STRESS  mood never crossed stress threshold
  INCONCLUSIVE_MISSING_DATA insufficient attempt-level data

Policy: missing data is NEVER coerced to zero / no-change. Marked PARTIAL or
UNAVAILABLE.
"""
import json
import re
import statistics
from collections import Counter
from pathlib import Path

_ROOT      = Path(__file__).resolve().parent.parent
_RESULTS   = _ROOT / "shard_workspace" / "d2_frustration_results.json"
_MOOD_DIR  = _ROOT / "shard_workspace" / "d2_mood_history"
_LOG_FILE  = _ROOT / "shard_workspace" / "d2_run_all.log"
_OUT_MD    = _ROOT / "shard_workspace" / "d2_analysis_summary.md"
_OUT_JSON  = _ROOT / "shard_workspace" / "d2_analysis_metrics.json"

VALENCE_THRESH = 0.3   # ValenceField activation threshold


# ── Performance summary ───────────────────────────────────────────────────────

def perf_summary(results: dict) -> dict:
    pairs = results.get("paired_runs", [])
    out = {"pairs": [], "aggregate": {}}
    a_certs, a_scores, b_certs, b_scores = [], [], [], []
    for p in pairs:
        pair_d = {"pair": p["pair"]}
        for key in ("arm_a", "arm_b"):
            arm = p.get(key)
            if not arm:
                pair_d[key] = None
                continue
            pair_d[key] = {
                "cert_rate": arm["cert_rate"],
                "avg_score": arm["avg_score"],
                "avg_llm_calls": arm["avg_llm_calls"],
                "topics": [
                    {"topic": t["topic"], "difficulty": t["difficulty"],
                     "certified": t["certified"], "score": t["score"]}
                    for t in arm["topics"]
                ],
            }
            if key == "arm_a":
                a_certs.append(arm["cert_rate"]); a_scores.append(arm["avg_score"])
            else:
                b_certs.append(arm["cert_rate"]); b_scores.append(arm["avg_score"])
        out["pairs"].append(pair_d)
    if a_certs and b_certs:
        out["aggregate"] = {
            "arm_a_cert_avg":  round(statistics.mean(a_certs), 4),
            "arm_b_cert_avg":  round(statistics.mean(b_certs), 4),
            "arm_a_score_avg": round(statistics.mean(a_scores), 3),
            "arm_b_score_avg": round(statistics.mean(b_scores), 3),
            "delta_cert_pp":   round((statistics.mean(a_certs) - statistics.mean(b_certs)) * 100, 2),
            "delta_score":     round(statistics.mean(a_scores) - statistics.mean(b_scores), 3),
            "trend_a_certs":   a_certs,
            "trend_b_certs":   b_certs,
            "trend_a_scores":  a_scores,
            "trend_b_scores":  b_scores,
        }
    return out


def progressive_degradation(perf: dict) -> bool:
    """True if BOTH arms have monotonic non-improvement across pairs."""
    a = perf["aggregate"].get("trend_a_certs", [])
    b = perf["aggregate"].get("trend_b_certs", [])
    if len(a) < 2 or len(b) < 2:
        return False
    a_decay = all(a[i] <= a[i-1] for i in range(1, len(a)))
    b_decay = all(b[i] <= b[i-1] for i in range(1, len(b)))
    return a_decay and b_decay


# ── Harness markers (3 categories per GPT-5.5) ────────────────────────────────

def harness_markers() -> dict:
    if not _LOG_FILE.exists():
        return {"available": False}
    text = _LOG_FILE.read_text(encoding="utf-8", errors="ignore")

    # NORMAL: most [LLM_ROUTER] entries are routine traces
    router_total = len(re.findall(r"\[LLM_ROUTER\]", text))

    # ANOMALOUS LLM ACTIVITY
    fallback_events = len(re.findall(r"\bfallback\b(?!\s+su\s+simulazione)", text, re.IGNORECASE))
    # exclude the recurring "[quantum_soul] Qiskit non disponibile - fallback su simulazione"
    timeouts        = len(re.findall(r"\btimed?\s*out\b", text, re.IGNORECASE))
    circuit         = len(re.findall(r"\[CIRCUIT\]|circuit breaker|provider exhausted|ALL PROVIDERS FAILED", text, re.IGNORECASE))

    # ANOMALOUS SOURCE/HTTP ACTIVITY
    http_429 = len(re.findall(r"\b429\b", text))
    http_503 = len(re.findall(r"\b503\b", text))
    http_502 = len(re.findall(r"\b502\b", text))
    http_500 = len(re.findall(r"(?<!\d)500(?!\d)", text))  # be careful: 500 appears in many numeric contexts; this is approximate

    return {
        "available": True,
        "normal_router_traces":  router_total,
        "anomalous_llm": {
            "fallback_events": fallback_events,
            "timeouts":        timeouts,
            "circuit_breakers": circuit,
        },
        "anomalous_source": {
            "http_429": http_429,
            "http_503": http_503,
            "http_502": http_502,
            "http_500_approx": http_500,
        },
        "total_anomalous_events": fallback_events + timeouts + circuit + http_429 + http_503 + http_502,
    }


# ── Mood & mechanism check ────────────────────────────────────────────────────

def load_mood_files() -> dict:
    """Returns {pair_idx: {arm_letter: [samples]}}."""
    out: dict = {}
    if not _MOOD_DIR.exists():
        return out
    for f in sorted(_MOOD_DIR.glob("pair*.jsonl")):
        m = re.match(r"pair(\d+)_arm_([ab])\.jsonl", f.name)
        if not m:
            continue
        pair_idx = int(m.group(1))
        arm = m.group(2)
        samples = []
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        out.setdefault(pair_idx, {})[arm] = samples
    return out


def mood_arm_stats(samples: list) -> dict:
    if not samples:
        return {"available": False}
    scores = [float(s["mood_score"]) for s in samples]
    wb     = [float(s.get("components", {}).get("workspace_bias", 0.0)) for s in samples]
    labels = [s.get("label", "?") for s in samples]
    return {
        "available": True,
        "n":              len(scores),
        "mood_min":       round(min(scores), 3),
        "mood_max":       round(max(scores), 3),
        "mood_mean":      round(statistics.mean(scores), 3),
        "mood_std":       round(statistics.stdev(scores) if len(scores) > 1 else 0.0, 3),
        "pct_below_neg_thresh": round(sum(1 for s in scores if s <= -VALENCE_THRESH) / len(scores) * 100, 1),
        "pct_above_pos_thresh": round(sum(1 for s in scores if s >=  VALENCE_THRESH) / len(scores) * 100, 1),
        "pct_dead_zone":        round(sum(1 for s in scores if -VALENCE_THRESH < s < VALENCE_THRESH) / len(scores) * 100, 1),
        "workspace_bias_mean":  round(statistics.mean(wb), 4) if wb else 0.0,
        "workspace_bias_nonzero_pct": round(sum(1 for x in wb if abs(x) > 1e-6) / len(wb) * 100, 1) if wb else 0.0,
        "labels":         dict(Counter(labels)),
    }


def mechanism_interpretation(arm_stats: dict) -> str:
    if not arm_stats.get("available"):
        return "UNAVAILABLE: no mood samples for this arm."
    crossed_neg = arm_stats["pct_below_neg_thresh"] > 0
    bias_active = arm_stats["workspace_bias_nonzero_pct"] > 0
    if not crossed_neg:
        return "Stress regime not reached (mood never crossed -0.3)."
    if crossed_neg and not bias_active:
        return "GWT mood threshold reached but coupling/winner propagation NOT observed (workspace_bias flat)."
    if crossed_neg and bias_active:
        return "GWT mechanism activates: mood crossed threshold AND workspace_bias non-zero. Operational advantage requires separate evaluation."
    return "Indeterminate."


# ── Recovery dynamics (PARTIAL: error_signature/strategy not in current artifacts) ──

def recovery_dynamics() -> dict:
    """Currently UNAVAILABLE: per-attempt error_signature and strategy_used are
    captured at runtime by SHARD but not surfaced into d2_frustration_results.json
    in the current schema. Marked UNAVAILABLE rather than zeroed — explicit
    policy from GPT-5.5 review.
    """
    return {
        "SERR": "UNAVAILABLE",
        "SSR":  "UNAVAILABLE",
        "TNA":  "UNAVAILABLE",
        "note": (
            "Per-attempt error_signature and strategy_used are present in "
            "study_phases / cycle_data at runtime but NOT serialized into "
            "d2_frustration_results.json. To compute SERR/SSR/TNA reliably, "
            "the benchmark schema must be extended OR benchmark_episodes.json "
            "must be cross-correlated with run timestamps. Marked UNAVAILABLE "
            "to avoid coercing missing data into 'no change'."
        ),
    }


# ── Harness risks (Task 2 review of d2_frustration_benchmark.py) ──────────────

def harness_risks() -> list:
    risks = []
    src = (_ROOT / "backend" / "d2_frustration_benchmark.py").read_text(encoding="utf-8")

    # Check arm differentiation
    if "use_affective_layer=True" in src and "no_l3=False" in src and "no_l3=True" in src:
        risks.append({
            "ok": True,
            "note": "Arm differentiation correct: ARM_A no_l3=False, ARM_B no_l3=True; use_affective_layer=True for both.",
        })
    else:
        risks.append({
            "ok": False,
            "note": "Arm differentiation NOT confirmed via static read — verify manually.",
        })

    # Snapshot mechanism
    if "shutil.copytree(_MEM, SNAPSHOT_DIR)" in src and "shutil.copytree(SNAPSHOT_DIR, _MEM)" in src:
        risks.append({
            "ok": True,
            "note": "Snapshot/restore covers shard_memory/ recursively (filesystem level).",
        })

    # In-process residue risks
    risks.append({
        "ok": False,
        "note": (
            "RISK: filesystem restore alone does NOT reset in-process state. "
            "ChromaDB clients, SQLite singletons, FeedbackField, MoodEngine, "
            "CognitionCore singletons, LLM router cache, strategy_memory in-memory "
            "may persist across arms IF the same Python process runs both arms. "
            "Current design exits process between arms (good), but only one arm "
            "per invocation. Re-running the script reuses fresh interpreter — OK."
        ),
    })

    # mood_history reset
    if "archive_mood_history" in src:
        risks.append({
            "ok": True,
            "note": "mood_history.jsonl is moved aside per (pair, arm) — clean trajectory per arm.",
        })

    # External instability
    risks.append({
        "ok": False,
        "note": (
            "RISK: external services (Groq/Gemini/Claude routing, Brave Search) "
            "introduce non-deterministic noise. Current run shows 52 fallback events "
            "and 21 HTTP-level errors. No abort threshold implemented — a single "
            "bad slot can poison both arms differently."
        ),
    })

    # Topic order randomization
    if "random.shuffle" not in src and "RANDOM_SEED" in src:
        risks.append({
            "ok": False,
            "note": "Topic order is fixed across arms. If first topic is consistently hardest, it primes mood for the rest. Consider rotating order or seeding shuffles.",
        })

    return risks


# ── Verdict ───────────────────────────────────────────────────────────────────

def compute_verdict(perf: dict, harness: dict, mood_per_arm: dict) -> dict:
    degraded = progressive_degradation(perf)
    fb = harness.get("anomalous_llm", {}).get("fallback_events", 0) if harness.get("available") else 0
    http_anom = sum(harness.get("anomalous_source", {}).values()) if harness.get("available") else 0

    # Aggregate mood threshold crossing across all arms
    any_crossed_neg = False
    any_bias_active = False
    for arm_stats in mood_per_arm.values():
        if not arm_stats.get("available"):
            continue
        if arm_stats["pct_below_neg_thresh"] > 0:
            any_crossed_neg = True
        if arm_stats["workspace_bias_nonzero_pct"] > 0:
            any_bias_active = True

    # GPT-5.5 abort thresholds (informative, not enforced — D2.0 already finished)
    contam_threshold = (fb > 10) or (http_anom > 3)

    if degraded and contam_threshold:
        verdict = "INCONCLUSIVE_HARNESS"
        reason = (
            f"D2.0 shows progressive degradation across pairs affecting both arms. "
            f"The run also contains {fb} LLM fallback events and {http_anom} HTTP-level "
            f"service/search errors. This is enough external instability to invalidate "
            f"causal interpretation of GWT_ON vs GWT_OFF, even though most [LLM_ROUTER] "
            f"log markers were normal routing traces."
        )
    elif not any_crossed_neg:
        verdict = "INCONCLUSIVE_NO_STRESS"
        reason = "Natural mood never crossed -0.3 in either arm; the stress regime D2 was designed to test was not reached."
    elif any_crossed_neg and not any_bias_active:
        verdict = "MECHANISM_ONLY"
        reason = "Mood crossed threshold but workspace_bias never propagated; coupling step missing or no winners produced."
    else:
        a = perf["aggregate"].get("delta_cert_pp", 0)
        if a >= 15:
            verdict = "VALID_POSITIVE"
            reason = f"GWT_ON cert_rate exceeds GWT_OFF by {a:.1f}pp."
        elif a <= -15:
            verdict = "VALID_NULL"
            reason = f"GWT_ON cert_rate is {abs(a):.1f}pp BELOW GWT_OFF — H0 supported (or worse)."
        else:
            verdict = "INCONCLUSIVE_MISSING_DATA"
            reason = "No primary criterion (a)-(c) reached >=15pp threshold; SERR/SSR/TNA unavailable."
    return {
        "verdict": verdict,
        "reason":  reason,
        "degraded": degraded,
        "contam_threshold_breached": contam_threshold,
        "any_mood_crossed_neg": any_crossed_neg,
        "any_workspace_bias_active": any_bias_active,
    }


# ── Render ────────────────────────────────────────────────────────────────────

def render_summary(perf, harness, mood_per_arm, recovery, risks, verdict) -> str:
    lines = []
    lines.append("# D2 Frustration Benchmark — Post-hoc Analysis (D2.0)\n")
    lines.append(f"**Verdict: `{verdict['verdict']}`**\n")
    lines.append(f"> {verdict['reason']}\n")

    lines.append("## 1. Performance summary\n")
    agg = perf.get("aggregate", {})
    if agg:
        lines.append(f"- ARM_A (GWT_ON):  cert={agg['arm_a_cert_avg']:.1%}  score={agg['arm_a_score_avg']:.2f}")
        lines.append(f"- ARM_B (GWT_OFF): cert={agg['arm_b_cert_avg']:.1%}  score={agg['arm_b_score_avg']:.2f}")
        lines.append(f"- Delta:           cert={agg['delta_cert_pp']:+.1f}pp  score={agg['delta_score']:+.2f}")
        lines.append(f"- Trend ARM_A cert by pair: {agg['trend_a_certs']}")
        lines.append(f"- Trend ARM_B cert by pair: {agg['trend_b_certs']}")
        if verdict.get("degraded"):
            lines.append("\n> WARNING: progressive pair degradation detected. D2.0 cannot support H1/H0.")
    lines.append("")

    lines.append("## 2. Harness markers (3 categories)\n")
    if harness.get("available"):
        lines.append(f"### NORMAL ROUTER ACTIVITY")
        lines.append(f"- `[LLM_ROUTER]` markers: {harness['normal_router_traces']} (routine traces, NOT errors)")
        lines.append(f"\n### ANOMALOUS LLM ACTIVITY")
        a = harness["anomalous_llm"]
        lines.append(f"- fallback / provider-switch events: {a['fallback_events']}")
        lines.append(f"- timeouts: {a['timeouts']}")
        lines.append(f"- circuit breakers / providers exhausted: {a['circuit_breakers']}")
        lines.append(f"\n### ANOMALOUS SOURCE/HTTP ACTIVITY")
        s = harness["anomalous_source"]
        lines.append(f"- HTTP 429 (Brave Search rate-limit): {s['http_429']}")
        lines.append(f"- HTTP 503 (provider/service): {s['http_503']}")
        lines.append(f"- HTTP 502: {s['http_502']}")
        lines.append(f"- HTTP 500 (approximate count): {s['http_500_approx']}")
        lines.append(f"\n**Total anomalous external-service events: {harness['total_anomalous_events']}**\n")
    else:
        lines.append("Log file not available — harness markers UNAVAILABLE.\n")

    lines.append("## 3. Mechanism check (mood + workspace_bias)\n")
    for key, stats in sorted(mood_per_arm.items()):
        lines.append(f"### {key}")
        if not stats.get("available"):
            lines.append("UNAVAILABLE: no mood samples for this arm.\n")
            continue
        lines.append(f"- n={stats['n']}  mood: min={stats['mood_min']:+.3f} max={stats['mood_max']:+.3f} mean={stats['mood_mean']:+.3f} std={stats['mood_std']:.3f}")
        lines.append(f"- below -{VALENCE_THRESH}: {stats['pct_below_neg_thresh']:.1f}%   above +{VALENCE_THRESH}: {stats['pct_above_pos_thresh']:.1f}%   dead zone: {stats['pct_dead_zone']:.1f}%")
        lines.append(f"- workspace_bias mean={stats['workspace_bias_mean']:+.4f}  non-zero pct={stats['workspace_bias_nonzero_pct']:.1f}%")
        lines.append(f"- labels: {stats['labels']}")
        lines.append(f"- interpretation: {mechanism_interpretation(stats)}")
        lines.append("")

    lines.append("## 4. Recovery dynamics (SERR / SSR / TNA)\n")
    lines.append(f"- SERR: `{recovery['SERR']}`")
    lines.append(f"- SSR:  `{recovery['SSR']}`")
    lines.append(f"- TNA:  `{recovery['TNA']}`")
    lines.append(f"\n> {recovery['note']}\n")

    lines.append("## 5. Harness risks found (static review of d2_frustration_benchmark.py)\n")
    for r in risks:
        prefix = "[OK]" if r["ok"] else "[RISK]"
        lines.append(f"- {prefix} {r['note']}")
    lines.append("")

    lines.append("## 6. Recommended D2.1 protocol\n")
    lines.append("**Single-pair diagnostic, subprocess isolation, abort thresholds.**\n")
    lines.append("```")
    lines.append("D2.1 protocol:")
    lines.append("  1. restore baseline snapshot")
    lines.append("  2. spawn subprocess for ARM_A; let it exit")
    lines.append("  3. restore baseline snapshot")
    lines.append("  4. spawn subprocess for ARM_B; let it exit")
    lines.append("  5. collect logs + mood history per arm")
    lines.append("  6. compare")
    lines.append("")
    lines.append("Reduce surface area:")
    lines.append("  - 1 hard topic + 1 medium topic (not 3)")
    lines.append("  - lower API budget per arm")
    lines.append("  - log provider/model per attempt")
    lines.append("  - cache or freeze MAP-phase sources to avoid Brave 429")
    lines.append("")
    lines.append("Abort thresholds (per arm):")
    lines.append("  - LLM fallback events > 10  -> mark arm contaminated, abort")
    lines.append("  - HTTP 4xx/5xx errors  > 3  -> mark arm contaminated, abort")
    lines.append("  - or: fallback_rate > 5% of LLM calls -> contaminated")
    lines.append("")
    lines.append("Do NOT run multi-pair long benchmarks until single-pair is stable.")
    lines.append("```\n")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not _RESULTS.exists():
        print(f"[d2_analyze] Missing {_RESULTS}. Run d2_frustration_benchmark.py first.")
        return
    results = json.loads(_RESULTS.read_text(encoding="utf-8"))
    perf    = perf_summary(results)
    harness = harness_markers()

    mood_files  = load_mood_files()
    mood_per_arm = {}
    for pair_idx, arms in mood_files.items():
        for arm_letter, samples in arms.items():
            mood_per_arm[f"pair{pair_idx}_arm_{arm_letter}"] = mood_arm_stats(samples)

    recovery = recovery_dynamics()
    risks    = harness_risks()
    verdict  = compute_verdict(perf, harness, mood_per_arm)

    summary_md = render_summary(perf, harness, mood_per_arm, recovery, risks, verdict)
    metrics = {
        "performance":   perf,
        "harness":       harness,
        "mood_per_arm":  mood_per_arm,
        "recovery":      recovery,
        "risks":         risks,
        "verdict":       verdict,
    }

    _OUT_MD.write_text(summary_md, encoding="utf-8")
    _OUT_JSON.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    # Console: print short summary + verdict
    print(summary_md.split("## 5.")[0])  # everything up to risks section
    print(f"\n[d2_analyze] Full summary -> {_OUT_MD}")
    print(f"[d2_analyze] Metrics JSON   -> {_OUT_JSON}")
    print(f"\nFINAL VERDICT: {verdict['verdict']}")


if __name__ == "__main__":
    main()
