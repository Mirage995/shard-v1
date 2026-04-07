"""scaffold_guardrail.py -- Deterministic middleware between LLM output and execution.

Three-level validation:
  L1 (Syntax):    AST parse — catches broken code before any execution
  L2 (Security):  Blacklist of dangerous calls, network imports, filesystem escape
  L3 (Principle): SHARD invariant rules + principle keyword alignment

Usage:
    from scaffold_guardrail import GuardrailGate, GuardrailHardBlock

    gate = GuardrailGate(topic="binary search")
    result = gate.check(code)
    if not result.ok:
        # pass result.rejection_reason back to swarm as guardrail_constraint
        print(result.rejection_reason)
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional

# ── Protected filesystem paths ────────────────────────────────────────────────
# Code must not open() these in write mode, and must not reference them in
# write contexts.  Add entries here to expand protection.
_PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    "shard_memory/",
    "shard_memory\\",
    "backend/",
    "backend\\",
    "CLAUDE.md",
    "principles.json",
    "capability_graph.json",
    "identity.json",
)

# ── L2 Security blacklists ────────────────────────────────────────────────────

# Dotted call names that are always forbidden regardless of arguments
_FORBIDDEN_CALLS: frozenset[str] = frozenset({
    "os.system",
    "os.popen",
    "shutil.rmtree",
})

# Top-level module names whose import is forbidden (network / low-level I/O)
_FORBIDDEN_IMPORTS: frozenset[str] = frozenset({
    "socket",
    "requests",
    "urllib",
    "http",
    "ftplib",
    "smtplib",
    "telnetlib",
    "paramiko",
    "aiohttp",
    "httpx",
})

# Maximum guardrail retries before hard block (used by benchmark_loop)
MAX_GUARDRAIL_RETRIES: int = 2


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class GuardrailResult:
    ok: bool
    violations: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    level: Optional[str] = None   # "L1", "L2", "L3", or None if ok


class GuardrailHardBlock(RuntimeError):
    """Raised when code remains blocked after MAX_GUARDRAIL_RETRIES attempts."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_forbidden_import(module: str) -> bool:
    """True if the top-level module is in the forbidden set."""
    return module.split(".")[0] in _FORBIDDEN_IMPORTS


def _call_name(node: ast.Call) -> str:
    """Return dotted name of a Call node (e.g. 'os.system', 'eval')."""
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return f"{node.func.value.id}.{node.func.attr}"
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _check_open_write_protected(tree: ast.AST) -> list[str]:
    """Return violations for open() calls in write mode targeting protected paths."""
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "open":
            continue
        if not node.args:
            continue

        # Detect write mode from positional arg or keyword
        write_mode = False
        if len(node.args) >= 2:
            m = node.args[1]
            if isinstance(m, ast.Constant) and "w" in str(m.value):
                write_mode = True
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and "w" in str(kw.value.value):
                write_mode = True

        if not write_mode:
            continue

        # Check if path literal matches a protected prefix
        path_arg = node.args[0]
        if not isinstance(path_arg, ast.Constant) or not isinstance(path_arg.value, str):
            continue
        for protected in _PROTECTED_PATH_PREFIXES:
            if protected in path_arg.value:
                violations.append(f"L2 write to protected path: '{path_arg.value}'")
                break

    return violations


def _check_principle_alignment(code: str, topic: str) -> list[str]:
    """Keyword-based principle alignment — returns [HIGH] warnings only."""
    warnings = []
    try:
        try:
            from principle_engine import inject_principles
        except ImportError:
            from backend.principle_engine import inject_principles

        principles_text = inject_principles(topic)
        if not principles_text:
            return []

        for line in principles_text.splitlines():
            lower = line.lower()
            for kw in ("never", "must not", "avoid"):
                idx = lower.find(kw)
                if idx < 0:
                    continue
                fragment = lower[idx + len(kw): idx + len(kw) + 60].strip()
                words = [w for w in fragment.split() if len(w) > 3][:3]
                if len(words) < 3:
                    continue
                pattern = r"\b" + r"\W+".join(re.escape(w) for w in words) + r"\b"
                if re.search(pattern, code, re.IGNORECASE):
                    warnings.append(
                        f"[HIGH] L3 principle contradiction: code matches '{' '.join(words)}'"
                    )
    except Exception:
        pass
    return warnings


# ── Main gate ─────────────────────────────────────────────────────────────────

class GuardrailGate:
    """Three-level deterministic validator for LLM-generated code.

    Levels run in order; the first blocking violation stops evaluation.
    L1 and L2 are fast (AST only). L3 may call principle_engine (graceful
    degradation if unavailable).
    """

    def __init__(self, topic: str = "") -> None:
        self.topic = topic

    def check(self, code: str) -> GuardrailResult:
        # L1: syntax
        l1 = self._check_l1(code)
        if not l1.ok:
            return l1

        # L2: security (requires valid AST — L1 guarantees this)
        tree = ast.parse(code)
        l2 = self._check_l2(code, tree)
        if not l2.ok:
            return l2

        # L3: SHARD invariants + principle alignment
        return self._check_l3(code, tree)

    # ── Level 1 ──────────────────────────────────────────────────────────────

    def _check_l1(self, code: str) -> GuardrailResult:
        try:
            ast.parse(code)
            return GuardrailResult(ok=True)
        except SyntaxError as e:
            return GuardrailResult(
                ok=False,
                violations=[f"L1 syntax error: {e.msg} at line {e.lineno}"],
                rejection_reason=(
                    f"Syntax error at line {e.lineno}: {e.msg}. "
                    "Fix all syntax errors before producing output."
                ),
                level="L1",
            )

    # ── Level 2 ──────────────────────────────────────────────────────────────

    def _check_l2(self, code: str, tree: ast.AST) -> GuardrailResult:
        violations: list[str] = []

        # Forbidden imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_forbidden_import(module):
                    violations.append(f"L2 forbidden import: {module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden_import(alias.name):
                        violations.append(f"L2 forbidden import: {alias.name}")

        # Forbidden calls + subprocess shell=True + dynamic eval/exec
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)

            if name in _FORBIDDEN_CALLS:
                violations.append(f"L2 forbidden call: {name}()")

            if name in {"subprocess.run", "subprocess.Popen", "subprocess.call"}:
                for kw in node.keywords:
                    if (kw.arg == "shell"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value is True):
                        violations.append(f"L2 forbidden: {name}(shell=True)")

            if name in {"eval", "exec"} and node.args:
                if not isinstance(node.args[0], ast.Constant):
                    violations.append(f"L2 forbidden: {name}(dynamic_expr)")

        # open() write to protected path
        violations.extend(_check_open_write_protected(tree))

        if violations:
            return GuardrailResult(
                ok=False,
                violations=violations,
                rejection_reason=(
                    f"Security violation(s): {'; '.join(violations[:3])}. "
                    "Remove all: network imports, os.system/popen, subprocess shell=True, "
                    "dynamic eval/exec, and write access to shard_memory/ or backend/ paths."
                ),
                level="L2",
            )
        return GuardrailResult(ok=True)

    # ── Level 3 ──────────────────────────────────────────────────────────────

    def _check_l3(self, code: str, tree: ast.AST) -> GuardrailResult:
        violations: list[str] = []

        # Rule: no __builtins__ override
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__builtins__":
                        violations.append("L3 forbidden: __builtins__ override")

        # Rule: principle alignment (HIGH confidence only)
        for warning in _check_principle_alignment(code, self.topic):
            if "[HIGH]" in warning:
                violations.append(warning)

        if violations:
            return GuardrailResult(
                ok=False,
                violations=violations,
                rejection_reason=(
                    f"SHARD invariant violation(s): {'; '.join(violations[:3])}. "
                    "Do not override __builtins__ or violate active principles."
                ),
                level="L3",
            )
        return GuardrailResult(ok=True)
