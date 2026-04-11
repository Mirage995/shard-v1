"""experiment_phases.py -- SHARD Experiment Engine phases (#35).

Three pipeline phases activated only in research_mode=True:

  ExperimentDesignPhase   -- LLM generates executable Python for hypothesis test
  ExperimentSandboxPhase  -- runs code in DockerSandboxRunner (zero modifications)
  ExperimentValidatePhase -- LLM decides CONFIRMED/REFUTED/INCONCLUSIVE + DB write

All three phases are non-fatal and self-gating:
  - If research_mode=False or hypothesis not suitable -> SKIPPED, pipeline continues
  - Errors are caught and logged, never propagate to CertifyRetryGroup
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from study_context import StudyContext

from study_phases import BasePhase

logger = logging.getLogger("shard.experiment_phases")

_MIN_CONFIDENCE = 0.6   # gate threshold -- hypotheses below this are SKIPPED


class ExperimentDesignPhase(BasePhase):
    """Translate hypothesis.minimum_experiment into executable sandbox Python.

    Gate conditions (all must be true):
      - ctx.research_mode is True
      - ctx.structured['hypothesis'] is present and not None
      - hypothesis['falsifiable'] is True
      - hypothesis['confidence'] >= _MIN_CONFIDENCE

    On success: writes ctx.experiment_code (str).
    On gate failure or error: writes ctx.experiment_status = 'SKIPPED'.
    """
    name  = "EXPERIMENT_DESIGN"
    fatal = False

    async def run(self, ctx: "StudyContext") -> None:
        # ── Gate ─────────────────────────────────────────────────────────────
        hypothesis = (ctx.structured or {}).get("hypothesis") if ctx.structured else None

        if not ctx.research_mode:
            print("[EXPERIMENT_DESIGN] SKIPPED (research_mode=False)")
            return

        if not hypothesis:
            ctx.experiment_status = "SKIPPED"
            logger.debug("[EXPERIMENT_DESIGN] No hypothesis in ctx.structured -- skipped")
            return

        if not hypothesis.get("falsifiable"):
            ctx.experiment_status = "SKIPPED"
            await ctx.emit("EXPERIMENT_DESIGN", 0, "Hypothesis not falsifiable -- skipped")
            return

        confidence = float(hypothesis.get("confidence", 0.0))
        if confidence < _MIN_CONFIDENCE:
            ctx.experiment_status = "SKIPPED"
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                f"Hypothesis confidence {confidence:.2f} < {_MIN_CONFIDENCE} -- skipped"
            )
            return

        # ── Feasibility gate (#35 Gap 2) ──────────────────────────────────────
        try:
            feasible = await ctx.agent._is_experiment_feasible(hypothesis)
        except Exception:
            feasible = True  # non-fatal -- assume feasible on error
        if not feasible:
            ctx.experiment_status = "SKIPPED_TOO_COMPLEX"
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                "Experiment requires real data/network/GPU -- SKIPPED_TOO_COMPLEX"
            )
            print("[EXPERIMENT_DESIGN] SKIPPED_TOO_COMPLEX -- not sandbox-feasible")
            return

        # ── Generate code ─────────────────────────────────────────────────────
        await ctx.emit("EXPERIMENT_DESIGN", 0, f"Designing experiment for: '{hypothesis.get('statement','')[:60]}...'")
        try:
            code = await ctx.agent._generate_experiment_code(hypothesis)
            if not code or not code.strip():
                ctx.experiment_status = "SKIPPED"
                logger.warning("[EXPERIMENT_DESIGN] LLM returned empty code -- skipped")
                return
            ctx.experiment_code = code
            await ctx.emit("EXPERIMENT_DESIGN", 0, f"Experiment code generated ({len(code)} chars)")
            print(f"[EXPERIMENT_DESIGN] Code preview:\n{code[:300]}...")
        except Exception as exc:
            ctx.experiment_status = "SKIPPED"
            logger.error("[EXPERIMENT_DESIGN] Code generation failed: %s", exc)
            await ctx.emit("EXPERIMENT_DESIGN", 0, f"Code generation failed: {exc} -- skipped")


class ExperimentSandboxPhase(BasePhase):
    """Execute experiment_code in Docker sandbox (DockerSandboxRunner, zero modifications).

    Gate conditions:
      - ctx.experiment_status != 'SKIPPED'
      - ctx.experiment_code is not None

    On success: writes ctx.experiment_result {success, stdout, stderr, exit_code}.
    On gate failure or error: logs and returns (experiment_status unchanged).
    """
    name  = "EXPERIMENT_SANDBOX"
    fatal = False

    async def run(self, ctx: "StudyContext") -> None:
        # ── Gate ─────────────────────────────────────────────────────────────
        if not ctx.research_mode:
            print("[EXPERIMENT_SANDBOX] SKIPPED (research_mode=False)")
            return

        if ctx.experiment_status == "SKIPPED" or not ctx.experiment_code:
            return

        # ── Execute ───────────────────────────────────────────────────────────
        await ctx.emit("EXPERIMENT_SANDBOX", 0, "Running experiment in Docker sandbox...")
        try:
            import os as _os
            from sandbox_runner import DockerSandboxRunner
            _sandbox_dir = getattr(ctx.agent, "sandbox_dir", None) or _os.path.join(_os.getcwd(), "sandbox")
            runner = DockerSandboxRunner(
                sandbox_dir=_sandbox_dir,
                analysis_fn=None,   # no LLM analysis -- ExperimentValidatePhase handles it
            )
            result = await runner.run(
                topic=f"[EXPERIMENT] {ctx.topic}",
                code=ctx.experiment_code,
                progress=ctx.progress,
            )
            ctx.experiment_result = {
                "success":   result.get("success", False),
                "stdout":    result.get("stdout", ""),
                "stderr":    result.get("stderr", ""),
                "exit_code": 0 if result.get("success") else 1,
            }
            status_icon = "OK" if result.get("success") else "FAIL"
            await ctx.emit(
                "EXPERIMENT_SANDBOX", 0,
                f"Sandbox [{status_icon}] -- stdout: {result.get('stdout','')[:80]}"
            )
        except Exception as exc:
            logger.error("[EXPERIMENT_SANDBOX] Sandbox execution failed: %s", exc)
            ctx.experiment_result = {
                "success": False, "stdout": "", "stderr": str(exc), "exit_code": -1
            }
            await ctx.emit("EXPERIMENT_SANDBOX", 0, f"Sandbox error: {exc}")


class ExperimentValidatePhase(BasePhase):
    """LLM interprets sandbox output and decides CONFIRMED/REFUTED/INCONCLUSIVE.

    Gate conditions:
      - ctx.experiment_result is not None

    On success:
      - writes ctx.experiment_status (CONFIRMED/REFUTED/INCONCLUSIVE)
      - writes ctx.hypothesis_confidence_updated
      - persists to DB via ExperimentStore
    """
    name  = "EXPERIMENT_VALIDATE"
    fatal = False

    async def run(self, ctx: "StudyContext") -> None:
        # ── Gate ─────────────────────────────────────────────────────────────
        if not ctx.research_mode:
            print("[EXPERIMENT_VALIDATE] SKIPPED (research_mode=False)")
            return

        if ctx.experiment_result is None:
            return

        hypothesis = (ctx.structured or {}).get("hypothesis")
        if not hypothesis:
            return

        # ── Validate ──────────────────────────────────────────────────────────
        await ctx.emit("EXPERIMENT_VALIDATE", 0, "Interpreting experiment result...")
        try:
            stdout = ctx.experiment_result.get("stdout", "")
            stderr = ctx.experiment_result.get("stderr", "")

            verdict = await ctx.agent._validate_experiment_result(hypothesis, stdout, stderr)

            ctx.experiment_status           = verdict.get("status", "INCONCLUSIVE")
            ctx.hypothesis_confidence_updated = float(verdict.get("confidence_updated", hypothesis.get("confidence", 0.0)))

            await ctx.emit(
                "EXPERIMENT_VALIDATE", 0,
                f"Verdict: {ctx.experiment_status} | "
                f"confidence {hypothesis.get('confidence', 0.0):.2f} -> {ctx.hypothesis_confidence_updated:.2f} | "
                f"{verdict.get('reasoning','')[:80]}"
            )
            print(f"[EXPERIMENT_VALIDATE] {ctx.experiment_status} | reasoning: {verdict.get('reasoning','')}")

        except Exception as exc:
            ctx.experiment_status = "INCONCLUSIVE"
            ctx.hypothesis_confidence_updated = hypothesis.get("confidence", 0.0)
            logger.error("[EXPERIMENT_VALIDATE] Validation failed: %s", exc)
            await ctx.emit("EXPERIMENT_VALIDATE", 0, f"Validation error: {exc} -- set INCONCLUSIVE")

        # ── Persist to DB ─────────────────────────────────────────────────────
        try:
            from experiment_store import store_hypothesis, update_result

            # Store if not already persisted (first run for this topic/hypothesis)
            existing_id = getattr(ctx, "_experiment_hypothesis_id", None)
            if existing_id is None:
                source_papers = [
                    {"title": s.get("title", ""), "year": s.get("year", ""), "url": s.get("url", "")}
                    for s in (ctx.sources or [])
                    if s.get("title")
                ] if ctx.research_mode else None

                existing_id = store_hypothesis(ctx.topic, hypothesis, source_papers=source_papers)
                ctx._experiment_hypothesis_id = existing_id

            if existing_id:
                update_result(
                    hypothesis_id     = existing_id,
                    status            = ctx.experiment_status,
                    experiment_code   = ctx.experiment_code,
                    experiment_result = ctx.experiment_result,
                    confidence_updated= ctx.hypothesis_confidence_updated,
                )
                print(f"[EXPERIMENT_VALIDATE] Persisted id={existing_id} status={ctx.experiment_status}")
        except Exception as db_exc:
            logger.error("[EXPERIMENT_VALIDATE] DB persist failed (non-fatal): %s", db_exc)
