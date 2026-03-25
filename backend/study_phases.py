"""study_phases.py — All pipeline phases for the SHARD study loop.

Each phase is a BasePhase subclass that reads from / writes to StudyContext.
The code inside each phase is lifted verbatim from study_agent.study_topic()
— prompts, scraping logic, and validation mechanisms are UNCHANGED.

Phase list (in pipeline order):
  1. InitPhase           — meta-learning hint + episodic memory context
  2. MapPhase            — search sources (DuckDuckGo)
  3. AggregatePhase      — scrape web pages (Playwright)
  4. SynthesizePhase     — LLM synthesis + cross-reference
  5. StorePhase          — persist to ChromaDB
  6. CrossPollinatePhase — integration report (non-fatal)
  7. MaterializePhase    — cheat sheet to filesystem (non-fatal)
  8. SandboxPhase        — code gen + Docker exec + SWE repair (non-fatal)
  9. CertifyRetryGroup   — VALIDATE → EVALUATE → BENCHMARK → CERTIFY × N
 10. PostStudyPhase      — meta-learning update, strategy tracking, episodic store (non-fatal)
"""
import json
import re
import sys
from datetime import datetime

from study_pipeline import BasePhase
from study_context import StudyContext
from constants import SUCCESS_SCORE_THRESHOLD

# MAX_RETRY lives here (was a module-level constant in study_agent.py)
MAX_RETRY = 3


# ── 1. InitPhase ─────────────────────────────────────────────────────────────

class InitPhase(BasePhase):
    """Fetch meta-learning strategy hint and episodic memory context."""
    name = "INIT"
    fatal = True

    async def run(self, ctx: StudyContext) -> None:
        # Meta-learning: suggest best strategy before starting
        ctx.best_strategy = ctx.agent.meta_learning.suggest_best_strategy(ctx.topic)
        if ctx.best_strategy:
            print(f"[META] Using best strategy: {ctx.best_strategy}")

        # Episodic memory: retrieve past experience context
        try:
            from episodic_memory import get_episodic_memory
            _em = get_episodic_memory()
            ctx.episode_context = _em.get_context_prompt(ctx.topic, k=3)
            if ctx.episode_context:
                print(f"[EPISODIC] Context found for '{ctx.topic}':\n{ctx.episode_context}")
        except Exception as _ep_err:
            print(f"[EPISODIC] Non-fatal retrieval error: {_ep_err}")


# ── 2. MapPhase ──────────────────────────────────────────────────────────────

class MapPhase(BasePhase):
    """Search sources with multiple targeted queries."""
    name = "MAP"
    fatal = True

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("MAP", 0, f"Searching sources for '{ctx.topic}'...")
        ctx.sources = await ctx.agent.phase_map(ctx.topic, ctx.tier)
        print(f"[MAP] Phase completed. {len(ctx.sources)} sources found.")


# ── 3. AggregatePhase ────────────────────────────────────────────────────────

class AggregatePhase(BasePhase):
    """Scrape and clean text from web pages."""
    name = "AGGREGATE"
    fatal = True

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("AGGREGATE", 0, f"Scraping {len(ctx.sources)} sources...")
        print("[AGGREGATE] Entering phase. Initializing browser...")
        sys.stdout.flush()
        ctx.raw_text = await ctx.agent.phase_aggregate(ctx.sources)
        print(f"[AGGREGATE] Phase completed. {len(ctx.raw_text)} chars scraped.")

        if not ctx.raw_text.strip():
            await ctx.emit("ERROR", 0, "No content could be scraped from any source.")
            if ctx.on_error:
                await ctx.on_error(ctx.topic, "AGGREGATE", "No content could be scraped from any source")
            raise RuntimeError("No content scraped — aborting pipeline")


# ── 4. SynthesizePhase ───────────────────────────────────────────────────────

class SynthesizePhase(BasePhase):
    """LLM synthesis + cross-referencing with existing knowledge."""
    name = "SYNTHESIZE"
    fatal = True

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("SYNTHESIZE", 0, "Building structured knowledge...")
        ctx.structured = await ctx.agent.phase_synthesize(
            ctx.topic, ctx.raw_text,
            strategy_hint=ctx.best_strategy,
            previous_score=ctx.previous_score,
            episode_context=ctx.episode_context,
        )
        print(f"[SYNTHESIZE] Phase completed. {len(ctx.structured.get('concepts', []))} concepts extracted.")

        # Cross-referencing with existing knowledge
        try:
            ctx.connections = await ctx.agent._cross_reference(ctx.topic, ctx.structured)
            ctx.structured["connections"] = ctx.connections
            if ctx.connections:
                await ctx.emit("SYNTHESIZE", 0, f"Found {len(ctx.connections)} connections with existing knowledge")
        except Exception as e:
            print(f"[CROSS-REF] Non-fatal error: {e}")
            ctx.connections = []
            ctx.structured["connections"] = []


# ── 5. StorePhase ────────────────────────────────────────────────────────────

class StorePhase(BasePhase):
    """Save knowledge to ChromaDB."""
    name = "STORE"
    fatal = True

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("STORE", 0, "Persisting to knowledge base...")
        await ctx.agent.phase_store(ctx.topic, ctx.structured)
        print("[STORE] Phase completed.")


# ── 6. CrossPollinatePhase ───────────────────────────────────────────────────

class CrossPollinatePhase(BasePhase):
    """Generate Integration Report linking old and new knowledge."""
    name = "CROSS_POLLINATE"
    fatal = False

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("CROSS_POLLINATE", 0, "Generating Integration Report...")
        ctx.integration_report = await ctx.agent.phase_cross_pollinate(
            ctx.topic, ctx.raw_text, ctx.structured,
        )
        if ctx.integration_report:
            await ctx.emit("CROSS_POLLINATE", 0, f"Integration Report: {ctx.integration_report[:100]}...")
        print("[CROSS-POLLINATE] Phase completed.")


# ── 7. MaterializePhase ──────────────────────────────────────────────────────

class MaterializePhase(BasePhase):
    """Generate a structured Cheat Sheet and write it to the filesystem."""
    name = "MATERIALIZE"
    fatal = False

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("MATERIALIZE", 0, "Writing Cheat Sheet to filesystem...")
        mat_ok = await ctx.agent.phase_materialize(
            ctx.topic, ctx.structured,
            strategy_hint=ctx.best_strategy,
            previous_score=ctx.previous_score,
            episode_context=ctx.episode_context,
        )
        if mat_ok:
            await ctx.emit("MATERIALIZE", 0, "Cheat Sheet saved to knowledge_base/")
        else:
            await ctx.emit("MATERIALIZE", 0, "Cheat Sheet materialization failed")
        print("[MATERIALIZE] Phase completed.")


# ── 8. SandboxPhase ──────────────────────────────────────────────────────────

class SandboxPhase(BasePhase):
    """Generate code, execute in Docker sandbox, attempt repairs on failure.

    This phase is non-fatal: if code generation or execution fails,
    the pipeline continues to VALIDATE/EVALUATE with sandbox_result=None.
    """
    name = "SANDBOX"
    fatal = False

    async def run(self, ctx: StudyContext) -> None:
        ctx.sandbox_result = None

        # Retrieve strategy for code generation
        strategy = await ctx.agent.retrieve_strategy(ctx.topic)
        ctx.strategy_used = strategy

        # ── Shared assertion requirements block ───────────────────────────
        _ASSERT_BLOCK = """
VALIDATION REQUIREMENTS (mandatory — this is how correctness is verified):

After your implementation, write at least 3 assert statements that test real behavior:
- Test normal inputs with known correct outputs
- Test edge cases (empty input, zero, negative, boundary values)
- Test that the implementation actually does what the topic requires

End with exactly this line:
    print("✓ All assertions passed")

Example structure:
    def my_function(x):
        # ... implementation ...

    # Validation
    assert my_function(2) == 4, "basic case failed"
    assert my_function(0) == 0, "zero edge case failed"
    assert my_function(-1) == 1, "negative edge case failed"
    print("✓ All assertions passed")

IMPORTANT: assert statements must test actual output values, not just that the function runs.
BAD:  assert my_function(2) is not None
GOOD: assert my_function(2) == 4
"""

        # ── Code generation ──────────────────────────────────────────────
        if strategy:
            await ctx.emit("SANDBOX", 0, "Using past strategy to guide code generation")
            print("[STUDY] Using past strategy")
            print("[SANDBOX] Generating code independently from theory phase")

            prompt_codice = f"""
Topic: {ctx.topic}

Previous successful strategy:
{strategy}

Write a minimal executable Python script demonstrating the topic.

Rules:
- valid Python code
- no markdown
- no explanations
- executable script only

IMPORTANT:
The generated code MUST terminate automatically.
Do NOT start persistent servers such as Flask, FastAPI, HTTPServer, or any socket listener.
Instead demonstrate the concept using functions, mocked requests, or short scripts that exit within a few seconds.
Do NOT make real HTTP requests to external URLs.
Instead use mock data, simulated responses, or local function calls.
The sandbox has NO network access.
{_ASSERT_BLOCK}"""
        else:
            await ctx.emit("SANDBOX", 0, "Generating code independently from theory phase")
            print("[SANDBOX] Generating code independently from theory phase")

            prompt_codice = f"""
Write a minimal executable Python script demonstrating: {ctx.topic}

Rules:
- valid Python code
- no markdown
- no explanations

IMPORTANT:
The generated code MUST terminate automatically.
Do NOT start persistent servers such as Flask, FastAPI, HTTPServer, or any socket listener.
Instead demonstrate the concept using functions, mocked requests, or short scripts that exit within a few seconds.
Do NOT make real HTTP requests to external URLs.
Instead use mock data, simulated responses, or local function calls.
The sandbox has NO network access.
{_ASSERT_BLOCK}"""

        prompt_codice += """

SANDBOX CONSTRAINTS:

The execution environment has NO internet access.

You MUST only use these libraries:

* Python standard library
* numpy
* math
* random
* itertools
* collections
* concurrent.futures

DO NOT use:

tensorflow
torch
pandas
sklearn
requests
external APIs
pip installs

If the task would normally require such libraries, implement a simplified version using numpy or pure python.
"""

        try:
            print("[SANDBOX] applying library constraints")
            ctx.codice_generato = await ctx.agent._think_fast(prompt_codice)
        except Exception as e:
            print(f"[SANDBOX] Code generation failed: {e}")

        # Markdown cleanup
        if ctx.codice_generato:
            if "```" in ctx.codice_generato:
                lines = ctx.codice_generato.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                ctx.codice_generato = "\n".join(lines).strip()
        else:
            print("[SANDBOX] No code generated by model")

        # ── Network import check (fail fast) ─────────────────────────────
        _BANNED_IMPORTS = re.compile(
            r"^\s*(import\s+(requests|urllib|aiohttp|http\.client|httpx|urllib3|socket)"
            r"|from\s+(requests|urllib|aiohttp|http\.client|httpx|urllib3|socket)\s+import)",
            re.MULTILINE,
        )
        _MAX_NET_RETRIES = 2
        _net_retries = 0
        while ctx.codice_generato and _net_retries < _MAX_NET_RETRIES:
            match = _BANNED_IMPORTS.search(ctx.codice_generato)
            if not match:
                break
            _net_retries += 1
            banned_line = match.group(0).strip()
            print(f"[SANDBOX] Network import detected: '{banned_line}' — retry {_net_retries}/{_MAX_NET_RETRIES}")
            net_violation_prompt = (
                prompt_codice
                + f"\n\nHai violato il vincolo di assenza di rete: '{banned_line}' non è consentito. "
                "Riscrivi il codice senza alcun import di rete. "
                "Usa solo stdlib, numpy, math, random, itertools, collections, concurrent.futures."
            )
            try:
                ctx.codice_generato = await ctx.agent._think_fast(net_violation_prompt)
                if ctx.codice_generato and "```" in ctx.codice_generato:
                    lines = ctx.codice_generato.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    ctx.codice_generato = "\n".join(lines).strip()
            except Exception as e:
                print(f"[SANDBOX] Net-violation retry failed: {e}")
                ctx.codice_generato = None
                break
        else:
            if ctx.codice_generato and _BANNED_IMPORTS.search(ctx.codice_generato):
                print("[SANDBOX] Network import persists after retries — aborting sandbox execution")
                ctx.codice_generato = None

        # ── Execution ────────────────────────────────────────────────────
        if ctx.codice_generato:
            try:
                await ctx.emit("SANDBOX", 0, "Executing generated code")
                print("[SANDBOX] Executing generated code")

                ctx.sandbox_result = await ctx.agent.run_sandbox(ctx.topic, ctx.codice_generato)

                # ── Assertion marker check ────────────────────────────────
                # If code ran but assertions marker is missing, treat as
                # functional failure — code ran but proved nothing.
                if ctx.sandbox_result.get("success", False):
                    stdout = ctx.sandbox_result.get("stdout", "")
                    # Check for marker without the ✓ character to avoid Windows/Docker
                    # encoding corruption (✓ arrives as âœ" on some Windows setups)
                    if "All assertions passed" not in stdout:
                        print("[SANDBOX] ⚠️  No assertion marker in stdout — code ran but did not validate behavior")
                        ctx.sandbox_result["success"] = False
                        ctx.sandbox_result["stderr"] = (
                            ctx.sandbox_result.get("stderr", "") +
                            "\n[SANDBOX] AssertionError: missing '✓ All assertions passed' — "
                            "add assert statements that verify actual output values, "
                            "then print('✓ All assertions passed')"
                        )

                if not ctx.sandbox_result.get("success", False):
                    await self._attempt_repairs(ctx)

                if not ctx.sandbox_result.get("success", False):
                    self._classify_failure(ctx)

                status = "passed" if ctx.sandbox_result["success"] else "failed"
                await ctx.emit("SANDBOX", 0, f"Sandbox {status}: {ctx.sandbox_result['analysis'][:100]}")
                print("[SANDBOX] Execution completed")

            except Exception as e:
                print(f"[SANDBOX] Execution error: {e}")
                import traceback
                traceback.print_exc()
                ctx.sandbox_result = {
                    "success": False, "stdout": "", "stderr": str(e),
                    "analysis": f"Sandbox crash: {e}",
                    "code": ctx.codice_generato, "file_path": None,
                }
        else:
            print("[SANDBOX] Skipping execution (no code produced)")

        if ctx.progress:
            ctx.progress.complete_phase("SANDBOX")

    # ── Private helpers (lifted verbatim from study_topic) ────────────────

    async def _attempt_repairs(self, ctx: StudyContext) -> None:
        """SWE agent + simulation engine repair attempt."""
        from backend.swe_agent import SWEAgent

        print("[STUDY] sandbox failure")
        ctx.agent.world_model.record_failure(ctx.topic, ctx.sandbox_result)
        print("[STUDY] invoking SWE agent")

        swe = SWEAgent(workspace_dir="shard_workspace")
        sandbox_file = ctx.sandbox_result.get("file_path")
        stderr_text = ctx.sandbox_result.get("stderr", "unknown error")

        # Detect assertion failure vs crash — different repair strategies
        is_assertion_failure = (
            "AssertionError" in stderr_text
            or "All assertions passed" in stderr_text
        )
        if is_assertion_failure:
            print("[SANDBOX] Assertion failure detected — code logic is wrong, not syntax")
            error_tail = (
                f"AssertionError in topic '{ctx.topic}': the implementation produced "
                f"wrong output values. Fix the logic so all assert statements pass. "
                f"Details: {stderr_text[-300:]}"
            )
        else:
            # Build error-aware patch candidates from actual stderr
            error_lines = [l.strip() for l in stderr_text.splitlines() if l.strip()]
            error_tail = " | ".join(error_lines[-3:]) if error_lines else "unknown error"

        print("[SIMULATION] generating candidate repairs")
        patch_candidates = [
            f"fix runtime error: {error_tail}",
            f"fix code logic for topic: {ctx.topic}",
            "fix sandbox execution failure",
        ]

        scores = []
        for patch in patch_candidates:
            print("[SIMULATION] evaluating patch candidate", patch)
            s = ctx.agent.sim_engine.predict_patch_success(ctx.topic, patch)
            scores.append((patch, s))

        scores.sort(key=lambda x: x[1], reverse=True)
        best_patch = scores[0][0]
        print("[SIMULATION] best predicted repair", best_patch)

        if sandbox_file:
            await swe.repair_file_with_llm(sandbox_file, stderr_text)
        else:
            print("[SIMULATION] no sandbox file path — skipping repair")

        print("[STUDY] retry sandbox")
        ctx.sandbox_result = await ctx.agent.run_sandbox(ctx.topic, ctx.codice_generato)

        if ctx.sandbox_result.get("success", False):
            from backend.strategy_memory import StrategyMemory
            memory = StrategyMemory()
            memory.store_strategy(
                "swe_repair",
                json.dumps({"topic": ctx.topic, "repair": "llm_patch"}),
                "success",
                10.0,
            )

    def _classify_failure(self, ctx: StudyContext) -> None:
        """Classify sandbox error + attempt heuristic fix + critic analysis."""
        import pathlib
        from importlib.util import spec_from_file_location, module_from_spec

        def _load_mod(rel_path, mod_name):
            repo_root = pathlib.Path(__file__).resolve().parents[1]
            target = repo_root / rel_path
            spec = spec_from_file_location(mod_name, target)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load module from {target}")
            mod = module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        error_mod = _load_mod("shard/debug/error_classifier.py", "shard_debug_error_classifier")
        classify_error = error_mod.classify_error
        repair_mod = _load_mod("shard/debug/heuristic_repairs.py", "shard_debug_heuristic_repairs")
        attempt_heuristic_fix = repair_mod.attempt_heuristic_fix

        stderr_text = ctx.sandbox_result.get("stderr", "")
        ctx.classified_error_type = classify_error(stderr_text)
        ctx.error_signature = (stderr_text or "").strip().splitlines()[-1][:200] if stderr_text else None
        print(f"[RELIABILITY] Sandbox failure classified as: {ctx.classified_error_type}")

        repair_context = {
            "stderr": stderr_text,
            "file_path": ctx.sandbox_result.get("file_path"),
            "topic": ctx.topic,
        }
        fix_result = attempt_heuristic_fix(ctx.classified_error_type, repair_context)
        if fix_result.get("success"):
            ctx.files_modified.extend(fix_result.get("files_modified", []))
            print(f"[RELIABILITY] Heuristic fix succeeded: {fix_result.get('files_modified', [])}")
        else:
            print("[RELIABILITY] Heuristic fix unavailable or failed; continuing normal failure flow")
            critic_input = {
                "stderr": stderr_text,
                "stdout": ctx.sandbox_result.get("stdout", ""),
                "failure_type": str(ctx.classified_error_type),
                "capability": ctx.topic,
            }
            try:
                critic_analysis = ctx.agent.critic_agent.analyze_failure(critic_input)
                print(f"[RELIABILITY] Critic analysis: {critic_analysis}")
                ctx.agent.critic_feedback_engine.process_feedback(critic_analysis)
            except Exception as critic_err:
                print(f"[RELIABILITY] Critic analysis failed (non-fatal): {critic_err}")


# ── 9. CertifyRetryGroup ─────────────────────────────────────────────────────

class CertifyRetryGroup(BasePhase):
    """Composite phase: VALIDATE -> EVALUATE -> BENCHMARK -> CERTIFY x MAX_RETRY.

    On retry: re-synthesizes gaps + regenerates sandbox code.
    The retry logic couples these sub-phases, so they stay together as one unit.
    """
    name = "CERTIFY_LOOP"
    fatal = True

    async def run(self, ctx: StudyContext) -> None:
        from strategy_extractor import StrategyExtractor
        from skill_utils import normalize_capability_name

        while ctx.attempt < MAX_RETRY and not ctx.certified:
            ctx.attempt += 1

            # ── VALIDATE ─────────────────────────────────────────────
            try:
                await ctx.emit("VALIDATE", 0, f"Self-interrogation (attempt {ctx.attempt}/{MAX_RETRY})...")
                ctx.validation_data = await ctx.agent.phase_validate(
                    ctx.topic, ctx.structured, sandbox_result=ctx.sandbox_result,
                )
            except Exception as e:
                raise  # fatal — propagates to pipeline

            # ── EVALUATE ─────────────────────────────────────────────
            try:
                await ctx.emit("EVALUATE", 0, "Scoring with Test-Driven Protocol...")
                ctx.eval_data = await ctx.agent.phase_evaluate(
                    ctx.topic, ctx.validation_data,
                    sandbox_result=ctx.sandbox_result,
                    gaps=ctx.gaps if ctx.attempt > 1 else None,
                    generated_code=ctx.codice_generato,
                )
                ctx.score = ctx.eval_data.get("score", 0)

                # Strategy extraction + storage
                await self._extract_and_store_strategy(ctx)

                # Experiment cache + replay
                if ctx.eval_data and ctx.eval_data.get("score", 0) < SUCCESS_SCORE_THRESHOLD:
                    current_skills = len(ctx.agent.capability_graph.capabilities) if ctx.agent.capability_graph else 0
                    ctx.agent.experiment_cache.register_failure(ctx.topic, current_skills)

                ctx.agent.replay_engine.add_experiment(ctx.topic)

            except Exception as e:
                raise  # fatal — propagates to pipeline

            # ── BENCHMARK (non-fatal) ────────────────────────────────
            try:
                bench_update = await ctx.agent.phase_benchmark(
                    ctx.topic, ctx.codice_generato or "", ctx.eval_data,
                )
                ctx.eval_data = {**ctx.eval_data, **bench_update}
                ctx.score = ctx.eval_data.get("score", ctx.score)
            except Exception as bench_phase_err:
                print(f"[BENCHMARK] Non-fatal phase error — skipping: {bench_phase_err}")

            # ── CERTIFY ──────────────────────────────────────────────
            ctx.certified = await ctx.agent.phase_certify(ctx.topic, ctx.eval_data)

            if ctx.certified:
                await ctx.emit("CERTIFY", ctx.score, f"Topic certified! Score: {ctx.score}/10")
                await ctx.emit("CERTIFY", ctx.score, f"SHARD stance: {ctx.eval_data.get('shard_stance', '')[:120]}")
                if ctx.on_certify:
                    await ctx.on_certify(ctx.topic, ctx.score, {
                        **ctx.eval_data,
                        "sandbox": ctx.sandbox_result,
                        "concepts": ctx.structured.get("concepts", []),
                        "shard_opinion": ctx.structured.get("shard_opinion", ""),
                        "connections": ctx.connections,
                        "validation_qa": ctx.validation_data.get("validation_qa", []),
                    })

                # Self-generated benchmarks post-certification
                await self._post_certify_benchmarks(ctx)

            else:
                ctx.gaps = ctx.eval_data.get("gaps", [])
                focus = ctx.eval_data.get("improvement_focus", "")
                await ctx.emit("VALIDATE", ctx.score, f"Score {ctx.score}/10 — Retrying. Focus: {focus[:80]}")

                if ctx.attempt < MAX_RETRY:
                    # On attempt 2+: ask CriticAgent for LLM meta-critique
                    # "What am I doing wrong systematically?" — injects into retry prompt
                    if ctx.attempt >= 2:
                        try:
                            critique = await ctx.agent.critic_agent.analyze_with_llm(
                                ctx.topic, ctx.score, ctx.gaps, ctx.attempt
                            )
                            if critique:
                                ctx.critic_meta_critique = critique
                                await ctx.emit("VALIDATE", ctx.score, f"[CRITIC] {critique[:100]}...")
                        except Exception as _ce:
                            pass  # non-fatal
                    await self._retry_gap_fill(ctx)

        if not ctx.certified:
            await ctx.emit("FAILED", ctx.score, f"Could not certify '{ctx.topic}' after {MAX_RETRY} attempts. Best: {ctx.score}/10")

    # ── Private helpers ──────────────────────────────────────────────────

    async def _extract_and_store_strategy(self, ctx: StudyContext) -> None:
        """Extract strategy from experiment and store to StrategyMemory."""
        from strategy_extractor import StrategyExtractor
        try:
            experiment = {
                "topic": ctx.topic,
                "sandbox_result": ctx.sandbox_result,
                "eval_data": ctx.eval_data,
                "structured": ctx.structured,
            }
            strategy_info = ctx.agent.strategy_memory.extract_strategy(experiment)
            if strategy_info:
                await ctx.agent.strategy_memory.store_strategy_async(
                    ctx.topic,
                    strategy_info["strategy"],
                    strategy_info["outcome"],
                    score=strategy_info.get("score", 0),
                )
                # Update capability graph only on success
                if strategy_info["outcome"] == "success":
                    await ctx.agent.capability_graph.update_from_strategy_async(
                        ctx.topic,
                        strategy_info["strategy"],
                    )
                    # Discover implicit skills from strategy
                    ctx.agent.skill_discovery.discover_from_experiment(
                        ctx.topic,
                        strategy_info["strategy"],
                    )
        except Exception as strat_err:
            print(f"[STRATEGY] Error extracting/storing strategy: {strat_err}")

        # Strategy Abstraction Layer hook
        try:
            extractor = StrategyExtractor()
            pipeline_steps = [
                "MAP", "AGGREGATE", "SYNTHESIZE", "STORE",
                "SANDBOX", "VALIDATE", "EVALUATE", "CERTIFY",
            ]
            experiment = {
                "topic": ctx.topic,
                "sandbox_result": ctx.sandbox_result,
                "eval_data": ctx.eval_data,
                "structured": ctx.structured,
                "pipeline_steps": pipeline_steps,
                "steps": ["research", "validate"],
            }
            ctx.strategy_obj = extractor.extract_from_experiment(experiment)
            if ctx.strategy_obj:
                await ctx.agent.strategy_memory.store_strategy_object_async(ctx.strategy_obj)
        except Exception as ext_err:
            print(f"[STRATEGY] Abstraction extraction error (non-fatal): {ext_err}")

    async def _post_certify_benchmarks(self, ctx: StudyContext) -> None:
        """Run self-generated benchmarks after certification."""
        from skill_utils import normalize_capability_name
        try:
            capability_name = normalize_capability_name(ctx.topic)

            # Get difficulty from capability graph if available
            difficulty = 1
            if ctx.agent.capability_graph and hasattr(ctx.agent.capability_graph, 'get_difficulty'):
                try:
                    difficulty = ctx.agent.capability_graph.get_difficulty(capability_name) or 1
                except Exception:
                    difficulty = 1

            benchmark = ctx.agent.benchmark_generator.generate_for_capability(capability_name, difficulty=difficulty)
            result = ctx.agent.benchmark_runner.run(benchmark)

            status = "PASS" if result["success"] else "FAIL"
            print(f"[BENCHMARK] {capability_name} | diff={difficulty} | {status}")

            if not result["success"]:
                analysis = ctx.agent.critic_agent.analyze_failure(result)
                print(f"[CRITIC] Failure analysis: {analysis}")
                ctx.agent.critic_feedback_engine.process_feedback(analysis)

                # Auto-debug with SWE Agent
                await self._auto_debug(ctx, result)

        except Exception as bench_err:
            print(f"[BENCHMARK] Non-fatal error during benchmark: {bench_err}")

    async def _auto_debug(self, ctx: StudyContext, result: dict) -> None:
        """SWE Agent auto-debug on benchmark failure (async, non-fatal)."""
        import os

        if not ctx.agent.swe_agent:
            return

        try:
            print("[AUTO-DEBUG] Sandbox failure detected")
            print("[AUTO-DEBUG] Triggering SWEAgent...")

            issue_text = f"""
A sandbox experiment failed.

Topic:
{ctx.topic}

Error output:
{result.get("stderr", "")}

Please analyze the problem and propose a minimal patch.
"""

            print("[AUTO-DEBUG] Using repo: shard_workspace")
            patch_result = await ctx.agent.swe_agent.run_task(
                repo_name="shard_workspace",
                base_commit="HEAD",
                issue_text=issue_text,
            )

            if patch_result and patch_result.get("patch"):
                print("[AUTO-DEBUG] Patch suggested by SWEAgent")
                patch_text = patch_result["patch"]

                # Prevent patching core SHARD backend
                if "backend/" in patch_text or "study_agent.py" in patch_text:
                    print("[AUTO-DEBUG] Patch attempts to modify core system. Skipping.")
                else:
                    print("[AUTO-DEBUG] Safety check passed")
                    ctx.agent.swe_agent.apply_patch(patch_text)
                    print("[AUTO-DEBUG] Patch applied")

                    # Reload patched code from sandbox file
                    try:
                        sandbox_path = ctx.sandbox_result.get("file_path") if ctx.sandbox_result else None
                        if sandbox_path and os.path.exists(sandbox_path):
                            with open(sandbox_path, "r", encoding="utf-8") as f:
                                ctx.codice_generato = f.read()
                            print("[AUTO-DEBUG] Reloaded patched code from sandbox file")
                    except Exception as e:
                        print(f"[AUTO-DEBUG] Failed to reload patched code: {e}")

                    print("[AUTO-DEBUG] Retrying sandbox with patched code")
                    retry_result = await ctx.agent.run_sandbox(ctx.topic, ctx.codice_generato)

                    if retry_result.get("success"):
                        print("[AUTO-DEBUG] Patch fixed the problem!")
                        strategy_data = {
                            "topic": ctx.topic,
                            "type": "bug_fix_strategy",
                            "description": "Patch generated by SWEAgent to fix sandbox failure",
                            "patch": patch_text,
                            "error": result.get("stderr", ""),
                            "success": True,
                        }
                        try:
                            await ctx.agent.strategy_memory.store_strategy_async(
                                ctx.topic, str(strategy_data), "success", 10.0,
                            )
                            print("[AUTO-DEBUG] Bug fix stored in StrategyMemory")
                        except Exception as e:
                            print(f"[AUTO-DEBUG] Strategy store failed: {e}")
                    else:
                        print("[AUTO-DEBUG] Patch did not fix the issue")

        except Exception as e:
            print(f"[AUTO-DEBUG] SWEAgent failed: {e}")

    async def _retry_gap_fill(self, ctx: StudyContext) -> None:
        """Re-synthesize theory with gap focus + regenerate sandbox code for retry."""
        # Reset progress for retry phases
        if ctx.progress:
            ctx.progress.phase_progress["VALIDATE"] = 0
            ctx.progress.phase_progress["EVALUATE"] = 0
            ctx.progress.phase_progress["CERTIFY"] = 0

        gaps = ctx.gaps
        focus = ctx.eval_data.get("improvement_focus", "")

        # Inject meta-critique if CriticAgent produced one (attempt >= 2)
        critique_block = ""
        if ctx.critic_meta_critique:
            critique_block = f"\n\nCRITICAL SELF-EVALUATION (read carefully — this is what you keep getting wrong):\n{ctx.critic_meta_critique}\n"
            print(f"[CRITIC-LLM] Injecting meta-critique into retry prompt for '{ctx.topic}'")

        # 1. Re-synthesize theory with gap focus
        gap_prompt = f"""
Previous study of "{ctx.topic}" had these gaps: {gaps}
Focus area: {focus}{critique_block}

Re-synthesize with emphasis on filling these specific gaps.
If the critical self-evaluation above identifies a systematic mistake, change your approach accordingly.
Use the same JSON format as before.
"""
        raw_gap = await ctx.agent._think_fast(gap_prompt, json_mode=True)
        try:
            gap_structured = json.loads(raw_gap)
            ctx.structured["concepts"].extend(gap_structured.get("concepts", []))
            ctx.structured["critical_questions"] = gap_structured.get(
                "critical_questions", ctx.structured.get("critical_questions"),
            )
        except Exception:
            pass

        # 2. Regenerate sandbox code targeting the gaps
        await ctx.emit(
            "SANDBOX", 0,
            f"Regenerating code (attempt {ctx.attempt + 1}/{MAX_RETRY}, gaps: {gaps[:2]})...",
        )
        regen_prompt = f"""
Rewrite a minimal executable Python script for: {ctx.topic}

The previous attempt had these gaps: {', '.join(str(g) for g in gaps[:3])}
Focus area: {focus}{critique_block}

Fix those gaps explicitly in the new implementation.
If the critical self-evaluation above identifies a systematic mistake, change your implementation approach accordingly.

Rules:
- valid Python, no markdown, no explanations, terminates automatically
- only use: Python stdlib, numpy, math, random, itertools, collections, concurrent.futures
- NO external APIs, NO pip installs, NO servers or infinite loops
"""
        try:
            ctx.codice_generato = await ctx.agent._think_fast(regen_prompt)
            if ctx.codice_generato and "```" in ctx.codice_generato:
                lines = ctx.codice_generato.split("\n")
                ctx.codice_generato = "\n".join(
                    l for l in lines if not l.strip().startswith("```")
                ).strip()
            if ctx.codice_generato:
                ctx.sandbox_result = await ctx.agent.run_sandbox(ctx.topic, ctx.codice_generato)
                success_icon = "passed" if ctx.sandbox_result.get("success") else "failed"
                print(f"[RETRY] Sandbox re-run: {success_icon}")
        except Exception as regen_err:
            print(f"[RETRY] Code regeneration failed (non-fatal): {regen_err}")


# ── 10. PostStudyPhase ────────────────────────────────────────────────────────

class PostStudyPhase(BasePhase):
    """Meta-learning update, strategy tracking, episodic memory store."""
    name = "POST_STUDY"
    fatal = False

    async def run(self, ctx: StudyContext) -> None:
        # Update strategy effectiveness tracking
        if ctx.strategy_obj:
            ctx.agent.tracker.update_strategy(ctx.strategy_obj, ctx.certified)
            await ctx.agent.strategy_memory.store_strategy_object_async(ctx.strategy_obj)

        # Meta-learning: record outcome and recompute stats
        try:
            ctx.agent.meta_learning.update(
                topic=ctx.topic,
                score=ctx.score,
                certified=ctx.certified,
                eval_data=ctx.eval_data,
                sandbox_result=ctx.sandbox_result,
                attempts=ctx.attempt,
            )
        except Exception as meta_err:
            print(f"[META] Non-fatal update error: {meta_err}")

        # Episodic memory: store episode
        try:
            import pathlib
            from importlib.util import spec_from_file_location, module_from_spec

            repo_root = pathlib.Path(__file__).resolve().parents[1]
            target = repo_root / "shard/memory/episodic_memory.py"
            spec = spec_from_file_location("shard_memory_episodic_memory", target)
            if spec and spec.loader:
                mod = module_from_spec(spec)
                spec.loader.exec_module(mod)
                store_episode = mod.store_episode

                episode = {
                    "timestamp": datetime.now().isoformat(),
                    "topic": ctx.topic,
                    "strategy_used": ctx.strategy_used,
                    "error_type": str(ctx.classified_error_type) if ctx.classified_error_type else None,
                    "error_signature": ctx.error_signature,
                    "sandbox_success": bool(ctx.sandbox_result.get("success", False)) if ctx.sandbox_result else False,
                    "files_modified": ctx.files_modified,
                    "evaluation_score": ctx.eval_data.get("score") if isinstance(ctx.eval_data, dict) else None,
                    "certified": bool(ctx.certified),
                }
                store_episode(episode)
                print(f"[EPISODIC] Episode stored for topic '{ctx.topic}'")
        except Exception as episode_err:
            print(f"[EPISODIC] Failed to store episode (non-fatal): {episode_err}")
