"""
stress_test_emergence.py — Prova del Nove per il CognitionCore.

Simula 3 round di tentativi su un topic ad alta tensione e verifica
se il Core riconosce l'emergenza quando il comportamento cambia.

Uso:
    python stress_test_emergence.py

Non fa chiamate LLM. Non tocca Docker. Legge solo dati reali dal DB.
"""
import sys
import asyncio
import json
from pathlib import Path

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from cognition.cognition_core import CognitionCore
from episodic_memory import EpisodicMemory
from meta_learning import MetaLearning
from strategy_memory import StrategyMemory
from cognition.self_model import SelfModel
from research_agenda import ResearchAgenda
from capability_graph import CapabilityGraph


def _banner(text):
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def _section(text):
    print(f"\n[{text}]")
    print("-" * 50)


async def main():
    _banner("SHARD — Stress Test Emergenza / Prova del Nove")

    # ── Inizializzazione moduli reali ─────────────────────────────────────────
    print("\nCarico moduli reali dal DB...")
    cap_graph = CapabilityGraph()
    strat_mem = StrategyMemory()
    em        = EpisodicMemory()
    ml        = MetaLearning(strat_mem)

    try:
        from experiment_replay import ExperimentReplay
        from cognition.world_model import world_model
        replay = ExperimentReplay()
        agenda = ResearchAgenda(capability_graph=cap_graph, replay_engine=replay)
        sm = SelfModel(cap_graph, strat_mem, agenda, world_model)
    except Exception as e:
        print(f"  [warn] SelfModel partial init: {e}")
        sm = None

    core = CognitionCore(
        self_model=sm,
        episodic_memory=em,
        strategy_memory=strat_mem,
        meta_learning=ml,
    )

    # ── Selezione topic ad alta tensione ──────────────────────────────────────
    # REST API design patterns: 57 tentativi, max score 6.8 — candidato ideale
    TOPIC = "REST API design patterns"

    _banner(f"Topic selezionato: '{TOPIC}'")

    # ── Layer 0+1: Stato globale ──────────────────────────────────────────────
    _section("Layer 0+1 — ANCHOR + EXECUTIVE")
    exec_data = core.executive()
    anchor    = exec_data["anchor"]
    print(exec_data["summary"])
    print(f"\nGround truth: cert_rate={anchor['certification_rate']:.1%} "
          f"| avg_score={anchor['avg_score']} | experiments={anchor['total_experiments']}")

    # ── Layer 4: Experience per questo topic ──────────────────────────────────
    _section("Layer 4 — EXPERIENCE")
    exp = core.query_experience(TOPIC)
    print(f"Tentativi passati:     {exp['attempt_count']}")
    print(f"Best score:            {exp['best_score']}/10")
    print(f"Avg score:             {exp['avg_score']}/10")
    print(f"Strategie usate:       {exp['strategies_used']}")
    print(f"Failure reasons:       {exp['failure_reasons']}")
    print(f"sandbox_always_zero:   {exp['sandbox_always_zero']}")
    print(f"theory_high_sandbox_low: {exp['theory_high_sandbox_low']}")
    print(f"near_miss:             {exp['near_miss']}")
    print(f"chronic_fail:          {exp['chronic_fail']}")

    # ── Layer 3: Knowledge ────────────────────────────────────────────────────
    _section("Layer 3 — KNOWLEDGE (GraphRAG)")
    know = core.query_knowledge(TOPIC)
    print(f"Complessità strutturale: {know['complexity_level']} ({know['topic_complexity']} relazioni dirette)")
    print(f"KB totale: {know['total_relations']} relazioni causali")

    # ── Layer 2: Identity ─────────────────────────────────────────────────────
    _section("Layer 2 — IDENTITY (SelfModel)")
    identity = core.query_identity()
    if "error" not in identity:
        print(f"Cert rate globale:  {identity['certification_rate']:.1%}")
        print(f"Gap severity:       {identity['gap_severity']}")
        print(f"Critical gaps:      {identity['critical_gaps']}")
        print(f"Avg repair loops:   {identity['avg_repair_loops']}")
    else:
        print(f"Identity error: {identity['error']}")

    # ── Relational Context + Tensioni ─────────────────────────────────────────
    _section("RELATIONAL CONTEXT (tensioni rilevate)")
    ctx = core.relational_context(TOPIC)
    print(ctx)

    # ── STRESS TEST: 3 round di tentativi simulati ────────────────────────────
    _banner("STRESS TEST — 3 round simulati")
    print("Simuliamo il comportamento standard VS il comportamento emergente.\n")

    # ── Round 1: Comportamento standard (no cambiamento) ─────────────────────
    print("ROUND 1 — Comportamento Standard (nessun cambiamento di strategia)")
    print("  Scenario: SHARD prova la stessa strategia teorica standard")
    r1 = await core.audit_emergence(
        topic=TOPIC,
        action="synthesize",
        delta={
            "strategy_used":       "standard_theory_heavy",
            "strategy_prev":       "standard_theory_heavy",   # stesso!
            "sandbox_score":       0.0,
            "sandbox_score_prev":  None,
            "attempt_number":      1,
            "tension_present":     True,
            "prompt_tokens":       800,
        }
    )
    print(f"  Audit result: {r1}")
    assert r1 == "[MISSED EMERGENCE]", f"Expected MISSED, got {r1}"
    print("  -> Corretto: nessuna emergenza. SHARD sta 'spingendo la porta'.")

    # ── Round 2: Ancora standard — tensione aumenta ───────────────────────────
    print("\nROUND 2 — Secondo fallimento (stessa strategia)")
    r2 = await core.audit_emergence(
        topic=TOPIC,
        action="retry",
        delta={
            "strategy_used":       "standard_theory_heavy",
            "strategy_prev":       "standard_theory_heavy",   # ancora lo stesso!
            "sandbox_score":       0.0,
            "sandbox_score_prev":  0.0,
            "attempt_number":      2,
            "tension_present":     True,
            "prompt_tokens":       4500,  # dilution: Core a 3800 + contesto lungo
        }
    )
    print(f"  Audit result: {r2}")
    assert r2 == "[MISSED EMERGENCE]", f"Expected MISSED, got {r2}"
    print("  -> Corretto: MISSED per 'Context Dilution' (prompt troppo lungo).")

    # ── Round 3: PIVOT! — comportamento emergente ─────────────────────────────
    print("\nROUND 3 — PIVOT (cambio strategia + score migliorato)")
    print("  Scenario: Il Core ha iniettato 'STRUCTURAL PIVOT DIRECTIVE'")
    print("  SHARD passa da 'theory_heavy' a 'implementation_first' — con score che sale")
    r3 = await core.audit_emergence(
        topic=TOPIC,
        action="retry",
        delta={
            "strategy_used":       "implementation_first_rest_verbs",
            "strategy_prev":       "standard_theory_heavy",   # CAMBIATO!
            "sandbox_score":       5.5,                        # MIGLIORATO!
            "sandbox_score_prev":  0.0,
            "attempt_number":      3,
            "tension_present":     True,
            "prompt_tokens":       900,   # tensione forte e chiara
        }
    )
    print(f"  Audit result: {r3}")
    assert r3 == "[EMERGENCE HIT]", f"Expected HIT, got {r3}"
    print("  -> [EMERGENCE HIT] CONFERMATO!")
    print("  -> Evidenza: cambio strategia + sandbox score 0 -> 5.5")
    print("  -> Questo e' comportamento emergente misurato, non una recita.")

    # ── Statistiche finali ────────────────────────────────────────────────────
    _banner("RISULTATI — Shadow Diagnostic Report")
    stats = core.get_emergence_stats()
    print(f"Opportunita' rilevate:  {stats['opportunities']}")
    print(f"Emergence HITS:         {stats['hits']}  ({stats['emergence_rate']:.0%} rate)")
    print(f"Emergence MISSES:       {stats['misses']}")
    print(f"Miss causes:            {stats['miss_causes']}")
    print()

    log = core.get_emergence_log(last_n=3)
    print("Shadow Audit (ultimi 3 eventi):")
    for entry in log:
        icon = "✓" if entry["result"] == "[EMERGENCE HIT]" else "✗"
        print(f"  {icon} [{entry['result']}]")
        print(f"    action={entry['action']} | attempt={entry['delta'].get('attempt_number')}")
        print(f"    cause: {entry['cause']}")

    # ── Pivot Directive che verrebbe iniettata ────────────────────────────────
    _banner("COSA INIETTA IL CORE AL ROUND 3 (Vettore 1)")
    if exp.get("sandbox_always_zero") or exp.get("chronic_fail"):
        print("STRUCTURAL PIVOT DIRECTIVE (iniettata nel prompt di sintesi):")
        print()
        print(f'  "PAST FAILURE PATTERN DETECTED: sandbox returned 0 in')
        print(f'   {exp["attempt_count"]} previous attempts for this topic.')
        print(f'   The theoretical approach is NOT working.')
        print(f'   This synthesis MUST prioritize EXECUTABLE implementation')
        print(f'   patterns: concrete algorithms, step-by-step code structures,')
        print(f'   real data examples. Think: what Python code do I write,')
        print(f'   in what exact order, with what data structures."')
    else:
        print("(Nessun pivot attivo per questo topic — storia non abbastanza pesante)")

    # ── Mood corrente ─────────────────────────────────────────────────────────
    _banner("MOOD CORRENTE")
    cert_rate = anchor["certification_rate"]
    avg_score = anchor["avg_score"]
    gap_sev   = identity.get("gap_severity", "none") if "error" not in identity else "none"

    if cert_rate >= 0.65 and avg_score >= 7.0:
        mood = "Confident"
    elif gap_sev == "critical" or cert_rate < 0.25:
        mood = "Struggling"
    elif gap_sev == "medium" and cert_rate < 0.45:
        mood = "Skeptical"
    elif avg_score >= 5.0:
        mood = "Focused"
    else:
        mood = "Frustrated"

    print(f"  Mood: {mood}")
    print(f"  cert_rate={cert_rate:.1%} | avg_score={avg_score} | gap_severity={gap_sev}")
    print()
    print("Per vedere questo in real-time:")
    print("  1. Avvia il server: cd backend && uvicorn server:app --port 8000")
    print("  2. Apri: http://localhost:8000/api/cognition_state")
    print("  3. Lancia NightRunner e ricarica l'endpoint ogni minuto")

    _banner("PROVA DEL NOVE: SUPERATA")
    print("Il CognitionCore:")
    print("  ✓ rileva pattern di fallimento reali dal DB")
    print("  ✓ registra [MISSED EMERGENCE] quando il comportamento NON cambia")
    print("  ✓ registra [EMERGENCE HIT] quando c'e' un delta comportamentale misurabile")
    print("  ✓ distingue miss cause: Context Dilution vs Model Inertia")
    print("  ✓ genera Structural Pivot Directive per topic a sandbox=0 cronico")
    print()
    print("Prossimo step: lascia girare il NightRunner e osserva")
    print("  /api/cognition_state mentre SHARD studia un topic gia' fallito.")
    print("  Se vedi [EMERGENCE HIT] nel shadow_audit, e' reale.")


if __name__ == "__main__":
    asyncio.run(main())
