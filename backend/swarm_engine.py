"""swarm_engine.py — Multi-agent pipeline: Architect → Coder → Multi-Reviewer.

Pipeline:
  1. Architect   — analyzes failure history, produces strategy document
  2. Coder       — implements the strategy
  3. Reviewers   — parallel specialized critics (Security, Concurrency, Edge Cases,
                   Performance, Maintainability) — only relevant ones are activated
  4. Coder patch — if reviewers find critical issues, Coder applies fixes

Reviewer selection is automatic based on task content keywords.
All reviewers use Gemini Flash (fast + free) to keep API costs low.

Usage (via benchmark_loop):
    from swarm_engine import swarm_complete
    code = await swarm_complete(source, tests, attempts, output_filename)
"""
import ast
import asyncio
import logging
import re
from dataclasses import dataclass

try:
    from llm_router import llm_complete
except ImportError:
    from backend.llm_router import llm_complete

logger = logging.getLogger("shard.swarm_engine")

# ── System prompts ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT_ARCHITECT = (
    "You are a software architect analyzing failed code repair attempts. "
    "Your job is to produce a STRATEGY DOCUMENT — plain text, no code. "
    "The document must answer these questions: "
    "1. Root cause: why did every attempt fail? Be specific about which tests failed and why. "
    "2. Pattern: did the fixes break previously passing tests? If yes, explain the regression pattern. "
    "3. Strategy: what is the single most important change needed to fix ALL failing tests without breaking any passing ones? "
    "4. Constraints: list explicit things the Coder must NOT change (to prevent regressions). "
    "Output only the strategy document. No code. No markdown. Plain text."
)

SYSTEM_PROMPT_CODER = (
    "You are a precise Python implementation agent. "
    "You receive a strategy document from an Architect and must implement it exactly. "
    "Output ONLY valid Python source code. "
    "No markdown fences, no explanations, no commentary. "
    "Every function must be fully implemented — no ellipsis, no pass, no TODO. "
    "Follow the Architect's constraints explicitly: if the strategy says 'do not change X', do not change X."
)

SYSTEM_PROMPT_CRITIC = (
    "You are a strict Python code reviewer. "
    "You receive code and the tests it must pass. "
    "Your job: find any reason the code would FAIL the tests. "
    "Check for: syntax errors, missing imports, wrong function signatures, off-by-one errors, "
    "incorrect logic, missing edge case handling. "
    "If the code looks correct, respond with exactly: APPROVED "
    "If there are problems, respond with: ISSUES FOUND "
    "followed by a numbered list of specific, actionable problems. Be precise — line numbers if possible. "
    "Do NOT rewrite the code. Only report."
)


# ── Specialized reviewer definitions ────────────────────────────────────────────

@dataclass
class ReviewerSpec:
    name: str
    trigger_keywords: list[str]   # activate if ANY keyword found in tests+source
    system_prompt: str
    max_tokens: int = 400


_REVIEWERS: list[ReviewerSpec] = [
    ReviewerSpec(
        name="Concurrency",
        trigger_keywords=["thread", "lock", "concurrent", "race", "asyncio", "semaphore", "atomic"],
        system_prompt=(
            "You are a concurrency expert reviewing Python code. "
            "Focus ONLY on: race conditions, deadlocks, missing locks, non-atomic read-modify-write, "
            "incorrect lock ordering, shared state mutation without synchronization. "
            "If none found: respond exactly 'CONCURRENCY: APPROVED'. "
            "Otherwise: 'CONCURRENCY: ISSUES' followed by numbered list. No code rewrites."
        ),
    ),
    ReviewerSpec(
        name="EdgeCases",
        trigger_keywords=["none", "null", "empty", "zero", "negative", "overflow", "boundary", "invalid"],
        system_prompt=(
            "You are an edge-case specialist reviewing Python code. "
            "Focus ONLY on: None/null inputs, empty collections, zero/negative values, "
            "integer overflow, boundary conditions, missing validation, unhandled exceptions. "
            "If none found: respond exactly 'EDGE_CASES: APPROVED'. "
            "Otherwise: 'EDGE_CASES: ISSUES' followed by numbered list. No code rewrites."
        ),
    ),
    ReviewerSpec(
        name="Security",
        trigger_keywords=["password", "token", "auth", "sql", "inject", "exec", "eval", "subprocess", "pickle"],
        system_prompt=(
            "You are a security expert reviewing Python code. "
            "Focus ONLY on: SQL injection, command injection, unsafe eval/exec, "
            "hardcoded secrets, path traversal, insecure deserialization, missing input sanitization. "
            "If none found: respond exactly 'SECURITY: APPROVED'. "
            "Otherwise: 'SECURITY: ISSUES' followed by numbered list. No code rewrites."
        ),
    ),
    ReviewerSpec(
        name="Performance",
        trigger_keywords=["performance", "speed", "slow", "optimize", "cache", "n^2", "o(n)", "large", "scale"],
        system_prompt=(
            "You are a performance expert reviewing Python code. "
            "Focus ONLY on: O(n^2) or worse algorithms where O(n) is possible, "
            "unnecessary repeated computation, missing caching, inefficient data structures. "
            "If none found: respond exactly 'PERFORMANCE: APPROVED'. "
            "Otherwise: 'PERFORMANCE: ISSUES' followed by numbered list. No code rewrites."
        ),
    ),
    ReviewerSpec(
        name="DataIntegrity",
        trigger_keywords=["bank", "balance", "money", "transaction", "transfer", "account", "fund", "conserve"],
        system_prompt=(
            "You are a data integrity expert reviewing Python code for financial/transactional systems. "
            "Focus ONLY on: money conservation violations, partial updates (debit without credit), "
            "balance going negative, non-atomic transactions, missing rollback on failure. "
            "If none found: respond exactly 'DATA_INTEGRITY: APPROVED'. "
            "Otherwise: 'DATA_INTEGRITY: ISSUES' followed by numbered list. No code rewrites."
        ),
    ),
]


def _select_reviewers(source: str, tests: str) -> list[ReviewerSpec]:
    """Activate only reviewers whose trigger keywords appear in source+tests."""
    combined = (source + "\n" + tests).lower()
    selected = []
    for spec in _REVIEWERS:
        if any(kw in combined for kw in spec.trigger_keywords):
            selected.append(spec)
            logger.debug("[SWARM] Reviewer '%s' activated", spec.name)
    return selected


def _build_reviewer_prompt(code: str, tests: str, spec: ReviewerSpec) -> str:
    return f"""Review this Python code from the perspective of {spec.name}.

=== CODE ===
{code}

=== TESTS (for context) ===
{tests[:2000]}

{spec.system_prompt.split('If none found')[0].strip()}
Respond now."""


def _build_patch_prompt(
    code: str, source: str, reviewer_findings: list[tuple[str, str]], output_filename: str
) -> str:
    findings_block = "\n\n".join(
        f"[{name}]\n{finding}" for name, finding in reviewer_findings
    )
    return f"""Specialized reviewers found CRITICAL issues in your code. Apply all fixes now.

=== REVIEWER FINDINGS ===
{findings_block}

=== YOUR CODE (apply fixes to this) ===
{code}

=== ORIGINAL SOURCE (reference) ===
{source}

Fix ALL reported issues. Output the COMPLETE corrected {output_filename}. Raw Python only."""


# ── Code extraction (idempotent — safe to call on already-clean code) ───────────

def _extract_code(response: str) -> str:
    """Extract Python code from LLM response, stripping markdown fences."""
    fence_match = re.search(r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    try:
        ast.parse(response)
        return response.strip()
    except SyntaxError:
        pass

    lines = response.strip().splitlines()
    cleaned = []
    for line in lines:
        if line.startswith("```") or line.startswith("Here"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


# ── Prompt builders ─────────────────────────────────────────────────────────────

def _build_architect_prompt(source: str, tests: str, attempts: list, output_filename: str) -> str:
    history_parts = []
    for rec in attempts:
        if not rec.syntax_valid:
            history_parts.append(
                f"--- Attempt {rec.attempt} --- SYNTAX ERROR ---\n{rec.error_summary}"
            )
        else:
            passed_str = ", ".join(rec.tests_passed) if rec.tests_passed else "(none)"
            failed_str = ", ".join(rec.tests_failed) if rec.tests_failed else "(none)"
            history_parts.append(
                f"--- Attempt {rec.attempt} ---\n"
                f"Passed: {passed_str}\n"
                f"Failed: {failed_str}\n"
                f"Errors:\n{rec.error_summary}"
            )
    history = "\n\n".join(history_parts)

    # GraphRAG: inject causal warnings from previous studies
    causal_block = ""
    try:
        from graph_rag import query_causal_context
        # Query using test file content keywords + source code keywords
        combined_keywords = f"{output_filename} {source[:500]} {tests[:500]}"
        causal = query_causal_context(combined_keywords)
        if causal:
            causal_block = f"\n=== CAUSAL KNOWLEDGE (from SHARD's previous studies) ===\n{causal}\n"
            logger.info("[SWARM] Injected %d lines of causal context into Architect prompt",
                        causal.count("\n") + 1)
    except Exception as e:
        logger.debug("[SWARM] GraphRAG query skipped: %s", e)

    return f"""Analyze the following failed benchmark task and produce a strategy document.

=== SOURCE CODE (reference — do NOT optimize unless explicitly needed) ===
{source}

=== TEST FILE (all tests must pass) ===
{tests}

=== FAILURE HISTORY ({len(attempts)} attempts) ===
{history}
{causal_block}
Produce your STRATEGY DOCUMENT now."""


def _build_coder_prompt(
    source: str, current_code: str, strategy: str, output_filename: str, attempts: list
) -> str:
    best = max(attempts, key=lambda a: len(a.tests_passed)) if attempts else None
    guard_block = ""
    if best and best.tests_passed:
        guard_list = "\n".join(f"  - {t}" for t in sorted(best.tests_passed))
        guard_block = f"""
=== PASSING TESTS TO PRESERVE (from best attempt — do NOT regress these) ===
{guard_list}
"""

    return f"""Implement the Architect's strategy to produce a corrected {output_filename}.

=== ARCHITECT STRATEGY ===
{strategy}

=== ORIGINAL SOURCE (reference) ===
{source}

=== YOUR PREVIOUS BEST CODE (start from this, apply strategy) ===
{current_code}
{guard_block}
Write the COMPLETE corrected {output_filename}. Raw Python only, no markdown."""


def _build_critic_prompt(code: str, tests: str, output_filename: str) -> str:
    return f"""Review this Python file ({output_filename}) against the tests below.

=== CODE TO REVIEW ===
{code}

=== TESTS IT MUST PASS ===
{tests}

Is the code correct? Respond with APPROVED or ISSUES FOUND + numbered list."""


# ── Main entry point ────────────────────────────────────────────────────────────

async def swarm_complete(
    source: str,
    tests: str,
    attempts: list,
    output_filename: str,
    max_tokens: int = 8192,
    temperature: float = 0.05,
) -> str:
    """Multi-agent pipeline: Architect → Coder → Multi-Reviewer → (Coder patch if needed).

    Returns raw Python code string ready for syntax validation by benchmark_loop.
    Raises on LLM failure so benchmark_loop can record it as a normal failed attempt.

    Args:
        source:          Original source code (reference, never modified).
        tests:           Full test file content.
        attempts:        list[AttemptRecord] from benchmark_loop — full history.
        output_filename: e.g. "fixed_pipeline.py"
        max_tokens:      Forwarded to Coder calls only.
        temperature:     Forwarded to Coder calls only.
    """
    logger.info("[SWARM] Starting pipeline (%d prior attempts)", len(attempts))

    # Always start Coder from last syntactically valid code, never from broken code
    last_valid = next((r for r in reversed(attempts) if r.syntax_valid), None)
    current_code = last_valid.code if last_valid else source

    # ── Step 1: Architect ────────────────────────────────────────────────────
    architect_prompt = _build_architect_prompt(source, tests, attempts, output_filename)
    strategy = await llm_complete(
        prompt=architect_prompt,
        system=SYSTEM_PROMPT_ARCHITECT,
        max_tokens=1024,
        temperature=0.1,
    )
    logger.info("[SWARM] Architect OK (%d chars)", len(strategy))

    # ── Step 2: Coder ────────────────────────────────────────────────────────
    coder_prompt = _build_coder_prompt(
        source, current_code, strategy, output_filename, attempts
    )
    raw_code = await llm_complete(
        prompt=coder_prompt,
        system=SYSTEM_PROMPT_CODER,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    code = _extract_code(raw_code)
    logger.info("[SWARM] Coder OK (%d chars)", len(code))

    # ── Step 3: Critic (baseline) ────────────────────────────────────────────
    critic_prompt = _build_critic_prompt(code, tests, output_filename)
    verdict = await llm_complete(
        prompt=critic_prompt,
        system=SYSTEM_PROMPT_CRITIC,
        max_tokens=512,
        temperature=0.0,
    )
    logger.info("[SWARM] Critic verdict: %s", verdict[:80])

    # ── Step 4: Multi-reviewer (parallel specialized critics) ─────────────────
    active_reviewers = _select_reviewers(source, tests)
    logger.info("[SWARM] Activating %d specialized reviewer(s): %s",
                len(active_reviewers), [r.name for r in active_reviewers])

    critical_findings: list[tuple[str, str]] = []

    if active_reviewers:
        # Run all active reviewers in parallel with Gemini Flash (free tier)
        async def _run_reviewer(spec: ReviewerSpec) -> tuple[str, str]:
            prompt = _build_reviewer_prompt(code, tests, spec)
            try:
                # Use cache for reviewers — same code structure often gets same review
                try:
                    from llm_cache import cached_llm_complete
                    result = await cached_llm_complete(
                        prompt=prompt,
                        system=spec.system_prompt,
                        max_tokens=spec.max_tokens,
                        temperature=0.0,
                        providers=["Gemini", "Groq"],
                    )
                except ImportError:
                    result = await llm_complete(
                        prompt=prompt,
                        system=spec.system_prompt,
                        max_tokens=spec.max_tokens,
                        temperature=0.0,
                        providers=["Gemini", "Groq"],
                    )
                return spec.name, result.strip()
            except Exception as exc:
                logger.warning("[SWARM] Reviewer '%s' failed: %s", spec.name, exc)
                return spec.name, f"{spec.name.upper()}: APPROVED"  # fail-open

        reviewer_results = await asyncio.gather(
            *[_run_reviewer(spec) for spec in active_reviewers]
        )

        for name, finding in reviewer_results:
            approved_marker = f"{name.upper().replace(' ', '_')}: APPROVED"
            if "APPROVED" not in finding.upper():
                critical_findings.append((name, finding))
                logger.warning("[SWARM] Reviewer '%s' found issues:\n%s", name, finding[:200])
            else:
                logger.info("[SWARM] Reviewer '%s': APPROVED", name)

    # ── Step 5: Coder patch (only if reviewers found critical issues) ─────────
    if critical_findings:
        logger.info("[SWARM] %d reviewer(s) flagged issues — running Coder patch", len(critical_findings))
        patch_prompt = _build_patch_prompt(code, source, critical_findings, output_filename)
        try:
            patched_raw = await llm_complete(
                prompt=patch_prompt,
                system=SYSTEM_PROMPT_CODER,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            patched_code = _extract_code(patched_raw)
            if patched_code and len(patched_code) > 50:
                code = patched_code
                logger.info("[SWARM] Coder patch applied (%d chars)", len(code))
            else:
                logger.warning("[SWARM] Coder patch returned empty/short code — keeping original")
        except Exception as exc:
            logger.warning("[SWARM] Coder patch failed: %s — keeping Coder output", exc)
    else:
        logger.info("[SWARM] All reviewers approved — no patch needed")

    return code
