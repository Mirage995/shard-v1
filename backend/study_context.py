"""study_context.py — Mutable state bag for the SHARD study pipeline.

StudyContext flows through every phase of the pipeline.
Each phase reads what it needs and writes its outputs — no phase
needs to know about any other phase, only about the context fields.
"""
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class StudyContext:
    """Accumulated state for a single study_topic() run.

    Phases read inputs and write outputs on this object.
    The pipeline orchestrator never inspects phase-specific fields —
    it only calls phase.run(ctx) and checks ctx.certified / ctx.score.
    """

    # ── Input (set once at creation) ──────────────────────────────────────────
    topic: str = ""
    tier: int = 1
    agent: Any = None                          # back-reference to StudyAgent
    progress: Any = None                       # ProgressTracker instance
    previous_score: Optional[float] = None

    # ── Callbacks (set once at creation) ──────────────────────────────────────
    on_progress: Optional[Callable] = None
    on_certify: Optional[Callable] = None
    on_error: Optional[Callable] = None
    on_web_data: Optional[Callable] = None

    # ── Phase outputs — accumulated as the pipeline runs ─────────────────────
    sources: List[Dict] = field(default_factory=list)
    raw_text: str = ""
    structured: Dict = field(default_factory=dict)
    connections: List[str] = field(default_factory=list)
    integration_report: str = ""
    codice_generato: Optional[str] = None
    sandbox_result: Optional[Dict] = None
    validation_data: Dict = field(default_factory=dict)
    eval_data: Dict = field(default_factory=dict)
    score: float = 0.0
    certified: bool = False
    gaps: List[str] = field(default_factory=list)

    # ── Strategy / meta hints (set by InitPhase) ─────────────────────────────
    best_strategy: Optional[str] = None
    episode_context: Optional[str] = None
    strategy_used: Optional[str] = None
    strategy_obj: Any = None

    # ── Reliability tracking ─────────────────────────────────────────────────
    classified_error_type: Optional[str] = None
    error_signature: Optional[str] = None
    files_modified: List[str] = field(default_factory=list)
    attempt: int = 0

    # ── Critical thinking — LLM meta-critique on stuck topics ────────────────
    critic_meta_critique: Optional[str] = None  # set by CritAgent.analyze_with_llm on attempt>=2

    # ── CognitionCore — Senso Interno ─────────────────────────────────────────
    core_experience: Dict = field(default_factory=dict)   # Layer 4 snapshot for this topic
    pivot_directive: Optional[str] = None                 # structural pivot from Vettore 1
    core_relational_ctx: Optional[str] = None             # relational_context() injected at attempt>=2
    prev_strategy_used: Optional[str] = None              # tracks strategy across attempts for audit_emergence

    # ── Helper ────────────────────────────────────────────────────────────────

    async def emit(self, phase: str, score: float, msg: str):
        """Unified progress emission — replaces the nested closure in study_topic."""
        pct = self.progress.percentage if self.progress else 0
        print(f"[SHARD.STUDY] [{pct:3d}%] {phase} | {score}/10 | {msg}")
        sys.stdout.flush()
        if self.on_progress:
            await self.on_progress(phase, self.topic, score, msg, pct)

    async def report_crash(self, phase: str, error: Exception):
        """Report a fatal crash to logs + frontend + on_error callback."""
        import traceback as tb
        error_msg = f"CRITICAL ERROR during phase {phase}: {type(error).__name__}: {error}"
        full_trace = tb.format_exc()

        print(f"\n{'=' * 60}")
        print(f"[CRITICAL] {error_msg}")
        print(f"[CRITICAL] Full traceback:")
        print(full_trace)
        print(f"{'=' * 60}\n")
        sys.stdout.flush()
        sys.stderr.flush()

        await self.emit("ERROR", 0, f"Crash in {phase}: {str(error)[:200]}")

        if self.on_error:
            try:
                await self.on_error(self.topic, phase, str(error))
            except Exception as cb_err:
                print(f"[CRITICAL] on_error callback also failed: {cb_err}")
