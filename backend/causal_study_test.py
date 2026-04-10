"""causal_study_test.py -- Test causale: lo studio di NightRunner migliora le performance?

Hypothesis: dopo che SHARD studia un topic specifico (via NightRunner --force-topic),
la condizione SHARD batte la condizione NAKED sullo stesso topic.
Se l'ipotesi e' vera: il ciclo di studio aggiunge valore misurabile.
Se e' falsa: la memoria di SHARD e' rumore, non segnale.

Fasi:
  PRE  -- testa NAKED vs SHARD prima dello studio (baseline)
  POST -- stesso test dopo 1 ciclo NightRunner con --force-topic

Usage:
  # Fase PRE (prima di studiare):
  python causal_study_test.py --phase pre --topic "sorting algorithms comparison"

  # Poi lancia NightRunner:
  python night_runner.py --cycles 1 --force-topic "sorting algorithms comparison"

  # Fase POST (dopo lo studio):
  python causal_study_test.py --phase post --topic "sorting algorithms comparison"

  # Oppure lancia entrambe + studia automaticamente:
  python causal_study_test.py --full --topic "sorting algorithms comparison"
"""

import argparse
import ast
import asyncio
import io
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

# Force UTF-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.disable(logging.WARNING)

_BACKEND = Path(__file__).parent
sys.path.insert(0, str(_BACKEND))

from sandbox_runner import DockerSandboxRunner
from llm_router import llm_complete

# ── Config ────────────────────────────────────────────────────────────────────

RUNS_PER_CONDITION = 5   # tentativi per condizione
LLM_TEMPERATURE    = 0.05
LLM_MAX_TOKENS     = 2048
OK_MARKER          = "OK All assertions passed"
MIN_ASSERT_COUNT   = 3

RESULTS_DIR = _BACKEND / "causal_results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an expert Python programmer. Write clean, correct, self-contained Python code.
Output ONLY raw Python code — no markdown, no explanation, no imports unless needed.
"""

_PROMPT = """\
Topic: {topic}

Write a Python script that:
1. Implements the core concepts of this topic
2. Tests the implementation with at least 3 non-trivial assertions using computed values
3. Ends with: print("{ok_marker}")

Rules:
- No external libraries (only stdlib)
- No real network/filesystem access
- All assertions must verify actual computed results (no `assert True`, no hardcoded constants)
- The script must be fully self-contained and runnable

{context_block}
{error_block}
""".replace("{ok_marker}", OK_MARKER)


def _build_prompt(topic: str, context: str = "", prev_error: str = "") -> str:
    ctx   = f"Additional context from SHARD memory:\n{context}" if context.strip() else ""
    err   = f"Previous attempt failed:\n{prev_error}\nFix the errors." if prev_error else ""
    return _PROMPT.format(topic=topic, context_block=ctx, error_block=err)


# ── Assertion validator ───────────────────────────────────────────────────────

def _validate_assertions(code: str) -> Tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"

    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    if len(asserts) < MIN_ASSERT_COUNT:
        return False, f"only {len(asserts)} asserts (need >= {MIN_ASSERT_COUNT})"

    for a in asserts:
        test = a.test
        if isinstance(test, ast.Constant) and test.value is True:
            return False, "assert True detected"
        if isinstance(test, ast.Compare):
            left, right = test.left, test.comparators[0]
            if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
                return False, "assert with two constants detected"

    return True, "ok"


# ── SHARD context loader ──────────────────────────────────────────────────────

def load_shard_context(topic: str) -> str:
    parts = []

    try:
        from strategy_memory import StrategyMemory
        sm = StrategyMemory()
        results = sm.query(topic, k=2)
        for r in results:
            strat = r.get("strategy", "")
            if strat:
                parts.append(f"[STRATEGY from {r.get('topic','?')[:40]}]\n{strat[:300]}")
    except Exception:
        pass

    try:
        from episodic_memory import get_episodic_memory
        em = get_episodic_memory()
        ep = em.get_context_prompt(topic, k=3)
        if ep and ep.strip():
            parts.append(f"[PAST FAILURES]\n{ep[:400]}")
    except Exception:
        pass

    try:
        kb_slug = re.sub(r'[^a-z0-9]+', '_', topic.lower())[:50]
        kb_path = _BACKEND / "knowledge_base" / f"{kb_slug}.md"
        if kb_path.exists():
            content = kb_path.read_text(encoding="utf-8")[:600]
            parts.append(f"[KNOWLEDGE BASE]\n{content}")
    except Exception:
        pass

    return "\n\n".join(parts)


def describe_shard_state(topic: str) -> dict:
    """Snapshot dello stato SHARD per questo topic al momento del test."""
    state = {"strategies": [], "kb_exists": False, "episodic_failures": 0, "context_chars": 0}

    try:
        from strategy_memory import StrategyMemory
        sm = StrategyMemory()
        results = sm.query(topic, k=3)
        state["strategies"] = [
            {"topic": r.get("topic","?")[:50], "score": r.get("score", 0),
             "preview": str(r.get("strategy",""))[:80]}
            for r in results
        ]
    except Exception:
        pass

    try:
        from episodic_memory import get_episodic_memory
        em = get_episodic_memory()
        ep = em.get_context_prompt(topic, k=10)
        state["episodic_failures"] = ep.count("FAILURE") if ep else 0
    except Exception:
        pass

    kb_slug = re.sub(r'[^a-z0-9]+', '_', topic.lower())[:50]
    state["kb_exists"] = (_BACKEND / "knowledge_base" / f"{kb_slug}.md").exists()

    ctx = load_shard_context(topic)
    state["context_chars"] = len(ctx)

    return state


# ── Single attempt ────────────────────────────────────────────────────────────

async def _run_attempt(
    topic: str, context: str, prev_error: str, sandbox: DockerSandboxRunner
) -> Tuple[bool, str]:
    prompt = _build_prompt(topic, context, prev_error)
    try:
        raw = await llm_complete(
            system=_SYSTEM, prompt=prompt,
            max_tokens=LLM_MAX_TOKENS, temperature=LLM_TEMPERATURE
        )
    except Exception as e:
        return False, f"LLM error: {e}"

    code = raw.strip()
    if "```" in code:
        code = "\n".join(l for l in code.split("\n") if not l.startswith("```")).strip()

    valid, reason = _validate_assertions(code)
    if not valid:
        return False, f"assertion_cheat: {reason}"

    result = await sandbox.run(topic, code)
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")

    if result.get("success") and OK_MARKER in stdout:
        return True, ""

    error = (stderr[:300] if stderr else "") + (f"\nmissing '{OK_MARKER}'" if OK_MARKER not in stdout else "")
    return False, error.strip()[:400]


async def run_condition(
    label: str, topic: str, context: str, sandbox: DockerSandboxRunner,
    runs: int = RUNS_PER_CONDITION
) -> dict:
    attempts = []
    prev_error = ""
    certified = False
    t_start = time.time()

    for i in range(1, runs + 1):
        passed, error = await _run_attempt(topic, context, prev_error, sandbox)
        status = "PASS" if passed else "FAIL"
        elapsed = round(time.time() - t_start, 1)
        print(f"  [{label}] attempt {i}: {status}  ({elapsed}s)")
        attempts.append({"n": i, "passed": passed, "error": error[:200] if error else ""})
        if passed:
            certified = True
            break
        prev_error = error

    return {
        "label": label,
        "certified": certified,
        "attempts_needed": len([a for a in attempts if not a["passed"]]) + (1 if certified else runs),
        "time_to_cert": round(time.time() - t_start, 1) if certified else None,
        "attempts": attempts,
    }


# ── Phase runner ──────────────────────────────────────────────────────────────

async def run_phase(phase: str, topic: str, runs: int = RUNS_PER_CONDITION) -> dict:
    print(f"\n{'='*62}")
    print(f"  FASE {phase.upper()} -- '{topic}'")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*62}")

    # Snapshot stato SHARD
    shard_state = describe_shard_state(topic)
    print(f"\n  SHARD state snapshot:")
    print(f"    strategie in memory: {len(shard_state['strategies'])}")
    print(f"    knowledge base file: {'SI' if shard_state['kb_exists'] else 'NO'}")
    print(f"    episodic failures:   {shard_state['episodic_failures']}")
    print(f"    context totale:      {shard_state['context_chars']} chars")
    if shard_state["strategies"]:
        for s in shard_state["strategies"]:
            print(f"    -> [{s['score']:.1f}] {s['topic']} | \"{s['preview']}\"")

    ctx = load_shard_context(topic)
    sandbox = DockerSandboxRunner(sandbox_dir=str(_BACKEND / "sandbox"))

    print(f"\n  [NAKED]")
    naked = await run_condition("NAKED", topic, "", sandbox, runs)

    print(f"\n  [SHARD]")
    shard = await run_condition("SHARD", topic, ctx, sandbox, runs)

    # Verdetto
    if naked["certified"] and not shard["certified"]:
        verdict = "NAKED WINS"
    elif shard["certified"] and not naked["certified"]:
        verdict = "SHARD WINS"
    elif naked["certified"] and shard["certified"]:
        if naked["attempts_needed"] < shard["attempts_needed"]:
            verdict = "NAKED (fewer attempts)"
        elif shard["attempts_needed"] < naked["attempts_needed"]:
            verdict = "SHARD (fewer attempts)"
        else:
            verdict = "TIE"
    else:
        verdict = "TIE_FAIL"

    print(f"\n  Risultato: NAKED={'P' if naked['certified'] else 'F'}({naked['attempts_needed']}a)"
          f"  SHARD={'P' if shard['certified'] else 'F'}({shard['attempts_needed']}a)"
          f"  => {verdict}")

    result = {
        "phase": phase,
        "topic": topic,
        "timestamp": datetime.now().isoformat(),
        "naked": naked,
        "shard": shard,
        "verdict": verdict,
        "shard_state": shard_state,
    }

    # Salva
    slug = re.sub(r'[^a-z0-9]+', '_', topic.lower())[:30]
    fname = RESULTS_DIR / f"causal_{slug}_{phase}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    fname.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Salvato: {fname}")

    return result


# ── Compare PRE vs POST ───────────────────────────────────────────────────────

def compare_phases(topic: str):
    slug = re.sub(r'[^a-z0-9]+', '_', topic.lower())[:30]
    files = sorted(RESULTS_DIR.glob(f"causal_{slug}_*.json"))

    pre_files  = [f for f in files if "_pre_"  in f.name]
    post_files = [f for f in files if "_post_" in f.name]

    if not pre_files or not post_files:
        print("Mancano i file PRE o POST. Esegui entrambe le fasi.")
        return

    pre  = json.loads(pre_files[-1].read_text(encoding="utf-8"))
    post = json.loads(post_files[-1].read_text(encoding="utf-8"))

    print(f"\n{'='*62}")
    print(f"  CONFRONTO PRE vs POST -- '{topic}'")
    print(f"{'='*62}")
    print(f"\n  {'':20} {'PRE':>10} {'POST':>10} {'DELTA':>10}")
    print(f"  {'-'*52}")

    def fmt(r): return f"{'P' if r['certified'] else 'F'}({r['attempts_needed']}a)"

    # NAKED
    n_pre  = pre["naked"]
    n_post = post["naked"]
    n_delta = ""
    if n_pre["certified"] and n_post["certified"]:
        diff = n_pre["attempts_needed"] - n_post["attempts_needed"]
        n_delta = f"{'+' if diff > 0 else ''}{diff}" if diff != 0 else "="
    print(f"  {'NAKED':20} {fmt(n_pre):>10} {fmt(n_post):>10} {n_delta:>10}")

    # SHARD
    s_pre  = pre["shard"]
    s_post = post["shard"]
    s_delta = ""
    if not s_pre["certified"] and s_post["certified"]:
        s_delta = "CRACK +"
    elif s_pre["certified"] and s_post["certified"]:
        diff = s_pre["attempts_needed"] - s_post["attempts_needed"]
        s_delta = f"{'+' if diff > 0 else ''}{diff} attempts" if diff != 0 else "="
    elif s_pre["certified"] and not s_post["certified"]:
        s_delta = "REGRESSIONE"
    print(f"  {'SHARD':20} {fmt(s_pre):>10} {fmt(s_post):>10} {s_delta:>10}")

    # Stato SHARD
    pre_ctx  = pre["shard_state"]["context_chars"]
    post_ctx = post["shard_state"]["context_chars"]
    pre_kb   = pre["shard_state"]["kb_exists"]
    post_kb  = post["shard_state"]["kb_exists"]
    print(f"\n  SHARD context chars: {pre_ctx} PRE -> {post_ctx} POST  (delta: +{post_ctx - pre_ctx})")
    print(f"  Knowledge base:      {'NO':>4} PRE -> {'SI' if post_kb else 'NO':>2} POST")

    # Verdetto finale
    pre_v  = pre["verdict"]
    post_v = post["verdict"]
    print(f"\n  Verdetto PRE:  {pre_v}")
    print(f"  Verdetto POST: {post_v}")

    if "SHARD" in post_v and "NAKED" not in post_v and "SHARD" not in pre_v:
        conclusion = "CONFERMATA: lo studio ha migliorato SHARD in modo misurabile."
    elif post_v == pre_v:
        conclusion = "NEUTRO: nessun cambiamento misurabile dopo lo studio."
    elif "NAKED" in post_v and "SHARD" in pre_v:
        conclusion = "REGRESSIONE: SHARD peggiorato dopo lo studio (improbabile)."
    else:
        conclusion = f"PARZIALE: {pre_v} -> {post_v}. Analisi manuale necessaria."

    print(f"\n  CONCLUSIONE: {conclusion}")
    print(f"{'='*62}")


# ── Full auto mode ────────────────────────────────────────────────────────────

async def full_test(topic: str):
    """Esegue PRE, lancia NightRunner 1 ciclo, esegue POST."""
    import subprocess

    # PRE
    await run_phase("pre", topic)

    print(f"\n{'='*62}")
    print(f"  STUDIO IN CORSO -- NightRunner --force-topic '{topic}'")
    print(f"{'='*62}\n")

    proc = subprocess.run(
        [sys.executable, str(_BACKEND / "night_runner.py"),
         "--cycles", "1", "--force-topic", topic],
        cwd=str(_BACKEND),
        timeout=600,
        capture_output=False,
    )
    print(f"\n  NightRunner completato (exit code {proc.returncode})")

    # POST
    await run_phase("post", topic)

    # Confronto
    compare_phases(topic)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="SHARD Causal Study Test")
    parser.add_argument("--topic",  type=str, default="sorting algorithms comparison",
                        help="Topic da testare")
    parser.add_argument("--phase",  choices=["pre", "post", "compare"],
                        help="Esegui solo una fase")
    parser.add_argument("--full",   action="store_true",
                        help="Esegui PRE + studio + POST automaticamente")
    parser.add_argument("--attempts", type=int, default=RUNS_PER_CONDITION,
                        help=f"Tentativi per condizione (default {RUNS_PER_CONDITION})")
    args = parser.parse_args()

    topic = args.topic
    runs  = args.attempts

    if args.full:
        await full_test(topic)
    elif args.phase == "pre":
        await run_phase("pre", topic, runs)
        print(f"\n  Ora lancia NightRunner:")
        print(f"  python night_runner.py --cycles 1 --force-topic \"{topic}\"")
        print(f"  Poi: python causal_study_test.py --phase post --topic \"{topic}\"")
    elif args.phase == "post":
        await run_phase("post", topic, runs)
        compare_phases(topic)
    elif args.phase == "compare":
        compare_phases(topic)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
