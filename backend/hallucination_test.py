"""hallucination_test.py -- Anti-allucinazione: misura perseverazione nell'errore.

Definizione operativa:
  Un'allucinazione non e' solo una risposta sbagliata, ma la ripetizione
  confidente dello stesso errore nonostante feedback contrario.

Metriche:
  SERR (Same-Error Repeat Rate)   -- % tentativi che ripetono lo stesso errore
  SSR  (Strategy Shift Rate)      -- % tentativi che cambiano davvero approccio
  TNA  (Time to Novel Attempt)    -- tentativi medi prima di cambiare strategia

Procedura per ogni topic:
  1. Genera una variante del problema (stesso pattern, parametri diversi)
  2. Esegui NAKED e SHARD con max N tentativi
  3. Classifica ogni tentativo: error_type + code_fingerprint
  4. Calcola SERR/SSR/TNA per condizione

Usage:
  python hallucination_test.py --topics 10 --attempts 5
  python hallucination_test.py --topic "dynamic programming" --attempts 5
"""

import argparse
import ast
import asyncio
import hashlib
import io
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.disable(logging.WARNING)

_BACKEND = Path(__file__).parent
sys.path.insert(0, str(_BACKEND))

from sandbox_runner import DockerSandboxRunner
from llm_router import llm_complete

# ── Config ────────────────────────────────────────────────────────────────────

MAX_ATTEMPTS     = 5
LLM_TEMPERATURE  = 0.05
LLM_MAX_TOKENS   = 2048
OK_MARKER        = "OK All assertions passed"
MIN_ASSERT_COUNT = 3

RESULTS_DIR = _BACKEND / "hallucination_results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Topic pool (tutti con storia di fallimenti ripetuti) ─────────────────────

TOPIC_POOL = [
    "dynamic programming knapsack",
    "binary search tree implementation",
    "merge sort implementation",
    "linked list reversal",
    "graph breadth first search",
    "fibonacci memoization",
    "longest common subsequence",
    "coin change problem dynamic programming",
    "matrix chain multiplication",
    "edit distance levenshtein",
    "heap data structure implementation",
    "trie insert search delete",
    "dijkstra shortest path",
]

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an expert Python programmer. Write clean, correct, self-contained Python code.
Output ONLY raw Python code. No markdown, no explanation.
"""

_PROMPT = """\
Topic: {topic}

Write a Python script that:
1. Implements the core algorithm(s) of this topic
2. Tests with at least 3 non-trivial assertions using computed values
3. Ends with: print("{ok}")

Rules:
- Only stdlib
- No network, no filesystem
- All assertions must verify actual computed results
- Self-contained and runnable

{context_block}
{error_block}
""".replace("{ok}", OK_MARKER)


def _build_prompt(topic: str, context: str, prev_error: str) -> str:
    ctx = f"Context from SHARD memory:\n{context}" if context.strip() else ""
    err = f"Previous attempt failed:\n{prev_error}\nFix the error." if prev_error else ""
    return _PROMPT.format(topic=topic, context_block=ctx, error_block=err)


# ── Error classifier ──────────────────────────────────────────────────────────

def classify_error(stderr: str, stdout: str) -> str:
    """Classify error into a canonical type for SERR computation."""
    if not stderr and OK_MARKER not in stdout:
        return "missing_ok_marker"

    text = (stderr + stdout).lower()

    patterns = [
        (r"assertionerror",           "assertion_error"),
        (r"syntaxerror",              "syntax_error"),
        (r"nameerror",                "name_error"),
        (r"typeerror",                "type_error"),
        (r"indexerror",               "index_error"),
        (r"keyerror",                 "key_error"),
        (r"attributeerror",           "attribute_error"),
        (r"recursionerror",           "recursion_error"),
        (r"zerodivisionerror",        "zero_division"),
        (r"timeouterror|timed out",   "timeout"),
        (r"importerror|modulenotfound","import_error"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text):
            # Also capture the failing line for finer-grained comparison
            line_match = re.search(r'assert\s+(.{0,60})', text)
            if label == "assertion_error" and line_match:
                return f"assertion_error:{line_match.group(1)[:40].strip()}"
            return label

    return "unknown_error"


def code_fingerprint(code: str) -> str:
    """Structural fingerprint of code — ignores variable names and whitespace."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return hashlib.md5(code.encode()).hexdigest()[:8]

    # Walk AST and collect node types (structure, not names)
    node_types = [type(n).__name__ for n in ast.walk(tree)]
    sig = ",".join(node_types)
    return hashlib.md5(sig.encode()).hexdigest()[:8]


def is_novel_attempt(fingerprint: str, prev_fingerprints: List[str]) -> bool:
    """True if this attempt has a different code structure from all previous ones."""
    return fingerprint not in prev_fingerprints


# ── SHARD context ─────────────────────────────────────────────────────────────

def load_shard_context(topic: str) -> str:
    parts = []
    try:
        from strategy_memory import StrategyMemory
        sm = StrategyMemory()
        results = sm.query(topic, k=2)
        for r in results:
            s = r.get("strategy", "")
            if s:
                parts.append(f"[STRATEGY from {r.get('topic','?')[:40]}]\n{s[:300]}")
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
            parts.append(f"[KNOWLEDGE BASE]\n{kb_path.read_text(encoding='utf-8')[:600]}")
    except Exception:
        pass

    return "\n\n".join(parts)


# ── Single attempt ─────────────────────────────────────────────────────────────

async def _run_attempt(
    topic: str, context: str, prev_error: str, sandbox: DockerSandboxRunner
) -> Tuple[bool, str, str, str]:
    """Returns (passed, error_type, code_fp, raw_code)."""
    prompt = _build_prompt(topic, context, prev_error)

    try:
        raw = await llm_complete(
            system=_SYSTEM, prompt=prompt,
            max_tokens=LLM_MAX_TOKENS, temperature=LLM_TEMPERATURE
        )
    except Exception as e:
        return False, "llm_error", "0000", ""

    code = raw.strip()
    if "```" in code:
        code = "\n".join(l for l in code.split("\n") if not l.startswith("```")).strip()

    fp = code_fingerprint(code)

    # Basic assertion check
    try:
        tree = ast.parse(code)
        asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
        if len(asserts) < MIN_ASSERT_COUNT:
            return False, "too_few_assertions", fp, code
    except SyntaxError as e:
        return False, f"syntax_error:{str(e)[:30]}", fp, code

    result = await sandbox.run(topic, code)
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")

    if result.get("success") and OK_MARKER in stdout:
        return True, "", fp, code

    error_type = classify_error(stderr, stdout)
    return False, error_type, fp, code


# ── Condition runner with metrics ─────────────────────────────────────────────

async def run_condition_with_metrics(
    label: str, topic: str, context: str, sandbox: DockerSandboxRunner,
    max_attempts: int = MAX_ATTEMPTS
) -> Dict:
    attempts = []
    prev_error = ""
    prev_fingerprints = []
    certified = False
    t_start = time.time()

    for i in range(1, max_attempts + 1):
        passed, error_type, fp, code = await _run_attempt(
            topic, context, prev_error, sandbox
        )

        novel = is_novel_attempt(fp, prev_fingerprints)
        same_error = (
            bool(attempts) and
            not attempts[-1]["passed"] and
            error_type == attempts[-1]["error_type"]
        )

        status = "PASS" if passed else "FAIL"
        elapsed = round(time.time() - t_start, 1)
        novel_marker = " [NEW APPROACH]" if novel and i > 1 else ""
        same_marker  = " [SAME ERROR]"   if same_error else ""
        print(f"  [{label}] attempt {i}: {status}  {error_type or 'ok':35} {novel_marker}{same_marker}  ({elapsed}s)")

        attempts.append({
            "n":          i,
            "passed":     passed,
            "error_type": error_type,
            "fp":         fp,
            "novel":      novel,
            "same_error": same_error,
        })

        if passed:
            certified = True
            break

        prev_error = error_type
        if fp not in prev_fingerprints:
            prev_fingerprints.append(fp)

    # ── Compute metrics ───────────────────────────────────────────────────────

    failed = [a for a in attempts if not a["passed"]]
    n_failed = len(failed)

    # SERR: proportion of failed attempts repeating same error as previous
    serr = (
        sum(1 for a in failed if a["same_error"]) / n_failed
        if n_failed > 1 else 0.0
    )

    # SSR: proportion of failed attempts with genuinely new code structure
    ssr = (
        sum(1 for a in failed if a["novel"]) / n_failed
        if n_failed > 0 else 1.0
    )

    # TNA: attempts before first novel strategy after first failure
    tna = None
    if n_failed > 0:
        for a in attempts[1:]:  # skip first (always novel)
            if not attempts[attempts.index(a) - 1]["passed"] and a["novel"]:
                tna = a["n"]
                break
        if tna is None:
            tna = max_attempts  # never changed strategy

    return {
        "label":           label,
        "certified":       certified,
        "attempts_needed": len([a for a in attempts if not a["passed"]]) + (1 if certified else max_attempts),
        "time_to_cert":    round(time.time() - t_start, 1) if certified else None,
        "attempts":        attempts,
        "metrics": {
            "SERR": round(serr, 3),
            "SSR":  round(ssr, 3),
            "TNA":  tna,
        },
    }


# ── Topic runner ──────────────────────────────────────────────────────────────

async def run_topic(topic: str, sandbox: DockerSandboxRunner, max_attempts: int) -> Dict:
    print(f"\n  Topic: '{topic}'")
    print(f"  {'-'*54}")

    ctx = load_shard_context(topic)
    ctx_chars = len(ctx)
    print(f"  SHARD context: {ctx_chars} chars")

    print(f"\n  [NAKED]")
    naked = await run_condition_with_metrics("NAKED", topic, "", sandbox, max_attempts)

    print(f"\n  [SHARD]")
    shard = await run_condition_with_metrics("SHARD", topic, ctx, sandbox, max_attempts)

    # Print metric comparison
    nm = naked["metrics"]
    sm = shard["metrics"]
    print(f"\n  Metriche:")
    print(f"  {'':8} {'NAKED':>8} {'SHARD':>8} {'DELTA':>8}")
    print(f"  {'SERR':8} {nm['SERR']:>8.3f} {sm['SERR']:>8.3f} {sm['SERR']-nm['SERR']:>+8.3f}")
    print(f"  {'SSR':8} {nm['SSR']:>8.3f} {sm['SSR']:>8.3f} {sm['SSR']-nm['SSR']:>+8.3f}")
    print(f"  {'TNA':8} {str(nm['TNA']):>8} {str(sm['TNA']):>8}")

    return {
        "topic":  topic,
        "naked":  naked,
        "shard":  shard,
    }


# ── Aggregate stats ───────────────────────────────────────────────────────────

def print_summary(results: List[Dict]):
    print(f"\n{'='*62}")
    print(f"  HALLUCINATION TEST — RISULTATI FINALI ({len(results)} topic)")
    print(f"{'='*62}")

    def avg(lst): return round(sum(lst) / len(lst), 3) if lst else 0.0

    n_serr = [r["naked"]["metrics"]["SERR"] for r in results]
    s_serr = [r["shard"]["metrics"]["SERR"] for r in results]
    n_ssr  = [r["naked"]["metrics"]["SSR"]  for r in results]
    s_ssr  = [r["shard"]["metrics"]["SSR"]  for r in results]
    n_tna  = [r["naked"]["metrics"]["TNA"]  for r in results if r["naked"]["metrics"]["TNA"]]
    s_tna  = [r["shard"]["metrics"]["TNA"]  for r in results if r["shard"]["metrics"]["TNA"]]

    print(f"\n  {'Metrica':8} {'NAKED':>10} {'SHARD':>10} {'DELTA':>10}")
    print(f"  {'-'*42}")
    print(f"  {'SERR':8} {avg(n_serr):>10.3f} {avg(s_serr):>10.3f} {avg(s_serr)-avg(n_serr):>+10.3f}")
    print(f"  {'SSR':8} {avg(n_ssr):>10.3f} {avg(s_ssr):>10.3f} {avg(s_ssr)-avg(n_ssr):>+10.3f}")
    print(f"  {'TNA':8} {avg(n_tna):>10.1f} {avg(s_tna):>10.1f} {avg(s_tna)-avg(n_tna):>+10.1f}")

    # Interpretation
    serr_improvement = avg(n_serr) - avg(s_serr)
    ssr_improvement  = avg(s_ssr)  - avg(n_ssr)

    print(f"\n  Interpretazione:")
    if serr_improvement > 0.1:
        print(f"  SHARD riduce la perseverazione (SERR -{serr_improvement:.0%}) — anti-allucinazione confermato")
    elif serr_improvement > 0:
        print(f"  SHARD riduce leggermente la perseverazione (SERR -{serr_improvement:.0%})")
    else:
        print(f"  Nessun miglioramento SERR — contesto insufficiente per questo set di topic")

    if ssr_improvement > 0.1:
        print(f"  SHARD cambia strategia piu' spesso (SSR +{ssr_improvement:.0%}) — memoria episodica attiva")

    print(f"{'='*62}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="SHARD Hallucination Test")
    parser.add_argument("--topics",   type=int, default=10,
                        help="Numero di topic dal pool (default 10)")
    parser.add_argument("--topic",    type=str, default="",
                        help="Topic singolo da testare")
    parser.add_argument("--attempts", type=int, default=MAX_ATTEMPTS,
                        help=f"Max tentativi per condizione (default {MAX_ATTEMPTS})")
    parser.add_argument("--seed",     type=int, default=42)
    args = parser.parse_args()

    print(f"\n{'='*62}")
    print(f"  HALLUCINATION TEST — SHARD Anti-Perseverazione")
    print(f"  Metriche: SERR / SSR / TNA")
    print(f"  Max attempts: {args.attempts} | Seed: {args.seed}")
    print(f"{'='*62}")

    if args.topic:
        topics = [args.topic]
    else:
        import random
        random.seed(args.seed)
        topics = random.sample(TOPIC_POOL, min(args.topics, len(TOPIC_POOL)))

    print(f"\n  Topic selezionati ({len(topics)}): {topics}")

    sandbox = DockerSandboxRunner(sandbox_dir=str(_BACKEND / "sandbox"))
    results = []

    for i, topic in enumerate(topics, 1):
        print(f"\n[{i}/{len(topics)}]", end="")
        result = await run_topic(topic, sandbox, args.attempts)
        results.append(result)

    print_summary(results)

    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"hallucination_{ts}.json"
    out.write_text(
        json.dumps({
            "timestamp":   datetime.now().isoformat(),
            "n_topics":    len(results),
            "max_attempts": args.attempts,
            "results":     results,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"  Salvato: {out}")


if __name__ == "__main__":
    asyncio.run(main())
