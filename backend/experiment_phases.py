"""experiment_phases.py -- SHARD Experiment Engine phases (#35).

Three pipeline phases activated only in research_mode=True:

  ExperimentDesignPhase   -- LLM generates executable Python for hypothesis test
  ExperimentSandboxPhase  -- runs code in DockerSandboxRunner (zero modifications)
  ExperimentValidatePhase -- LLM decides CONFIRMED/REFUTED/INCONCLUSIVE + DB write

All three phases are non-fatal and self-gating:
  - If research_mode=False or hypothesis not suitable -> SKIPPED, pipeline continues
  - Errors are caught and logged, never propagate to CertifyRetryGroup
"""
import json
import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from study_context import StudyContext

from study_phases import BasePhase

logger = logging.getLogger("shard.experiment_phases")

# ── Calibration log (jsonl, one record per hypothesis alignment decision) ─────
_CALIB_LOG_PATH: str | None = None   # set once per process on first use

def _calib_log_path() -> str:
    global _CALIB_LOG_PATH
    if _CALIB_LOG_PATH is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        experiments_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "shard_workspace", "experiments"
        )
        os.makedirs(experiments_dir, exist_ok=True)
        _CALIB_LOG_PATH = os.path.join(experiments_dir, f"alignment_log_{ts}.jsonl")
    return _CALIB_LOG_PATH

def _calib_append(record: dict) -> None:
    """Append one JSON line to the calibration log. Non-fatal."""
    try:
        with open(_calib_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("[CALIB_LOG] write failed (non-fatal): %s", exc)

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
            _persist_skipped(ctx, hypothesis, "SKIPPED")
            return

        confidence = float(hypothesis.get("confidence", 0.0))
        if confidence < _MIN_CONFIDENCE:
            ctx.experiment_status = "SKIPPED"
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                f"Hypothesis confidence {confidence:.2f} < {_MIN_CONFIDENCE} -- skipped"
            )
            _persist_skipped(ctx, hypothesis, "SKIPPED")
            return

        # ── Feasibility gate ──────────────────────────────────────────────────
        # Returns: "local" | "kaggle" | "invalid"
        #   "local"   → run in sandbox as-is
        #   "kaggle"  → valid science, needs GPU/downloads; generate code anyway
        #   "invalid" → domain mismatch or nonsensical proxy; skip with no code
        try:
            feasibility = await ctx.agent._is_experiment_feasible(hypothesis)
        except Exception:
            feasibility = "local"  # non-fatal -- assume feasible on error

        if feasibility == "invalid":
            ctx.experiment_status = "SKIPPED_TOO_COMPLEX"
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                "Domain mismatch or unfalsifiable experiment -- SKIPPED_TOO_COMPLEX"
            )
            print(f"[EXPERIMENT_DESIGN] SKIPPED_TOO_COMPLEX (invalid) -- '{hypothesis.get('statement','')[:80]}'")
            _persist_skipped(ctx, hypothesis, "SKIPPED_TOO_COMPLEX")
            return

        # kaggle or local → always generate code
        # For "kaggle", code is written for external compute and stored in DB
        is_kaggle = (feasibility == "kaggle")
        if is_kaggle:
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                "Experiment needs external compute (GPU/data) -- generating Kaggle-ready code"
            )
            print(f"[EXPERIMENT_DESIGN] KAGGLE_READY -- generating code for: '{hypothesis.get('statement','')[:80]}'")

        # ── Experiment alignment validator (LLM-based, semantic check) ────────
        # Checks that minimum_experiment actually tests the hypothesis.
        # REWRITE: replaces minimum_experiment and retries (up to MAX_REWRITES).
        # INVALID: skips entirely (proxy unrelated to hypothesis domain).
        _MAX_REWRITES = 2
        _alignment_ok = False
        _calib_attempts: list[dict] = []   # one entry per loop iteration

        for _attempt in range(_MAX_REWRITES + 1):
            try:
                alignment = await ctx.agent._validate_experiment_alignment(hypothesis, attempt=_attempt)
            except Exception:
                alignment = {"verdict": "VALID", "rewritten": None, "issues": []}

            _verdict = alignment.get("verdict", "VALID")
            _score   = alignment.get("alignment_score", 1.0)
            _issues  = alignment.get("issues", [])

            _calib_attempts.append({
                "attempt": _attempt,
                "score":   round(_score, 4),
                "verdict": _verdict,
                "issues":  _issues,
            })

            if _verdict == "VALID":
                _alignment_ok = True
                if _attempt > 0:
                    print(f"[EXPERIMENT_DESIGN] ALIGNMENT_VALID after {_attempt} rewrite(s) "
                          f"(score={_score:.2f})")
                break

            if _verdict == "REWRITE" and alignment.get("rewritten") and _attempt < _MAX_REWRITES:
                old_exp = hypothesis.get("minimum_experiment", "")
                hypothesis = dict(hypothesis)  # don't mutate original
                hypothesis["minimum_experiment"] = alignment["rewritten"]
                print(f"[EXPERIMENT_DESIGN] ALIGNMENT_REWRITE attempt={_attempt+1}/{_MAX_REWRITES} "
                      f"score={_score:.2f} -- '{old_exp[:50]}' -> '{alignment['rewritten'][:50]}'")
                await ctx.emit("EXPERIMENT_DESIGN", 0,
                               f"minimum_experiment rewritten (attempt {_attempt+1}) score={_score:.2f}")
                continue

            # INVALID verdict, or REWRITE with no rewritten text, or rewrites exhausted
            ctx.experiment_status = "SKIPPED_TOO_COMPLEX"
            issues_str = "; ".join(_issues) if isinstance(_issues, list) else str(_issues)
            reason = (
                f"INVALID (score={_score:.2f}): {issues_str}" if _verdict == "INVALID"
                else f"REWRITE loop exhausted after {_attempt} attempt(s): {issues_str}"
            )
            # ── Calibration record (failed path) ─────────────────────────────
            _calib_append({
                "ts":             time.strftime("%Y-%m-%dT%H:%M:%S"),
                "hypothesis":     (hypothesis.get("statement", "") or "")[:100],
                "domain_from":    hypothesis.get("domain_from", ""),
                "domain_to":      hypothesis.get("domain_to", ""),
                "kaggle_feasible": is_kaggle,
                "attempts":        _calib_attempts,
                "num_rewrites":    _attempt,
                "final_verdict":   "INVALID" if _verdict == "INVALID" else "REWRITE_EXHAUSTED",
            })
            await ctx.emit("EXPERIMENT_DESIGN", 0,
                           f"Alignment check failed -- SKIPPED ({reason[:100]})")
            print(f"[EXPERIMENT_DESIGN] ALIGNMENT_FAILED -- {reason[:140]}")
            _persist_skipped(ctx, hypothesis, "SKIPPED_TOO_COMPLEX")
            return

        if not _alignment_ok:
            # Shouldn't reach here, but guard anyway
            ctx.experiment_status = "SKIPPED_TOO_COMPLEX"
            _persist_skipped(ctx, hypothesis, "SKIPPED_TOO_COMPLEX")
            return

        # ── Calibration record (success path) ────────────────────────────────
        _calib_append({
            "ts":              time.strftime("%Y-%m-%dT%H:%M:%S"),
            "hypothesis":      (hypothesis.get("statement", "") or "")[:100],
            "domain_from":     hypothesis.get("domain_from", ""),
            "domain_to":       hypothesis.get("domain_to", ""),
            "kaggle_feasible": is_kaggle,
            "attempts":        _calib_attempts,
            "num_rewrites":    len(_calib_attempts) - 1,
            "final_verdict":   "VALID",
        })

        # ── Generate code ─────────────────────────────────────────────────────
        await ctx.emit("EXPERIMENT_DESIGN", 0, f"Designing experiment for: '{hypothesis.get('statement','')[:60]}...'")
        try:
            code = await ctx.agent._generate_experiment_code(hypothesis, kaggle_mode=is_kaggle)
            if not code or not code.strip():
                ctx.experiment_status = "SKIPPED"
                logger.warning("[EXPERIMENT_DESIGN] LLM returned empty code -- skipped")
                return
            ctx.experiment_code = code
            if is_kaggle:
                ctx.experiment_status = "KAGGLE_READY"
                # Persist immediately — no sandbox execution follows
                _persist_kaggle_ready(ctx, hypothesis, code)
                await ctx.emit("EXPERIMENT_DESIGN", 0,
                               f"Kaggle-ready code generated ({len(code)} chars) -- persisted to DB")
                print(f"[EXPERIMENT_DESIGN] KAGGLE_READY code saved for: '{hypothesis.get('statement','')[:80]}'")
                return
            await ctx.emit("EXPERIMENT_DESIGN", 0, f"Experiment code generated ({len(code)} chars)")
            print(f"[EXPERIMENT_DESIGN] Code preview:\n{code[:300]}...")
        except Exception as exc:
            ctx.experiment_status = "SKIPPED"
            logger.error("[EXPERIMENT_DESIGN] Code generation failed: %s", exc)
            await ctx.emit("EXPERIMENT_DESIGN", 0, f"Code generation failed: {exc} -- skipped")


def _persist_kaggle_ready(ctx, hypothesis: dict, code: str) -> None:
    """Persist a hypothesis whose experiment code targets Kaggle/GPU (KAGGLE_READY).

    Saves the generated code so it can be retrieved via get_kaggle_ready().
    Non-fatal -- errors are logged and swallowed.
    """
    try:
        from experiment_store import store_hypothesis, update_result
        source_papers = [
            {"title": s.get("title", ""), "year": s.get("year", ""), "url": s.get("url", "")}
            for s in (ctx.sources or [])
            if s.get("title")
        ] if ctx.research_mode else None
        hyp_id = store_hypothesis(ctx.topic, hypothesis, source_papers=source_papers)
        if hyp_id:
            update_result(
                hypothesis_id=hyp_id,
                status="KAGGLE_READY",
                experiment_code=code,
                experiment_result=None,
                confidence_updated=hypothesis.get("confidence", 0.0),
            )
            ctx._experiment_hypothesis_id = hyp_id
            print(f"[EXPERIMENT_DESIGN] Persisted KAGGLE_READY id={hyp_id}")
    except Exception as db_exc:
        logger.error("[EXPERIMENT_DESIGN] DB persist (kaggle) failed (non-fatal): %s", db_exc)


def _persist_skipped(ctx, hypothesis: dict, status: str) -> None:
    """Persist a hypothesis that was skipped before sandbox execution.

    Called for SKIPPED (not falsifiable / low confidence) and
    SKIPPED_TOO_COMPLEX (needs external resources).
    Non-fatal -- errors are logged and swallowed.
    """
    try:
        from experiment_store import store_hypothesis, update_result
        source_papers = [
            {"title": s.get("title", ""), "year": s.get("year", ""), "url": s.get("url", "")}
            for s in (ctx.sources or [])
            if s.get("title")
        ] if ctx.research_mode else None
        hyp_id = store_hypothesis(ctx.topic, hypothesis, source_papers=source_papers)
        if hyp_id:
            update_result(
                hypothesis_id=hyp_id,
                status=status,
                experiment_code=None,
                experiment_result=None,
                confidence_updated=hypothesis.get("confidence", 0.0),
            )
            ctx._experiment_hypothesis_id = hyp_id
            print(f"[EXPERIMENT_DESIGN] Persisted id={hyp_id} status={status}")
    except Exception as db_exc:
        logger.error("[EXPERIMENT_DESIGN] DB persist failed (non-fatal): %s", db_exc)


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

        if ctx.experiment_status in ("SKIPPED", "KAGGLE_READY") or not ctx.experiment_code:
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
