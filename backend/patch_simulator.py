"""patch_simulator.py — "What if" simulator for code patches.

Before applying a patch, SHARD simulates its impact:
  1. Finds which modules depend on the file being patched (via architecture_map)
  2. Runs static diff analysis (removed functions, changed signatures, new imports)
  3. Asks LLM to assess risk for each dependent module (parallel, Gemini Flash)
  4. Returns SimulationReport: risk_level, affected_modules, recommendation

Integration point: server.py calls simulate_patch() in approve_patch() before
writing the file — adds a risk assessment to the approval gate.

Example report:
    PatchSimulator: llm_router.py
    Dependents: study_agent, benchmark_loop, swarm_engine, night_runner (+4 more)
    Changes detected: function signature changed (llm_complete: providers param moved)
    Risk: HIGH — 8 dependent modules, breaking signature change
    Recommendation: apply_with_caution — run benchmarks after applying
"""
import ast
import asyncio
import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("shard.patch_simulator")

try:
    from architecture_map import ArchitectureMap
except ImportError:
    try:
        from backend.architecture_map import ArchitectureMap
    except ImportError:
        ArchitectureMap = None


# ── Report dataclass ──────────────────────────────────────────────────────────

@dataclass
class SimulationReport:
    file_path: str
    risk_level: str                  # LOW / MEDIUM / HIGH / CRITICAL
    recommendation: str              # apply / apply_with_caution / reject
    affected_modules: list[str]      # modules that depend on this file
    changes_detected: list[str]      # static diff findings
    module_risks: dict[str, str]     # module_name -> LLM risk assessment
    summary: str                     # one-paragraph human-readable summary
    simulated: bool = True           # False if simulation was skipped


# ── Static diff analysis ──────────────────────────────────────────────────────

def _extract_public_api(code: str) -> dict:
    """Extract public functions, classes, and their signatures from Python source."""
    api = {"functions": {}, "classes": {}}
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                args = [a.arg for a in node.args.args]
                api["functions"][node.name] = args
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                methods = [
                    n.name for n in ast.walk(node)
                    if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
                ]
                api["classes"][node.name] = methods
    except Exception:
        pass
    return api


def _analyze_diff(old_code: str, new_code: str, filename: str) -> list[str]:
    """Static analysis of what changed between old and new code.

    Returns a list of human-readable change descriptions.
    """
    findings = []

    # --- Line diff summary ---
    old_lines = old_code.splitlines()
    new_lines = new_code.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    added   = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    findings.append(f"Lines: +{added} added, -{removed} removed")

    # --- API comparison ---
    old_api = _extract_public_api(old_code)
    new_api = _extract_public_api(new_code)

    # Removed functions (breaking)
    removed_funcs = set(old_api["functions"]) - set(new_api["functions"])
    for fn in removed_funcs:
        findings.append(f"BREAKING: function '{fn}()' removed")

    # Signature changes (potentially breaking)
    for fn in set(old_api["functions"]) & set(new_api["functions"]):
        old_args = old_api["functions"][fn]
        new_args = new_api["functions"][fn]
        if old_args != new_args:
            findings.append(
                f"SIGNATURE CHANGE: '{fn}({', '.join(old_args)})' -> "
                f"'{fn}({', '.join(new_args)})'"
            )

    # Removed classes (breaking)
    removed_classes = set(old_api["classes"]) - set(new_api["classes"])
    for cls in removed_classes:
        findings.append(f"BREAKING: class '{cls}' removed")

    # Removed methods from existing classes
    for cls in set(old_api["classes"]) & set(new_api["classes"]):
        removed_methods = set(old_api["classes"][cls]) - set(new_api["classes"][cls])
        for m in removed_methods:
            findings.append(f"BREAKING: method '{cls}.{m}()' removed")

    # Import changes (may break dependents expecting specific symbols)
    old_imports = set(re.findall(r"^(?:from\s+\S+\s+)?import\s+(.+)$", old_code, re.MULTILINE))
    new_imports = set(re.findall(r"^(?:from\s+\S+\s+)?import\s+(.+)$", new_code, re.MULTILINE))
    added_imports   = new_imports - old_imports
    removed_imports = old_imports - new_imports
    if removed_imports:
        findings.append(f"Imports removed: {', '.join(list(removed_imports)[:3])}")
    if added_imports:
        findings.append(f"New imports: {', '.join(list(added_imports)[:3])}")

    return findings


# ── Dependency lookup via ArchitectureMap ─────────────────────────────────────

def _find_dependents(file_path: str) -> tuple[list[str], list[str]]:
    """Return (direct_dependents, all_affected) for a file path.

    direct_dependents: modules that explicitly depend_on this module
    all_affected:      direct + transitive (1 hop)
    """
    if ArchitectureMap is None:
        return [], []

    try:
        arch = ArchitectureMap()
        # Derive module name from file path (e.g. backend/llm_router.py → llm_router)
        module_name = Path(file_path).stem

        direct = arch.get_dependents(module_name)

        # 1-hop transitive: modules that depend on the direct dependents
        transitive = []
        for dep in direct:
            second_order = arch.get_dependents(dep)
            for mod in second_order:
                if mod not in direct and mod not in transitive and mod != module_name:
                    transitive.append(mod)

        return direct, direct + transitive
    except Exception as e:
        logger.warning("[PATCH_SIM] Dependency lookup failed: %s", e)
        return [], []


# ── LLM risk assessment ───────────────────────────────────────────────────────

async def _assess_module_risk(
    module_name: str,
    file_patched: str,
    changes: list[str],
    old_snippet: str,
    new_snippet: str,
) -> str:
    """Ask LLM to assess risk of this patch for a specific dependent module."""
    changes_str = "\n".join(f"  - {c}" for c in changes[:8])
    prompt = f"""A patch is being applied to '{file_patched}'. Assess the risk for module '{module_name}'.

Changes detected:
{changes_str}

Old code snippet (first 800 chars):
{old_snippet[:800]}

New code snippet (first 800 chars):
{new_snippet[:800]}

In 1-2 sentences, describe the specific risk to '{module_name}' from this patch.
If no real risk: say "LOW RISK: no breaking changes affect this module."
Be specific about what could break. No general statements."""

    try:
        from llm_router import llm_complete
        result = await llm_complete(
            prompt=prompt,
            system="You are a code impact analyst. Be concise and specific.",
            max_tokens=150,
            temperature=0.0,
            providers=["Gemini", "Groq"],
        )
        return result.strip()
    except Exception as e:
        return f"Assessment failed: {e}"


# ── Risk scoring ──────────────────────────────────────────────────────────────

def _compute_risk_level(
    changes: list[str],
    n_affected: int,
    module_risks: dict[str, str],
) -> tuple[str, str]:
    """Return (risk_level, recommendation) based on findings."""
    has_breaking = any("BREAKING" in c for c in changes)
    has_signature_change = any("SIGNATURE CHANGE" in c for c in changes)

    high_risk_modules = sum(
        1 for r in module_risks.values()
        if any(w in r.upper() for w in ["BREAK", "CRASH", "FAIL", "ERROR", "INCOMPATIBLE"])
    )

    if has_breaking and n_affected >= 3:
        return "CRITICAL", "reject"
    if has_breaking or (has_signature_change and n_affected >= 2):
        return "HIGH", "apply_with_caution"
    if has_signature_change or high_risk_modules >= 2:
        return "MEDIUM", "apply_with_caution"
    if n_affected >= 5:
        return "MEDIUM", "apply_with_caution"
    return "LOW", "apply"


def _build_summary(
    file_path: str,
    changes: list[str],
    affected: list[str],
    risk_level: str,
    recommendation: str,
    module_risks: dict[str, str],
) -> str:
    filename = Path(file_path).name
    breaking = [c for c in changes if "BREAKING" in c or "SIGNATURE" in c]
    lines = [
        f"PatchSimulator: {filename}",
        f"Dependents: {', '.join(affected[:5])}" + (f" (+{len(affected)-5} more)" if len(affected) > 5 else ""),
        f"Changes: {'; '.join(changes[:3])}",
    ]
    if breaking:
        lines.append(f"Breaking: {'; '.join(breaking[:2])}")
    lines.append(f"Risk: {risk_level} | Recommendation: {recommendation}")
    if module_risks:
        worst = [(m, r) for m, r in module_risks.items()
                 if "LOW RISK" not in r and "low risk" not in r.lower()]
        if worst:
            lines.append(f"Flagged: {worst[0][0]} — {worst[0][1][:80]}")
    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

async def simulate_patch(
    file_path: str,
    old_code: str,
    new_code: str,
    max_module_assessments: int = 4,
) -> SimulationReport:
    """Simulate impact of patching file_path from old_code to new_code.

    Args:
        file_path:               Path of the file being patched (for display + lookup).
        old_code:                Current content of the file.
        new_code:                Proposed new content.
        max_module_assessments:  Max modules to run LLM assessment on (keep API cost low).

    Returns SimulationReport.
    """
    logger.info("[PATCH_SIM] Simulating patch on: %s", file_path)

    # ── 1. Static diff ────────────────────────────────────────────────────────
    changes = _analyze_diff(old_code, new_code, file_path)
    logger.info("[PATCH_SIM] %d change(s) detected", len(changes))

    # ── 2. Find dependents ────────────────────────────────────────────────────
    direct, all_affected = _find_dependents(file_path)
    logger.info("[PATCH_SIM] Direct dependents: %s", direct)

    # ── 3. LLM risk assessment (parallel, capped) ─────────────────────────────
    modules_to_assess = direct[:max_module_assessments]  # prioritize direct deps
    module_risks: dict[str, str] = {}

    if modules_to_assess and changes:
        old_snippet = old_code[:800]
        new_snippet = new_code[:800]

        results = await asyncio.gather(
            *[_assess_module_risk(m, Path(file_path).name, changes, old_snippet, new_snippet)
              for m in modules_to_assess],
            return_exceptions=True,
        )
        for module_name, result in zip(modules_to_assess, results):
            if isinstance(result, Exception):
                module_risks[module_name] = f"Assessment error: {result}"
            else:
                module_risks[module_name] = result

    # ── 4. Risk scoring ───────────────────────────────────────────────────────
    risk_level, recommendation = _compute_risk_level(changes, len(all_affected), module_risks)

    # ── 5. Build report ───────────────────────────────────────────────────────
    summary = _build_summary(file_path, changes, all_affected, risk_level, recommendation, module_risks)
    logger.info("[PATCH_SIM] %s", summary.replace("\n", " | "))

    return SimulationReport(
        file_path=file_path,
        risk_level=risk_level,
        recommendation=recommendation,
        affected_modules=all_affected,
        changes_detected=changes,
        module_risks=module_risks,
        summary=summary,
    )


def simulate_patch_sync(
    file_path: str,
    old_code: str,
    new_code: str,
) -> SimulationReport:
    """Synchronous version — runs static analysis only (no LLM calls).

    Use when you need a quick risk estimate without awaiting.
    """
    changes = _analyze_diff(old_code, new_code, file_path)
    direct, all_affected = _find_dependents(file_path)
    risk_level, recommendation = _compute_risk_level(changes, len(all_affected), {})
    summary = _build_summary(file_path, changes, all_affected, risk_level, recommendation, {})

    return SimulationReport(
        file_path=file_path,
        risk_level=risk_level,
        recommendation=recommendation,
        affected_modules=all_affected,
        changes_detected=changes,
        module_risks={},
        summary=summary,
    )
