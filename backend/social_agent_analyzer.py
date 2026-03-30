"""social_agent_analyzer.py -- Local codebase analysis via SHARD StudyPipeline.

Entry-point script that builds a custom pipeline to analyze a local codebase
(default: ~/Desktop/social_agent) without internet access.

Pipeline:
  1. InitPhase           -- meta-learning hint + episodic context
  2. LocalDirMapPhase    -- read local files -> ctx.sources + ctx.raw_text
  3. SynthesizePhase     -- LLM extracts architecture + concepts from code
  4. CodeReviewSandboxPhase -- LLM proposes refactoring improvements
  5. CertifyRetryGroup   -- validates proposed fixes (VALIDATE->EVALUATE->CERTIFY)

Usage:
    python social_agent_analyzer.py                          # default path
    python social_agent_analyzer.py /path/to/any/codebase    # custom path
    python social_agent_analyzer.py --help
"""
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# ── Ensure backend is importable ──────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Also add project root for backend.* imports used by some phases
PROJECT_ROOT = BACKEND_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── Default codebase path ────────────────────────────────────────────────────
DEFAULT_CODEBASE = Path.home() / "Desktop" / "social_agent"


def resolve_codebase_path(arg: str = None) -> Path:
    """Resolve the target codebase path from CLI arg or default."""
    if arg:
        p = Path(arg).resolve()
    else:
        p = DEFAULT_CODEBASE.resolve()

    if not p.exists():
        print(f"[ERROR] Path not found: {p}")
        sys.exit(1)
    if not p.is_dir():
        print(f"[ERROR] Not a directory: {p}")
        sys.exit(1)
    return p


async def analyze_codebase(codebase_path: Path):
    """Build and execute the local analysis pipeline."""

    # ── Lazy imports (heavy deps) ─────────────────────────────────────────
    from study_agent import StudyAgent
    from study_context import StudyContext
    from study_pipeline import StudyPipeline
    from study_phases import InitPhase, SynthesizePhase
    from local_phases import LocalDirMapPhase, CodeReviewSandboxPhase, CodeReviewCertifyPhase
    from study_utils import ProgressTracker

    print()
    print("=" * 70)
    print(f"  SHARD Local Codebase Analyzer")
    print(f"  Target: {codebase_path}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    # ── Create StudyAgent (provides LLM engines + infrastructure) ─────────
    print("[INIT] Loading StudyAgent...")
    agent = StudyAgent()
    agent.is_running = True

    # Use codebase folder name as "topic" for the pipeline
    topic = f"Code Review: {codebase_path.name}"

    # ── Progress callback (prints to terminal) ────────────────────────────
    async def on_progress(phase, topic_name, score, msg, pct):
        pass  # ctx.emit already prints -- no double output

    async def on_error(topic_name, phase, error_msg):
        print(f"\n[ANALYZER ERROR] {phase}: {error_msg}\n")

    # ── Build StudyContext ────────────────────────────────────────────────
    progress = ProgressTracker()
    ctx = StudyContext(
        topic=topic,
        tier=1,
        agent=agent,
        progress=progress,
        on_progress=on_progress,
        on_error=on_error,
    )

    # ── Build custom pipeline ─────────────────────────────────────────────
    #
    # InitPhase           -- reuse: meta-learning + episodic context (non-critical if empty)
    # LocalDirMapPhase    -- NEW: reads local files instead of web scraping
    # SynthesizePhase     -- reuse: LLM extracts structured concepts from raw_text
    # CodeReviewSandboxPhase -- NEW: LLM proposes refactoring instead of demo code
    # CertifyRetryGroup   -- reuse: validates the analysis quality
    #
    # Skipped (not needed for local analysis):
    #   MapPhase, AggregatePhase  -- replaced by LocalDirMapPhase
    #   StorePhase                -- not persisting to ChromaDB
    #   CrossPollinatePhase       -- no cross-pollination needed
    #   MaterializePhase          -- no cheat sheet needed
    #   PostStudyPhase            -- no meta-learning update needed

    pipeline = StudyPipeline([
        InitPhase(),                                         # meta hints
        LocalDirMapPhase(str(codebase_path)),                # read local files
        SynthesizePhase(),                                   # extract architecture
        CodeReviewSandboxPhase(str(codebase_path)),          # code review + refactoring
        CodeReviewCertifyPhase(),                            # validate quality (no benchmark)
    ])

    print(f"[PIPELINE] Phases: {' -> '.join(repr(p) for p in pipeline.phases)}")
    print()

    # ── Execute ───────────────────────────────────────────────────────────
    try:
        score = await pipeline.execute(ctx)
    finally:
        await agent.browser_scraper._close()
        agent.is_running = False

    # ── Report ────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print(f"  ANALYSIS COMPLETE")
    print(f"  Codebase: {codebase_path.name}")
    print(f"  Files analyzed: {len(ctx.sources)}")
    print(f"  Score: {score}/10")
    print(f"  Certified: {'YES' if ctx.certified else 'NO'}")
    print("=" * 70)

    # Print review summary if available
    if ctx.sandbox_result and isinstance(ctx.sandbox_result, dict):
        review = ctx.sandbox_result.get("review_data", {})

        assessment = review.get("architecture_assessment", "")
        if assessment:
            print(f"\n{'─'*70}")
            print("ARCHITECTURE ASSESSMENT:")
            print(f"{'─'*70}")
            print(assessment)

        priorities = review.get("top_priorities", [])
        if priorities:
            print(f"\n{'─'*70}")
            print("TOP REFACTORING PRIORITIES:")
            print(f"{'─'*70}")
            for i, p in enumerate(priorities, 1):
                print(f"  {i}. {p}")

        issues = review.get("issues", [])
        if issues:
            print(f"\n{'─'*70}")
            print(f"ISSUES FOUND: {len(issues)}")
            print(f"{'─'*70}")
            for issue in issues:
                sev = issue.get("severity", "?").upper()
                cat = issue.get("category", "?")
                file = issue.get("file", "?")
                problem = issue.get("problem", "")
                print(f"  [{sev}] {file} ({cat})")
                print(f"         {problem}")
                if issue.get("fix_before") and issue.get("fix_after"):
                    print(f"         FIX: {issue['fix_before'][:80]}  ->  {issue['fix_after'][:80]}")
                print()

        # Show refactored file if generated
        refactored_file = ctx.sandbox_result.get("refactored_file")
        if refactored_file and ctx.codice_generato:
            print(f"{'─'*70}")
            print(f"REFACTORED FILE: {refactored_file}")
            print(f"{'─'*70}")
            print(f"  (Refactored code stored in ctx.codice_generato -- {len(ctx.codice_generato)} chars)")
            print(f"  To apply: review the diff and copy to {codebase_path / refactored_file}")

    print(f"\n  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return score


def main():
    """CLI entry point."""
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        sys.exit(0)

    codebase_arg = sys.argv[1] if len(sys.argv) > 1 else None
    codebase_path = resolve_codebase_path(codebase_arg)

    # Run the async pipeline
    score = asyncio.run(analyze_codebase(codebase_path))
    sys.exit(0 if score >= 7.5 else 1)


if __name__ == "__main__":
    main()
