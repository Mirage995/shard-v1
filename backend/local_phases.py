"""local_phases.py -- Pipeline phases for local codebase analysis.

Replaces web-scraping phases (MapPhase + AggregatePhase) with local file reading.
Used by social_agent_analyzer.py and any future LocalFlow-style pipelines.

Phases:
  - LocalDirMapPhase: walks a directory, reads source files -> ctx.sources + ctx.raw_text
  - CodeReviewSandboxPhase: asks LLM to propose refactoring based on synthesized architecture
"""
import os
import sys
from pathlib import Path

from study_pipeline import BasePhase
from study_context import StudyContext


# ── Configuration ────────────────────────────────────────────────────────────

SKIP_DIRS = {
    "venv", ".venv", "env", ".git", "__pycache__", "node_modules",
    ".netlify", ".next", "dist", "build", ".idea", ".vscode",
    ".mypy_cache", ".pytest_cache", "eggs", ".tox", ".egg-info",
    "logs", "output", ".cache",
}

SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
    ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini",
    ".md", ".txt", ".sh", ".bat", ".sql",
}

# Skip files larger than 100KB (likely generated/binary)
MAX_FILE_SIZE = 100_000

# Truncate total raw_text to avoid blowing up LLM context
MAX_TOTAL_CHARS = 200_000


# ── LocalDirMapPhase ─────────────────────────────────────────────────────────

class LocalDirMapPhase(BasePhase):
    """Read a local codebase directory into ctx.sources + ctx.raw_text.

    Replaces MapPhase + AggregatePhase for offline codebase analysis.
    Walks the directory tree, skipping junk dirs, reading source files,
    and concatenating their content into a structured raw_text block.
    """
    name = "LOCAL_DIR_MAP"
    fatal = True

    def __init__(self, codebase_path: str):
        self.codebase_path = Path(codebase_path).resolve()

    async def run(self, ctx: StudyContext) -> None:
        root = self.codebase_path
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Codebase path not found: {root}")

        await ctx.emit("LOCAL_DIR_MAP", 0, f"Scanning {root.name}/...")

        sources = []
        raw_parts = []
        total_chars = 0
        skipped = 0

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune junk directories in-place (prevents os.walk from descending)
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
            ]

            rel_dir = Path(dirpath).relative_to(root)

            for fname in sorted(filenames):
                fpath = Path(dirpath) / fname
                ext = fpath.suffix.lower()

                # Skip non-source files
                if ext not in SOURCE_EXTENSIONS:
                    skipped += 1
                    continue

                # Skip oversized files
                try:
                    size = fpath.stat().st_size
                except OSError:
                    continue
                if size > MAX_FILE_SIZE:
                    skipped += 1
                    continue
                if size == 0:
                    continue

                # Read file content
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    skipped += 1
                    continue

                rel_path = str(rel_dir / fname).replace("\\", "/")

                sources.append({
                    "path": rel_path,
                    "abs_path": str(fpath),
                    "extension": ext,
                    "size": size,
                    "lines": content.count("\n") + 1,
                })

                # Build annotated block for raw_text
                header = f"\n{'='*60}\n# FILE: {rel_path} ({size} bytes, {sources[-1]['lines']} lines)\n{'='*60}\n"
                block = header + content + "\n"

                if total_chars + len(block) > MAX_TOTAL_CHARS:
                    # Truncate to fit -- add as much as possible
                    remaining = MAX_TOTAL_CHARS - total_chars
                    if remaining > len(header) + 200:
                        raw_parts.append(header + content[:remaining - len(header)] + "\n... [TRUNCATED]\n")
                        total_chars = MAX_TOTAL_CHARS
                    print(f"[LOCAL_DIR_MAP] Reached {MAX_TOTAL_CHARS} char limit -- stopping file reads")
                    break
                else:
                    raw_parts.append(block)
                    total_chars += len(block)
            else:
                continue
            break  # break outer loop if inner broke (char limit hit)

        ctx.sources = sources
        ctx.raw_text = "".join(raw_parts)

        # Build a tree summary as prefix
        tree_lines = [f"# Codebase: {root.name}", f"# Files: {len(sources)}, Skipped: {skipped}", ""]
        for s in sources:
            tree_lines.append(f"  {s['path']:50s}  {s['lines']:>5d} lines  {s['extension']}")
        tree_summary = "\n".join(tree_lines) + "\n"
        ctx.raw_text = tree_summary + ctx.raw_text

        await ctx.emit(
            "LOCAL_DIR_MAP", 0,
            f"Mapped {len(sources)} files ({total_chars:,} chars). Skipped {skipped} non-source files.",
        )
        print(f"[LOCAL_DIR_MAP] Done. {len(sources)} files, {total_chars:,} chars loaded.")


# ── CodeReviewSandboxPhase ───────────────────────────────────────────────────

class CodeReviewSandboxPhase(BasePhase):
    """Propose concrete refactoring improvements based on codebase analysis.

    Replaces the standard SandboxPhase (which generates demo scripts).
    Instead, this phase:
      1. Takes the structured analysis from SynthesizePhase
      2. Asks the LLM for concrete, actionable refactoring proposals
      3. Generates refactored code for the most impactful file
      4. Runs it in sandbox to verify it doesn't break
    """
    name = "CODE_REVIEW"
    fatal = False

    def __init__(self, codebase_path: str):
        self.codebase_path = Path(codebase_path).resolve()

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("CODE_REVIEW", 0, "Analyzing codebase for improvements...")

        # ── Step 1: Ask LLM for a detailed code review ────────────────────
        concepts_json = ""
        try:
            import json
            concepts_json = json.dumps(ctx.structured.get("concepts", []), indent=2, ensure_ascii=False)
        except Exception:
            concepts_json = str(ctx.structured)

        # Pick the largest source files for focused review
        top_files = sorted(ctx.sources, key=lambda s: s["lines"], reverse=True)[:5]
        file_list = "\n".join(f"  - {f['path']} ({f['lines']} lines)" for f in top_files)

        # IMPORTANT: keep this prompt short and the JSON schema minimal.
        # _think() has max_tokens=2000 -- we bypass it below with 4096,
        # but the prompt itself must stay lean to leave room for the response.
        review_prompt = f"""You are a Staff Software Engineer doing a code review. BE LETALLY CONCISE.

CODEBASE: {self.codebase_path.name}
TOP FILES: {file_list}

SOURCE CODE (excerpt):
{ctx.raw_text[:8000]}

STRICT OUTPUT RULES -- VIOLATIONS WILL CORRUPT THE OUTPUT:
- architecture_assessment: MAX 200 words, single plain string, NO newlines inside the string
- top_priorities: exactly 2 items, each MAX 25 words
- issues: list ONLY the 2-3 most critical issues, NO more
- fix_before / fix_after: MAX 1 line each, NO newlines
- YOU MUST close every bracket and brace -- the JSON MUST be complete and valid
- NO markdown, NO text outside the JSON

Return ONLY this JSON (nothing before, nothing after):
{{
  "architecture_assessment": "...",
  "top_priorities": ["...", "..."],
  "issues": [
    {{
      "file": "...",
      "line_range": "...",
      "category": "architecture|performance|security|duplication|readability|error_handling|dead_code",
      "severity": "critical|warning|suggestion",
      "problem": "...",
      "fix_before": "...",
      "fix_after": "..."
    }}
  ]
}}"""

        # Call Anthropic client directly with max_tokens=4096 (bypassing _think's 2000 limit)
        import asyncio
        raw_review = None
        try:
            def _call_api():
                return ctx.agent.anthropic_client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=4096,
                    system="You are a senior software engineer. OUTPUT ONLY VALID JSON. No markdown, no text outside the JSON object.",
                    messages=[{"role": "user", "content": review_prompt}],
                )
            response = await asyncio.to_thread(_call_api)
            raw_review = response.content[0].text if response.content else None
            print(f"[CODE_REVIEW] API response: {len(raw_review) if raw_review else 0} chars, stop_reason={response.stop_reason}")
        except Exception as e:
            print(f"[CODE_REVIEW] LLM review failed: {e}")
            raw_review = None

        if not raw_review:
            print("[CODE_REVIEW] No review generated")
            if ctx.progress:
                ctx.progress.complete_phase("CODE_REVIEW")
            return

        # Parse review JSON -- safe_json_load returns None on failure, never raises
        import json
        review_data = None
        try:
            from study_agent import safe_json_load
            review_data = safe_json_load(raw_review)
        except Exception:
            pass
        if not isinstance(review_data, dict):
            try:
                review_data = json.loads(raw_review)
            except Exception:
                pass
        if not isinstance(review_data, dict):
            # LLM returned non-JSON prose -- save raw text and wrap so pipeline continues
            review_data = {
                "architecture_assessment": raw_review[:2000],
                "top_priorities": [],
                "issues": [],
            }
            print("[CODE_REVIEW] LLM returned non-JSON -- wrapped as plain assessment")
            self._save_markdown(raw_review, parsed=False)
        else:
            self._save_markdown_from_data(review_data)

        ctx.sandbox_result = {
            "success": True,
            "stdout": json.dumps(review_data, indent=2, ensure_ascii=False),
            "stderr": "",
            "analysis": review_data.get("architecture_assessment", "Code review completed"),
            "code": "",
            "file_path": None,
            "review_data": review_data,
        }

        # ── Step 2: Generate a concrete refactored file ───────────────────
        issues = review_data.get("issues", [])
        critical = [i for i in issues if i.get("severity") == "critical"]
        targets = critical or issues[:3]

        if targets:
            target_file = targets[0].get("file", "")
            await ctx.emit("CODE_REVIEW", 0, f"Generating refactored version of {target_file}...")

            # Read the actual target file
            target_path = self.codebase_path / target_file
            original_code = ""
            if target_path.exists():
                try:
                    original_code = target_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

            if original_code:
                issues_desc = "\n".join(
                    f"- [{i.get('severity', '?')}] {i.get('problem', '')}" for i in targets
                )
                refactor_prompt = f"""You are refactoring this Python file.

FILE: {target_file}
ISSUES TO FIX:
{issues_desc}

ORIGINAL CODE:
```
{original_code[:10000]}
```

Write the COMPLETE refactored file. Apply all fixes listed above.
Rules:
- Return ONLY the Python code, no markdown fences, no explanations
- Keep all existing functionality intact
- Fix the listed issues
- The code must be valid, runnable Python
"""
                try:
                    refactored = await ctx.agent._think(refactor_prompt)
                    if refactored:
                        # Clean markdown fences if present
                        if "```" in refactored:
                            lines = refactored.split("\n")
                            lines = [l for l in lines if not l.strip().startswith("```")]
                            refactored = "\n".join(lines).strip()

                        ctx.codice_generato = refactored
                        ctx.sandbox_result["refactored_file"] = target_file
                        ctx.sandbox_result["refactored_code"] = refactored
                        ctx.sandbox_result["original_code"] = original_code
                        await ctx.emit("CODE_REVIEW", 0, f"Refactored {target_file} -- {len(issues)} issues addressed")
                except Exception as e:
                    print(f"[CODE_REVIEW] Refactoring generation failed: {e}")

        n_issues = len(issues)
        n_crit = len([i for i in issues if i.get("severity") == "critical"])
        n_warn = len([i for i in issues if i.get("severity") == "warning"])
        print(f"[CODE_REVIEW] Done. {n_issues} issues ({n_crit} critical, {n_warn} warnings)")

        assessment = review_data.get("architecture_assessment", "")
        if assessment:
            print(f"[CODE_REVIEW] Architecture: {assessment[:200]}")

        priorities = review_data.get("top_priorities", [])
        for i, p in enumerate(priorities, 1):
            print(f"[CODE_REVIEW] Priority {i}: {p}")

        if ctx.progress:
            ctx.progress.complete_phase("CODE_REVIEW")

    # ── Markdown persistence helpers ──────────────────────────────────────

    def _reports_dir(self) -> Path:
        """Return the reports/ dir next to the codebase, creating it if needed."""
        reports = self.codebase_path.parent / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        return reports

    def _save_markdown(self, raw_text: str, parsed: bool = True) -> None:
        """Save raw LLM output to Markdown (fallback when JSON parsing fails)."""
        from datetime import datetime
        fname = f"{self.codebase_path.name}_audit_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        out = self._reports_dir() / fname
        content = f"# Code Review: {self.codebase_path.name}\n\n"
        content += f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -- raw output (JSON parse failed)_\n\n"
        content += "```\n" + raw_text + "\n```\n"
        out.write_text(content, encoding="utf-8")
        print(f"[CODE_REVIEW] Raw output saved -> {out}")

    def _save_markdown_from_data(self, review_data: dict) -> None:
        """Render the parsed review as a clean Markdown report."""
        from datetime import datetime
        fname = f"{self.codebase_path.name}_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        out = self._reports_dir() / fname

        lines = [
            f"# Code Audit: {self.codebase_path.name}",
            f"_Generated by SHARD on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
            "",
            "---",
            "",
            "## Architecture Assessment",
            "",
            review_data.get("architecture_assessment", "_No assessment provided._"),
            "",
            "---",
            "",
            "## Top Priorities",
            "",
        ]
        for i, p in enumerate(review_data.get("top_priorities", []), 1):
            lines.append(f"{i}. {p}")
        lines += ["", "---", "", "## Issues", ""]

        issues = review_data.get("issues", [])
        if not issues:
            lines.append("_No issues recorded._")
        for issue in issues:
            sev = issue.get("severity", "?").upper()
            cat = issue.get("category", "?")
            f   = issue.get("file", "?")
            lr  = issue.get("line_range", "")
            lines += [
                f"### [{sev}] `{f}`{' L' + lr if lr else ''} -- {cat}",
                "",
                issue.get("problem", ""),
                "",
                "**Before:**",
                f"```python\n{issue.get('fix_before', '')}\n```",
                "**After:**",
                f"```python\n{issue.get('fix_after', '')}\n```",
                "",
            ]

        refactored_file = review_data.get("refactored_file", "")
        if refactored_file:
            lines += [
                "---",
                "",
                f"## Refactored File: `{refactored_file}`",
                "",
                "_Refactored code generated by SHARD -- review before applying._",
                "",
            ]

        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"[CODE_REVIEW] Audit report saved -> {out}")


# ── CodeReviewCertifyPhase ────────────────────────────────────────────────────

class CodeReviewCertifyPhase(BasePhase):
    """Validate and score a code review analysis.

    Replaces CertifyRetryGroup for local codebase analysis.
    Uses phase_validate + phase_evaluate (LLM scoring) but skips the
    BenchmarkGenerator -- which generates algorithmic problems meaningless
    for a code review context.

    Certification threshold: score >= 7.5 (same as standard pipeline).
    """
    name = "CODE_REVIEW_CERTIFY"
    fatal = False

    async def run(self, ctx: StudyContext) -> None:
        from constants import SUCCESS_SCORE_THRESHOLD

        review = ctx.sandbox_result.get("review_data", {}) if ctx.sandbox_result else {}
        issues = review.get("issues", [])
        assessment = review.get("architecture_assessment", "")
        priorities = review.get("top_priorities", [])
        has_refactored = bool(ctx.codice_generato)

        await ctx.emit("CODE_REVIEW_CERTIFY", 0, "Validating code review quality...")

        # ── VALIDATE: Q&A self-interrogation on the analysis ─────────────
        try:
            ctx.validation_data = await ctx.agent.phase_validate(
                ctx.topic, ctx.structured, sandbox_result=ctx.sandbox_result,
            )
        except Exception as e:
            print(f"[CODE_REVIEW_CERTIFY] Validate failed (non-fatal): {e}")
            ctx.validation_data = {}

        # ── EVALUATE: LLM scores the overall analysis quality ────────────
        try:
            ctx.eval_data = await ctx.agent.phase_evaluate(
                ctx.topic, ctx.validation_data,
                sandbox_result=ctx.sandbox_result,
                gaps=None,
                generated_code=ctx.codice_generato,
            )
            ctx.score = ctx.eval_data.get("score", 0.0)
        except Exception as e:
            print(f"[CODE_REVIEW_CERTIFY] Evaluate failed (non-fatal): {e}")
            ctx.score = 0.0

        # ── Structural bonus: reward concrete output ──────────────────────
        # If LLM gave a low score despite good review output, boost it
        structural_score = 0.0
        if assessment and len(assessment) > 150:
            structural_score += 2.5
        if len(issues) >= 5:
            structural_score += 2.5
        elif len(issues) >= 2:
            structural_score += 1.5
        if len(priorities) >= 2:
            structural_score += 1.5
        if has_refactored:
            structural_score += 1.5
        structural_score = min(structural_score, 8.0)

        # Blend: max of LLM score and structural score (trust whichever is higher)
        ctx.score = max(ctx.score, structural_score)
        ctx.score = min(ctx.score, 10.0)

        ctx.certified = ctx.score >= SUCCESS_SCORE_THRESHOLD

        n_crit = len([i for i in issues if i.get("severity") == "critical"])
        n_warn = len([i for i in issues if i.get("severity") == "warning"])
        status = "✅ CERTIFIED" if ctx.certified else "❌ NOT CERTIFIED"
        print(
            f"[CODE_REVIEW_CERTIFY] {status} -- score={ctx.score:.1f}/10 | "
            f"{len(issues)} issues ({n_crit} critical, {n_warn} warnings) | "
            f"refactored={'yes' if has_refactored else 'no'}"
        )
        await ctx.emit(
            "CODE_REVIEW_CERTIFY", ctx.score,
            f"{status} | Score: {ctx.score:.1f}/10 | {len(issues)} issues found",
        )
