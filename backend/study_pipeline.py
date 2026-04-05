"""study_pipeline.py -- Configurable study pipeline for SHARD.

Replaces the 750-line study_topic() orchestration with a declarative
sequence of BasePhase objects threaded through a shared StudyContext.

Usage (inside StudyAgent.study_topic):

    from study_pipeline import StudyPipeline
    from study_phases import (
        InitPhase, MapPhase, AggregatePhase, SynthesizePhase,
        StorePhase, CrossPollinatePhase, MaterializePhase,
        SandboxPhase, CertifyRetryGroup, PostStudyPhase,
    )

    pipeline = StudyPipeline([
        InitPhase(),
        MapPhase(),
        AggregatePhase(),
        SynthesizePhase(),
        StorePhase(),
        CrossPollinatePhase(),
        MaterializePhase(),
        SandboxPhase(),
        CertifyRetryGroup(),
        PostStudyPhase(),
    ])
    score = await pipeline.execute(ctx)
"""
from abc import ABC, abstractmethod

from study_context import StudyContext


# ── BasePhase ─────────────────────────────────────────────────────────────────

class BasePhase(ABC):
    """Single unit of work in the study pipeline.

    Attributes:
        name:  Phase identifier (matches PHASES dict for progress tracking).
        fatal: If True, failure aborts the pipeline.
               If False, failure is logged and the pipeline continues.
    """
    name: str = "UNKNOWN"
    fatal: bool = True

    @abstractmethod
    async def run(self, ctx: StudyContext) -> None:
        """Execute this phase.

        Read inputs from ctx, write outputs to ctx.
        Raise on failure -- the pipeline catches and routes based on self.fatal.
        """
        ...

    def __repr__(self):
        tag = "!" if self.fatal else "~"
        return f"<{tag}{self.name}>"


# ── StudyPipeline ─────────────────────────────────────────────────────────────

class StudyPipeline:
    """Executes a sequence of phases, threading StudyContext through each one.

    Handles:
    - Fatal vs non-fatal error routing
    - Progress tracking + crash reporting
    - Cleanup delegation (PostStudyPhase handles meta-learning, episodic store)
    """

    def __init__(self, phases: list):
        self.phases: list[BasePhase] = phases

    async def execute(self, ctx: StudyContext) -> dict:
        """Run all phases in order. Returns result dict with score and certified."""
        await ctx.emit("INIT", 0, f"Starting study of '{ctx.topic}'...")

        for phase in self.phases:
            try:
                await phase.run(ctx)
            except Exception as e:
                if phase.fatal:
                    await ctx.report_crash(phase.name, e)
                    return {"score": 0.0, "certified": False, "topic": ctx.topic, "benchmark_result": None}
                else:
                    print(f"[{phase.name}] Non-fatal error: {e}")
                    import traceback
                    traceback.print_exc()
                    if ctx.progress:
                        ctx.progress.complete_phase(phase.name)

        return {
            "score":            ctx.score,
            "certified":        ctx.certified,
            "topic":            ctx.topic,
            "benchmark_result": ctx.benchmark_result,
        }
