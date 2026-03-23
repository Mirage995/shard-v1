"""concurrency_simulator.py — Pre-pytest stress test for concurrency bugs.

Run AFTER code generation, BEFORE pytest, on concurrency-sensitive tasks.
Executes generated code under heavy thread stress in an isolated subprocess.
Returns a structured report that is injected into the next repair prompt.

Integration point: benchmark_loop.py calls `probe_concurrency()` when the task
is detected as concurrency-sensitive (README or test file contains threading keywords).

Example output injected into repair prompt:
    ⚡ CONCURRENCY PROBE — Race condition detected in Bank.deposit():
       Expected balance: 50000.00, Got: 49870.00 (lost: 130.00)
       Probe: 50 threads × 100 deposits × $10 = $50000 expected
       Hint: use threading.Lock() or RLock to protect balance updates.
"""
import ast
import importlib.util
import logging
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("shard.concurrency_simulator")

# ── Detection keywords ────────────────────────────────────────────────────────

_CONCURRENCY_KEYWORDS = [
    "threading", "thread", "race", "lock", "concurrent",
    "deadlock", "synchroni", "mutex", "atomic",
]

_BANK_KEYWORDS = ["bank", "account", "balance", "deposit", "withdraw", "transfer"]


@dataclass
class ConcurrencyReport:
    triggered: bool           # True if simulator actually ran (task was detected as concurrent)
    passed: bool              # True if all probes passed
    summary: str              # Human-readable summary (injected into repair prompt)
    details: list[str]        # Individual probe results
    hint: str = ""            # Specific fix suggestion


# ── Detection ─────────────────────────────────────────────────────────────────

def is_concurrency_task(readme: str, tests_source: str) -> bool:
    """Return True if task likely involves threading/concurrency."""
    combined = (readme + "\n" + tests_source).lower()
    return any(kw in combined for kw in _CONCURRENCY_KEYWORDS)


def is_bank_like(tests_source: str, class_name: str = None) -> bool:
    """Return True if task is a bank/account-style concurrency problem."""
    combined = (tests_source + (class_name or "")).lower()
    return sum(1 for kw in _BANK_KEYWORDS if kw in combined) >= 2


# ── Probe runners (subprocess-isolated) ───────────────────────────────────────

_BANK_PROBE_SCRIPT = """\
import sys
import threading
sys.path.insert(0, {code_dir!r})
{import_stmt}

errors = []

# ── Probe 1: Concurrent deposits ────────────────────────────────────────────
def probe_deposits():
    bank = {class_name}()
    bank.create_account("shared", 0)

    n_threads = 50
    n_deposits = 100
    amount = 10.0
    import sys as _sys
    old = _sys.getswitchinterval()
    _sys.setswitchinterval(1e-6)

    try:
        def worker():
            for _ in range(n_deposits):
                bank.deposit("shared", amount)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=15)
        alive = [t for t in threads if t.is_alive()]
    finally:
        _sys.setswitchinterval(old)

    if alive:
        errors.append("PROBE_DEPOSITS: TIMEOUT — threads still alive after 15s")
        return

    expected = n_threads * n_deposits * amount
    actual = bank.get_balance("shared")
    if abs(actual - expected) > 0.001:
        errors.append(
            f"PROBE_DEPOSITS: RACE - expected {{expected:.2f}}, got {{actual:.2f}}"
            f" (diff: {{actual - expected:+.2f}})"
        )
    else:
        errors.append("PROBE_DEPOSITS: OK")

# ── Probe 2: Money conservation under concurrent transfers ──────────────────
def probe_conservation():
    bank = {class_name}()
    n_accounts = 10
    initial = 1000.0
    for i in range(n_accounts):
        bank.create_account(f"acc_{{i}}", initial)
    total_before = bank.total_funds()

    import random, sys as _sys
    old = _sys.getswitchinterval()
    _sys.setswitchinterval(1e-6)

    try:
        def worker():
            rng = random.Random(threading.current_thread().ident)
            for _ in range(200):
                a = f"acc_{{rng.randint(0, n_accounts-1)}}"
                b = f"acc_{{rng.randint(0, n_accounts-1)}}"
                if a != b:
                    try:
                        bank.transfer(a, b, rng.uniform(1, 50))
                    except (ValueError, KeyError):
                        pass

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=15)
        alive = [t for t in threads if t.is_alive()]
    finally:
        _sys.setswitchinterval(old)

    if alive:
        errors.append("PROBE_CONSERVATION: TIMEOUT — possible deadlock")
        return

    total_after = bank.total_funds()
    diff = abs(total_after - total_before)
    if diff > 0.01:
        errors.append(
            f"PROBE_CONSERVATION: MONEY LEAK - before={{total_before:.2f}}"
            f" after={{total_after:.2f}} (diff={{diff:+.2f}})"
        )
    else:
        errors.append("PROBE_CONSERVATION: OK")

# ── Probe 3: Deadlock detection ──────────────────────────────────────────────
def probe_deadlock():
    bank = {class_name}()
    bank.create_account("X", 100000.0)
    bank.create_account("Y", 100000.0)

    import sys as _sys
    old = _sys.getswitchinterval()
    _sys.setswitchinterval(1e-6)

    try:
        def x_to_y():
            for _ in range(500):
                try: bank.transfer("X", "Y", 1)
                except ValueError: pass

        def y_to_x():
            for _ in range(500):
                try: bank.transfer("Y", "X", 1)
                except ValueError: pass

        threads = [threading.Thread(target=x_to_y), threading.Thread(target=y_to_x),
                   threading.Thread(target=x_to_y), threading.Thread(target=y_to_x)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)
        alive = [t for t in threads if t.is_alive()]
    finally:
        _sys.setswitchinterval(old)

    if alive:
        errors.append(
            f"PROBE_DEADLOCK: DEADLOCK - {{len(alive)}} threads still alive after 10s. "
            "Use consistent lock ordering (sort account ids before acquiring locks)."
        )
    else:
        errors.append("PROBE_DEADLOCK: OK")

probe_deposits()
probe_conservation()
probe_deadlock()

for e in errors:
    print(e)
"""


def _run_bank_probes(code_path: Path, class_name: str) -> list[str]:
    """Run bank probes in an isolated subprocess. Returns list of probe result lines."""
    script = _BANK_PROBE_SCRIPT.format(
        code_dir=str(code_path.parent),
        import_stmt=f"from {code_path.stem} import {class_name}",
        class_name=class_name,
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(script)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        lines = (result.stdout + result.stderr).strip().splitlines()
        return [l.strip() for l in lines if l.strip()]
    except subprocess.TimeoutExpired:
        return ["PROBE: GLOBAL TIMEOUT — simulator exceeded 60s"]
    except Exception as e:
        return [f"PROBE: RUNNER ERROR — {e}"]
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass


def _detect_class_name(code: str, fallback: str = "Bank") -> str:
    """Extract first class name from generated code."""
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                return node.name
    except Exception:
        pass
    return fallback


# ── Main entry point ──────────────────────────────────────────────────────────

def probe_concurrency(
    code: str,
    code_path: Path,
    readme: str,
    tests_source: str,
) -> ConcurrencyReport:
    """Run concurrency probes on generated code.

    Called by benchmark_loop after writing the file, before running pytest.
    Returns ConcurrencyReport — if triggered=False, no probes ran (task not concurrent).

    Args:
        code:         Generated Python source code (as string).
        code_path:    Path where the generated code was written.
        readme:       Task README content.
        tests_source: Test file content.
    """
    if not is_concurrency_task(readme, tests_source):
        return ConcurrencyReport(
            triggered=False, passed=True,
            summary="", details=[],
        )

    logger.info("[CONC_SIM] Concurrency task detected — running probes on %s", code_path.name)

    # Bank-style probe
    if is_bank_like(tests_source):
        class_name = _detect_class_name(code)
        raw_results = _run_bank_probes(code_path, class_name)

        failures = [r for r in raw_results if "RACE" in r or "TIMEOUT" in r
                    or "DEADLOCK" in r or "LEAK" in r or "ERROR" in r]
        oks      = [r for r in raw_results if r.endswith(": OK")]

        passed = len(failures) == 0

        if passed:
            summary = f"[CONC_SIM] All {len(oks)} probes passed. Code is thread-safe."
            hint = ""
        else:
            hint = _build_hint(failures)
            lines = ["[CONC_SIM] ISSUES DETECTED - Race conditions found:"]
            for f in failures:
                lines.append(f"   >> {f}")
            if oks:
                lines.append(f"   OK: {', '.join(o.split(':')[0] for o in oks)}")
            lines.append(f"   FIX: {hint}")
            summary = "\n".join(lines)

        return ConcurrencyReport(
            triggered=True, passed=passed,
            summary=summary, details=raw_results, hint=hint,
        )

    # Generic task: no specific probe available
    return ConcurrencyReport(
        triggered=True, passed=True,
        summary="[CONC_SIM] No bank-style probe available for this task.",
        details=[],
    )


def _build_hint(failures: list[str]) -> str:
    """Generate a targeted fix hint based on what probes failed."""
    hints = []

    if any("RACE" in f and "DEPOSITS" in f for f in failures):
        hints.append(
            "Use threading.Lock() to protect deposit/withdraw: "
            "read-modify-write on self._balances is not atomic."
        )
    if any("DEADLOCK" in f for f in failures):
        hints.append(
            "Deadlock in transfer(): acquire locks in SORTED order "
            "(sort account ids before locking both) to prevent circular waits."
        )
    if any("LEAK" in f or "CONSERVATION" in f for f in failures):
        hints.append(
            "Money conservation violated: ensure debit and credit happen atomically "
            "under the same lock, with no possibility of partial update."
        )

    return " | ".join(hints) if hints else "Add threading.Lock() to all balance-modifying methods."


# ── Prompt injection helper ────────────────────────────────────────────────────

def format_for_prompt(report: ConcurrencyReport) -> str:
    """Format report as a block to inject into the repair prompt.

    Returns empty string if report was not triggered or passed cleanly.
    """
    if not report.triggered or report.passed:
        return ""
    return f"\n{report.summary}\n"
