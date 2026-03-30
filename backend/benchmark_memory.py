"""benchmark_memory.py -- Episodic memory for benchmark tasks.

Persiste la storia di ogni sessione su disco. Quando il flag
use_episodic_memory è attivo, SHARD inietta un Experience Summary
nel primo prompt -- così non ripete mai gli stessi errori.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

MEMORY_FILE = Path(__file__).parent.parent / "shard_memory" / "benchmark_episodes.json"


# ── I/O ───────────────────────────────────────────────────────────────────────

def _load_all() -> dict:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_all(data: dict):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def load_episodes(task_key: str) -> list:
    """Return past sessions for this task, oldest first."""
    return _load_all().get(task_key, [])


def save_episode(task_key: str, success: bool, total_attempts: int,
                 attempts: list, final_code: str = "",
                 kb_used: bool = False, kb_chars: int = 0):
    """Persist a condensed session record. Always called, regardless of flag."""
    data = _load_all()
    data.setdefault(task_key, [])

    record = {
        "run_id":         str(uuid.uuid4())[:8],
        "timestamp":      datetime.now().isoformat(timespec="seconds"),
        "success":        success,
        "total_attempts": total_attempts,
        "kb_used":        kb_used,
        "kb_chars":       kb_chars,
        "attempts": [
            {
                "attempt":      r.attempt,
                "mode":         "LLM SOLO" if r.attempt == 1 else "SHARD FEEDBACK",
                "syntax_valid": r.syntax_valid,
                "passed":       list(r.tests_passed),
                "failed":       list(r.tests_failed),
                # cap error summary to avoid bloating the file
                "error_summary": (r.error_summary or "")[:600],
            }
            for r in attempts
        ],
    }
    if success:
        record["winning_hint"] = _winning_hint(attempts)

    data[task_key].append(record)
    data[task_key] = data[task_key][-10:]   # keep last 10 sessions per task
    _save_all(data)


def build_experience_summary(episodes: list) -> str:
    """Build the block injected into the Attempt 1 prompt."""
    if not episodes:
        return ""

    lines = [
        f"╔═══ EPISODIC MEMORY -- {len(episodes)} past session(s) for this exact task ═══╗",
        "║  SHARD has already attempted this task. Study this history carefully.     ║",
        "╚═════════════════════════════════════════════════════════════════════════════╝",
        "",
    ]

    for i, ep in enumerate(episodes[-3:], 1):   # show last 3 sessions max
        status = "OK SUCCESS" if ep["success"] else f"FAIL FAILED after {ep['total_attempts']} attempts"
        lines.append(f"─── Session {i}  ({ep['timestamp'][:10]})  {status} ───")

        prev_passed: set = set()
        all_passed:  set = set()
        all_failed:  set = set()
        regressions: list = []

        for att in ep["attempts"]:
            curr_passed = set(att["passed"])
            curr_failed = set(att["failed"])
            all_passed.update(curr_passed)
            all_failed.update(curr_failed)

            lost = prev_passed - curr_passed
            if lost:
                regressions.append((att["attempt"], sorted(lost)))
            prev_passed = curr_passed

            mode = att.get("mode", "")
            p, f = len(att["passed"]), len(att["failed"])
            if not att.get("syntax_valid", True):
                lines.append(f"  Attempt {att['attempt']} [{mode}]: SYNTAX ERROR")
            else:
                lines.append(f"  Attempt {att['attempt']} [{mode}]: {p} passed / {f} failed")
            if att["failed"] and att.get("error_summary"):
                excerpt = att["error_summary"][:300].replace("\n", " ").strip()
                lines.append(f"    -> {excerpt}")

        if regressions:
            lines.append("  [WARN] REGRESSIONS (had it, then broke it):")
            for att_n, lost in regressions:
                lines.append(f"    Attempt {att_n} lost: {', '.join(lost)}")

        never = sorted(all_failed - all_passed)
        if never:
            lines.append(f"  FAIL Never solved: {', '.join(never)}")

        if ep.get("winning_hint"):
            lines.append(f"  OK What worked: {ep['winning_hint']}")

        lines.append("")

    lines += [
        "CRITICAL -- learn from the above before writing a single line of code:",
        "  • Do NOT repeat any approach that failed in a previous session.",
        "  • If you previously fixed some tests but regressed others, identify",
        "    the exact regression and fix it WITHOUT touching what was working.",
        "  • Tests listed as 'Never solved' are your primary target.",
        "═" * 72,
        "",
    ]
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def kb_impact_stats() -> dict:
    """Compare benchmark success rates with vs without KB context injection.

    Returns a dict with:
      - with_kb:    {runs, successes, success_rate, avg_attempts}
      - without_kb: {runs, successes, success_rate, avg_attempts}
      - delta_rate: success_rate(with) - success_rate(without)
    """
    all_data = _load_all()
    with_kb    = {"runs": 0, "successes": 0, "total_attempts": 0}
    without_kb = {"runs": 0, "successes": 0, "total_attempts": 0}

    for episodes in all_data.values():
        for ep in episodes:
            bucket = with_kb if ep.get("kb_used") else without_kb
            bucket["runs"] += 1
            bucket["total_attempts"] += ep.get("total_attempts", 1)
            if ep.get("success"):
                bucket["successes"] += 1

    def _stats(b):
        if b["runs"] == 0:
            return {"runs": 0, "successes": 0, "success_rate": None, "avg_attempts": None}
        return {
            "runs":         b["runs"],
            "successes":    b["successes"],
            "success_rate": round(b["successes"] / b["runs"], 3),
            "avg_attempts": round(b["total_attempts"] / b["runs"], 2),
        }

    s_with    = _stats(with_kb)
    s_without = _stats(without_kb)
    delta = None
    if s_with["success_rate"] is not None and s_without["success_rate"] is not None:
        delta = round(s_with["success_rate"] - s_without["success_rate"], 3)

    return {"with_kb": s_with, "without_kb": s_without, "delta_rate": delta}


def _winning_hint(attempts: list) -> str:
    if not attempts:
        return ""
    w = attempts[-1]
    return (
        f"Solved on attempt {w.attempt}. "
        f"Passing tests: {', '.join(list(w.tests_passed)[:6])}"
    )
