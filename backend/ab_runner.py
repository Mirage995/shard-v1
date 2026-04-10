"""ab_runner.py -- A/B test: Naked LLM vs LLM+SHARD.

Metrica: sandbox execution + "OK All assertions passed"
Domain-agnostic, deterministico, replicabile. Nessun judge LLM.

Variabile unica: contesto iniettato nel prompt.
  NAKED : topic + prompt template (zero contesto)
  SHARD : stesso + memoria episodica + strategia + L3

Tutto il resto identico: stesso LLM, stessa temperatura, stesso sandbox,
stesso prompt template, stesso max_attempts.

Anti-cheating: assertion validator blocca assert True / assert costanti.

Usage:
    python ab_runner.py --topics 50 --max-attempts 5
    python ab_runner.py --topics 20 --seed 42
"""
import argparse
import ast
import asyncio
import io
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Force UTF-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_BACKEND = Path(__file__).parent
sys.path.insert(0, str(_BACKEND))

from sandbox_runner import DockerSandboxRunner
from llm_router import llm_complete

SANDBOX_DIR = str(_BACKEND / "sandbox")
DB_PATH = _BACKEND.parent / "shard_memory" / "shard.db"

MAX_ATTEMPTS_DEFAULT = 5
LLM_TEMPERATURE = 0.05
LLM_MAX_TOKENS = 2048

# Assertion validator thresholds
MIN_ASSERT_COUNT = 3
OK_MARKER = "OK All assertions passed"


# ── Topic selector ─────────────────────────────────────────────────────────────

# Topics to exclude: junk, meta-topics, impossible topics
_EXCLUDE_PATTERNS = [
    r"^topic \d+$",
    r"^\[missed_emergence\]",
    r"^MISSED_EMERGENCE",
    r"impossible.*quantum",
    r"^shard debug",
    r"test_driven_development applied",
    r"^integration of",
    r"applied to",
    r"handling and debugging$",
]

def _is_excluded(topic: str) -> bool:
    t = topic.lower()
    for pat in _EXCLUDE_PATTERNS:
        if re.search(pat, t):
            return True
    return False


GATE_THRESHOLD = 6.5  # predicted score below this → inject SHARD context


def predict_difficulty(topic: str) -> Optional[float]:
    """Predicted difficulty from DB avg score. Lower = harder.
    Returns None if no history (treated as hard → use SHARD).
    """
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(
            "SELECT AVG(score) FROM experiments WHERE topic=? AND score > 0",
            (topic,)
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0] is not None:
            return round(float(row[0]), 2)
    except Exception:
        pass
    return None  # unknown → assume hard


def pick_topics(n: int, seed: int = 0) -> List[str]:
    """Pick N random topics from experiment DB (min 2 attempts each)."""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("""
        SELECT topic, COUNT(*) as c
        FROM experiments
        GROUP BY topic
        HAVING c >= 2
    """)
    rows = cur.fetchall()
    conn.close()

    candidates = [r[0] for r in rows if not _is_excluded(r[0])]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:n]


# ── Assertion validator ────────────────────────────────────────────────────────

def validate_assertions(code: str) -> Tuple[bool, str]:
    """Check that generated code has meaningful assertions.

    Rules:
    - At least MIN_ASSERT_COUNT assert statements
    - No trivial `assert True` or `assert False`
    - At least one assert must reference a function call or expression (not a literal)
    - Must contain OK_MARKER print

    Returns (valid: bool, reason: str)
    """
    if OK_MARKER not in code:
        return False, f"missing print('{OK_MARKER}')"

    # Parse AST to count and inspect asserts
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"syntax error: {e}"

    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]

    if len(asserts) < MIN_ASSERT_COUNT:
        return False, f"only {len(asserts)} assert(s), need >= {MIN_ASSERT_COUNT}"

    # Check for trivial asserts: assert True, assert False, assert 1==1, assert "x"
    trivial_count = 0
    for a in asserts:
        test = a.test
        # assert True / assert False
        if isinstance(test, ast.Constant):
            trivial_count += 1
            continue
        # assert (x == x) where both sides are same constant
        if isinstance(test, ast.Compare):
            if (len(test.ops) == 1 and
                isinstance(test.left, ast.Constant) and
                isinstance(test.comparators[0], ast.Constant) and
                test.left.value == test.comparators[0].value):
                trivial_count += 1

    if trivial_count >= len(asserts):
        return False, "all asserts are trivial constants"

    if trivial_count > len(asserts) // 2:
        return False, f"{trivial_count}/{len(asserts)} trivial asserts (majority)"

    return True, "ok"


# ── Prompt templates ───────────────────────────────────────────────────────────

_SYSTEM = (
    "You are an expert Python programmer. "
    "Write clean, correct, self-contained Python code."
)

_PROMPT_TEMPLATE = """\
Topic: {topic}

Write a Python script that:
1. Implements a working demonstration of the concept
2. Includes at least 3 meaningful assert statements that validate correctness
3. Assertions MUST test computed values, not constants (no `assert True`, no `assert 1 == 1`)
4. Each assert must call a function or compute a result and verify it

End the script with exactly this line:
    print("OK All assertions passed")

{context_block}

{error_block}

Output ONLY raw Python. No markdown, no explanations."""


def build_prompt(topic: str, context: str = "", prev_error: str = "") -> str:
    context_block = f"Additional context:\n{context}" if context.strip() else ""
    error_block = f"Previous attempt failed with:\n{prev_error}\nFix the errors above." if prev_error else ""
    return _PROMPT_TEMPLATE.format(
        topic=topic,
        context_block=context_block,
        error_block=error_block,
    )


# ── SHARD context loader ───────────────────────────────────────────────────────

def load_shard_context(topic: str) -> str:
    parts = []

    try:
        from strategy_memory import StrategyMemory
        sm = StrategyMemory()
        results = sm.query(topic, k=1)
        if results:
            strat = results[0].get("strategy", "")
            if strat:
                parts.append(f"[STRATEGY]\n{strat}")
    except Exception:
        pass

    try:
        from episodic_memory import get_episodic_memory
        em = get_episodic_memory()
        ep = em.get_context_prompt(topic, k=3)
        if ep and ep.strip():
            parts.append(f"[PAST ATTEMPTS]\n{ep}")
    except Exception:
        pass

    try:
        from link_builder import MemoryLinkBuilder
        links = MemoryLinkBuilder.get_cross_topic_links(topic, limit=3)
        if links:
            txt = "\n".join(f"  - {l.get('linked_topic','?')}" for l in links)
            parts.append(f"[RELATED TOPICS]\n{txt}")
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

async def run_single_attempt(
    topic: str,
    context: str,
    prev_error: str,
    sandbox: DockerSandboxRunner,
) -> Tuple[bool, str]:
    """Run one attempt. Returns (passed: bool, error_summary: str)."""

    prompt = build_prompt(topic, context, prev_error)

    try:
        raw = await llm_complete(
            system=_SYSTEM,
            prompt=prompt,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
        )
    except Exception as e:
        return False, f"LLM error: {e}"

    # Strip markdown
    code = raw.strip()
    if "```" in code:
        code = "\n".join(l for l in code.split("\n") if not l.startswith("```")).strip()

    # Assertion validator
    valid, reason = validate_assertions(code)
    if not valid:
        return False, f"assertion_cheat: {reason}"

    # Sandbox execution
    result = await sandbox.run(topic, code)
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    success = result.get("success", False)

    if success and OK_MARKER in stdout:
        return True, ""

    # Build error summary for next attempt
    error_parts = []
    if stderr:
        error_parts.append(stderr[:400])
    if OK_MARKER not in stdout:
        error_parts.append(f"stdout did not contain '{OK_MARKER}'")
    return False, "\n".join(error_parts)[:500]


# ── Condition loop ─────────────────────────────────────────────────────────────

async def run_condition(
    label: str,
    topic: str,
    context: str,
    sandbox: DockerSandboxRunner,
    max_attempts: int,
) -> dict:
    attempts = []
    prev_error = ""
    t_start = time.time()

    for n in range(1, max_attempts + 1):
        passed, error = await run_single_attempt(topic, context, prev_error, sandbox)
        elapsed = round(time.time() - t_start, 1)
        attempts.append({"attempt": n, "passed": passed, "elapsed": elapsed})
        status = "PASS" if passed else "FAIL"
        print(f"  [{label}] attempt {n}: {status}  ({elapsed}s)")
        if passed:
            break
        prev_error = error

    certified = attempts[-1]["passed"]
    return {
        "label": label,
        "topic": topic,
        "certified": certified,
        "attempts_needed": len(attempts),
        "time_to_success": attempts[-1]["elapsed"] if certified else None,
        "shard_ctx_chars": len(context),
        "attempts": attempts,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def _winner(a: dict, b: dict, label_a: str, label_b: str) -> str:
    if a["certified"] and b["certified"]:
        if a["attempts_needed"] < b["attempts_needed"]: return label_a
        if b["attempts_needed"] < a["attempts_needed"]: return label_b
        return "TIE"
    if a["certified"]: return label_a
    if b["certified"]: return label_b
    return "TIE_FAIL"


async def main(topics: List[str], max_attempts: int):
    print(f"\n{'='*62}")
    print(f"  A/B/C TEST: NAKED vs SHARD(always) vs SHARD(gated)")
    print(f"  Topics: {len(topics)}  |  Max attempts: {max_attempts}")
    print(f"  Gate threshold: predicted_score < {GATE_THRESHOLD}")
    print(f"  Metric: sandbox + '{OK_MARKER}'")
    print(f"  Anti-cheat: >= {MIN_ASSERT_COUNT} non-trivial asserts")
    print(f"{'='*62}\n")

    sandbox = DockerSandboxRunner(SANDBOX_DIR)
    results = []

    for i, topic in enumerate(topics):
        print(f"\n[{i+1}/{len(topics)}] '{topic}'")
        print("-" * 54)

        # Predict difficulty + gate decision
        pred = predict_difficulty(topic)
        use_shard = (pred is None or pred < GATE_THRESHOLD)
        bucket = "hard" if use_shard else "easy"
        print(f"  predicted={pred}  use_shard={use_shard}  bucket={bucket}")

        # Load SHARD context once
        ctx = load_shard_context(topic)
        print(f"  SHARD context: {len(ctx)} chars")

        # NAKED
        naked = await run_condition("NAKED", topic, "", sandbox, max_attempts)

        # SHARD always-on
        shard = await run_condition("SHARD", topic, ctx, sandbox, max_attempts)

        # GATED — uses ctx only if predicted hard
        gated_ctx = ctx if use_shard else ""
        gated = await run_condition("GATED", topic, gated_ctx, sandbox, max_attempts)
        print(f"  [GATED] predicted={pred}  use_shard={use_shard}")

        w_naked_shard = _winner(naked, shard, "NAKED", "SHARD")
        w_naked_gated = _winner(naked, gated, "NAKED", "GATED")
        w_gated_shard = _winner(gated, shard, "GATED", "SHARD")

        results.append({
            "topic": topic,
            "naked": naked, "shard": shard, "gated": gated,
            "winner_naked_vs_shard": w_naked_shard,
            "winner_naked_vs_gated": w_naked_gated,
            "winner_gated_vs_shard": w_gated_shard,
            "gated_meta": {
                "predicted_score": pred,
                "use_shard": use_shard,
                "difficulty_bucket": bucket,
            },
        })
        print(f"  => NAKED: {'P' if naked['certified'] else 'F'}({naked['attempts_needed']}a)  "
              f"SHARD: {'P' if shard['certified'] else 'F'}({shard['attempts_needed']}a)  "
              f"GATED: {'P' if gated['certified'] else 'F'}({gated['attempts_needed']}a)  "
              f"| GATED_vs_NAKED={w_naked_gated}")

    # ── Summary ────────────────────────────────────────────────────────────────
    n = len(results)
    if n == 0:
        print("\nNo results.")
        return

    def _stats(key):
        cert  = sum(1 for r in results if r[key]["certified"])
        att   = sum(r[key]["attempts_needed"] for r in results) / n
        times = [r[key]["time_to_success"] for r in results if r[key]["time_to_success"]]
        t_avg = round(sum(times)/len(times), 1) if times else None
        return cert, round(att, 2), t_avg

    n_cert, n_att, n_t = _stats("naked")
    s_cert, s_att, s_t = _stats("shard")
    g_cert, g_att, g_t = _stats("gated")

    gated_wins  = sum(1 for r in results if r["winner_naked_vs_gated"] == "GATED")
    naked_wins  = sum(1 for r in results if r["winner_naked_vs_gated"] == "NAKED")
    ties        = sum(1 for r in results if "TIE" in r["winner_naked_vs_gated"])

    verdict = (
        "GATED WINS" if gated_wins > naked_wins
        else "NAKED WINS" if naked_wins > gated_wins
        else "PAREGGIO"
    )

    # Segmentation: easy vs hard
    hard = [r for r in results if r["gated_meta"]["difficulty_bucket"] == "hard"]
    easy = [r for r in results if r["gated_meta"]["difficulty_bucket"] == "easy"]

    def _seg_cert(subset, key):
        if not subset: return "n/a"
        return f"{sum(1 for r in subset if r[key]['certified'])}/{len(subset)}"

    print(f"\n{'='*62}")
    print(f"  RISULTATI FINALI  ({n} topic)")
    print(f"{'='*62}")
    print(f"  {'Topic'[:38]:<38} {'NK':>5} {'SH':>5} {'GT':>5} {'GT>NK':>7}")
    print(f"  {'-'*38} {'-'*5} {'-'*5} {'-'*5} {'-'*7}")
    for r in results:
        nk = ('P' if r['naked']['certified'] else 'F') + str(r['naked']['attempts_needed'])
        sh = ('P' if r['shard']['certified'] else 'F') + str(r['shard']['attempts_needed'])
        gt = ('P' if r['gated']['certified'] else 'F') + str(r['gated']['attempts_needed'])
        bk = r['gated_meta']['difficulty_bucket'][0].upper()
        print(f"  [{bk}] {r['topic'][:36]:<36} {nk:>5} {sh:>5} {gt:>5} {r['winner_naked_vs_gated']:>7}")

    print(f"\n  {'':30} {'NAKED':>8} {'SHARD':>8} {'GATED':>8}")
    print(f"  {'Pass rate':<30} {n_cert}/{n}={100*n_cert//n}%  {s_cert}/{n}={100*s_cert//n}%  {g_cert}/{n}={100*g_cert//n}%")
    print(f"  {'Avg attempts':<30} {n_att:>8} {s_att:>8} {g_att:>8}")
    print(f"  {'Avg time (success)':<30} {str(n_t)+'s':>8} {str(s_t)+'s':>8} {str(g_t)+'s':>8}")

    print(f"\n  GATED vs NAKED: wins={gated_wins}  losses={naked_wins}  ties={ties}")
    print(f"\n  Segmentation (hard=pred<{GATE_THRESHOLD}, easy=pred>={GATE_THRESHOLD}):")
    print(f"    HARD topics ({len(hard)}): NAKED={_seg_cert(hard,'naked')}  SHARD={_seg_cert(hard,'shard')}  GATED={_seg_cert(hard,'gated')}")
    print(f"    EASY topics ({len(easy)}): NAKED={_seg_cert(easy,'naked')}  SHARD={_seg_cert(easy,'shard')}  GATED={_seg_cert(easy,'gated')}")

    print(f"\n  VERDETTO: {verdict}")
    print(f"{'='*62}\n")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _BACKEND / f"ab_results_{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts, "n_topics": n, "max_attempts": max_attempts,
            "gate_threshold": GATE_THRESHOLD,
            "summary": {
                "naked":  {"cert": n_cert, "pass_pct": round(100*n_cert/n,1), "avg_att": n_att, "avg_time": n_t},
                "shard":  {"cert": s_cert, "pass_pct": round(100*s_cert/n,1), "avg_att": s_att, "avg_time": s_t},
                "gated":  {"cert": g_cert, "pass_pct": round(100*g_cert/n,1), "avg_att": g_att, "avg_time": g_t},
                "gated_wins": gated_wins, "naked_wins": naked_wins, "ties": ties,
                "verdict": verdict,
                "hard_topics": len(hard), "easy_topics": len(easy),
            },
            "results": results,
        }, f, indent=2)
    print(f"  Salvato: {out}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topics", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS_DEFAULT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--topic", action="append", dest="manual_topics")
    args = parser.parse_args()

    if args.manual_topics:
        topics = args.manual_topics
    else:
        topics = pick_topics(args.topics, seed=args.seed)
        print(f"Topic selezionati ({len(topics)}): {topics[:10]}{'...' if len(topics)>10 else ''}\n")

    asyncio.run(main(topics, args.max_attempts))
