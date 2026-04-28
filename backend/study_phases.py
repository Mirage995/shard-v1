"""study_phases.py -- All pipeline phases for the SHARD study loop.

Each phase is a BasePhase subclass that reads from / writes to StudyContext.
The code inside each phase is lifted verbatim from study_agent.study_topic()
-- prompts, scraping logic, and validation mechanisms are UNCHANGED.

Phase list (in pipeline order):
  1. InitPhase           -- meta-learning hint + episodic memory context
  2. MapPhase            -- search sources (DuckDuckGo)
  3. AggregatePhase      -- scrape web pages (Playwright)
  4. SynthesizePhase     -- LLM synthesis + cross-reference
  5. StorePhase          -- persist to ChromaDB
  6. CrossPollinatePhase -- integration report (non-fatal)
  7. MaterializePhase    -- cheat sheet to filesystem (non-fatal)
  8. SandboxPhase        -- code gen + Docker exec + SWE repair (non-fatal)
  9. CertifyRetryGroup   -- VALIDATE -> EVALUATE -> BENCHMARK -> CERTIFY × N
 10. PostStudyPhase      -- meta-learning update, strategy tracking, episodic store (non-fatal)
"""
import asyncio
import json
import logging
import re
import sys
from datetime import datetime

_logger = logging.getLogger("shard.study")

from study_pipeline import BasePhase
from study_context import StudyContext
from constants import SUCCESS_SCORE_THRESHOLD, PROVIDERS_PRIMARY
from backend.vlm_ingestion import describe_images
from backend.benchmark_generator import is_network_topic

# MAX_RETRY lives here (was a module-level constant in study_agent.py)
MAX_RETRY = 3

# L3 context gate: predicted score below this threshold triggers deep context load
# (cross-topic memory links). Set here for easy tuning.
L3_THRESHOLD = 6.0

# Synthetic link_weight assigned to same-topic failures (beats cross-topic borderlines).
SAME_TOPIC_BOOST = 3.5


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

        # Semantic memory: inject ChromaDB-matched past episodes and knowledge
        try:
            from semantic_memory import query_semantic_memory
            _sem_ctx = query_semantic_memory(ctx.topic, top_k=3, min_score=0.35)
            if _sem_ctx:
                ctx.episode_context = (ctx.episode_context or "") + "\n\n" + _sem_ctx
                print(f"[SEMANTIC] Injected {len(_sem_ctx)} chars of semantic context for '{ctx.topic}'")
        except Exception:
            pass  # semantic memory is always non-fatal

        # Self model: inject who SHARD is, what it knows, what it keeps failing
        try:
            from self_model import SelfModel
            _sm = SelfModel.load()
            if _sm:
                ctx.episode_context = (_sm.as_prompt_fragment() + "\n\n"
                                       + (ctx.episode_context or ""))
        except Exception:
            pass  # self model is always non-fatal

        # World model: inject relevance signal for this specific topic
        try:
            from world_model import WorldModel
            _wm = WorldModel.load_or_default()
            _rel = _wm.relevance(ctx.topic)
            _domain = _wm.domain_of(ctx.topic)
            if _rel > 0.3:
                _wm_hint = (
                    f"[WORLD MODEL] Topic '{ctx.topic}' -- "
                    f"relevance={round(_rel*100)}%  domain={_domain}. "
                    f"This is a high-value skill in the current software landscape."
                )
                ctx.episode_context = (ctx.episode_context or "") + "\n\n" + _wm_hint
        except Exception:
            pass  # world model is always non-fatal

        # Principle layer: inject relevant cross-domain principles accumulated over time
        try:
            from principle_engine import inject_principles
            _principles_ctx = inject_principles(ctx.topic)
            if _principles_ctx:
                ctx.episode_context = (ctx.episode_context or "") + "\n\n" + _principles_ctx
                print(f"[PRINCIPLES] Injected principle layer for '{ctx.topic}'")
        except Exception:
            pass  # principle layer is always non-fatal

        # Task context: inject actual task files (README + code + tests) as primary signal
        # This ensures MAP queries are grounded in what SHARD actually needs to solve,
        # not in generic web results for the topic name.
        if ctx.task_context:
            ctx.episode_context = (
                "[TASK CONTEXT — primary study material]\n"
                + ctx.task_context
                + "\n\n"
                + (ctx.episode_context or "")
            )
            print(f"[TASK CONTEXT] Injected {len(ctx.task_context)} chars of task context for '{ctx.topic}'")

        # Phase 0 memory: "what do I already know about this topic?"
        # Queries SHARD.MEMORY for all memory types before any study begins.
        # Prepended so it's the first context SYNTHESIZE sees — SHARD starts
        # from known ground instead of from zero every session.
        try:
            _prior = ctx.agent._memory_context_block(
                ctx.topic,
                memory_types=None,   # all types: FACT, RELATION, EPISODE, GOAL, PREFERENCE
                label="WHAT SHARD ALREADY KNOWS",
                limit=8,
            )
            if _prior:
                ctx.episode_context = _prior + "\n\n" + (ctx.episode_context or "")
                print(f"[MEMORY P0] Prior knowledge injected ({_prior.count(chr(10))} lines) for '{ctx.topic}'")
        except Exception:
            pass  # always non-fatal

        # L3 gate: cross-topic memory links (from link_builder / #40)
        # Only loaded when SHARD is likely to struggle:
        #   - predicted score below L3_THRESHOLD, OR
        #   - topic is a known blind spot, OR
        #   - there are previous failures on this topic
        _predicted    = getattr(ctx, "predicted_score", None)
        _blind_spots  = getattr(ctx, "blind_spots", []) or []
        _has_failures = getattr(ctx, "previous_attempts", 0) >= 1
        _is_blind     = ctx.topic in _blind_spots or any(
            bs.lower() in ctx.topic.lower() for bs in _blind_spots
        )
        _load_l3 = (
            _predicted is None               # new topic: load to be safe
            or _predicted < L3_THRESHOLD     # predicted struggle
            or _is_blind                     # known blind spot
            or _has_failures                 # past failures on this topic
        )
        _l3_reason = (
            ("new_topic " if _predicted is None else "")
            + (f"low_pred={_predicted:.1f} " if _predicted is not None and _predicted < L3_THRESHOLD else "")
            + ("blind_spot " if _is_blind else "")
            + ("retry " if _has_failures else "")
        ).strip() or "n/a"
        print(f"[L3] loaded={_load_l3} predicted={_predicted} attempts={getattr(ctx, 'previous_attempts', 0)} reason={_l3_reason}")

        if _load_l3:
            try:
                from link_builder import MemoryLinkBuilder
                _cross = MemoryLinkBuilder.get_cross_topic_links(
                    ctx.topic, min_weight=2, limit=10
                )
                if _cross:
                    _cross_lines = [
                        f"  [{r['source_ref']}] {r['content']} (confidence={r['confidence']:.2f})"
                        for r in _cross
                    ]
                    _cross_block = (
                        "[CROSS-TOPIC MEMORY LINKS — related knowledge from other domains]\n"
                        + "\n".join(_cross_lines)
                    )
                    ctx.episode_context = (ctx.episode_context or "") + "\n\n" + _cross_block
                    print(f"[L3] Injected {len(_cross)} cross-topic link(s) for '{ctx.topic}'")
            except Exception:
                pass  # always non-fatal

        # [PREVIOUS FAILURES] injection — composite-ranked, deduped by error_type.
        # UNION: same-topic failures get synthetic weight=3.0 (highest priority);
        # cross-topic failures carry their actual link weight.
        try:
            from shard_db import query as _db_query
            import re as _re
            from datetime import datetime as _dt
            _resolved = getattr(ctx, "resolved_errors", set())
            _raw_failures = _db_query(
                """SELECT m.content, m.created_at, ? AS link_weight
                   FROM memories m
                   WHERE m.memory_type='EPISODE_FAILURE' AND m.source_ref=? AND m.is_latest=1
                   UNION ALL
                   SELECT m2.content, m2.created_at, ml.weight
                   FROM memory_links ml
                   JOIN memories m2 ON ml.target_id = m2.id
                   WHERE ml.source_id IN (
                       SELECT id FROM memories WHERE source_ref=? AND is_latest=1 LIMIT 5
                   ) AND ml.weight >= 2 AND m2.is_latest=1 AND m2.memory_type='EPISODE_FAILURE'
                   LIMIT 20""",
                (SAME_TOPIC_BOOST, ctx.topic, ctx.topic),
            )
            if _raw_failures:
                _now = _dt.now()
                def _fscore(r):
                    try:
                        _hrs = (_now - _dt.fromisoformat(r["created_at"])).total_seconds() / 3600
                    except Exception:
                        _hrs = 168
                    _s = 0.6 * float(r["link_weight"]) + 0.4 / (1.0 + _hrs)
                    # Penalise errors already resolved this session
                    _m2 = _re.search(r"Error type:\s*(\S+)", r["content"])
                    _et = _m2.group(1).rstrip(".") if _m2 else ""
                    if _et and _et in _resolved:
                        _s *= 0.5
                    return _s

                # Rank, then dedup by error_type (keep best-scored per type)
                _ranked = sorted(_raw_failures, key=_fscore, reverse=True)
                _seen_types: set = set()
                _deduped = []
                for _r in _ranked:
                    _m = _re.search(r"Error type:\s*(\S+)", _r["content"])
                    _etype = _m.group(1).rstrip(".") if _m else "unknown"
                    if _etype not in _seen_types:
                        _seen_types.add(_etype)
                        _deduped.append(_r)
                    if len(_deduped) == 3:
                        break

                if _deduped:
                    _fail_lines = [f"  - {r['content'][:180]}" for r in _deduped]
                    _fail_block = "[PREVIOUS FAILURES — avoid repeating these mistakes]\n" + "\n".join(_fail_lines)
                    ctx.episode_context = (ctx.episode_context or "") + "\n\n" + _fail_block
                    _logger.info("[FAIL-REUSE] Injecting %d previous failure(s) for '%s' (types: %s)",
                                 len(_deduped), ctx.topic, list(_seen_types))
        except Exception:
            pass  # always non-fatal


# ── 2. MapPhase ──────────────────────────────────────────────────────────────

class MapPhase(BasePhase):
    """Search sources with multiple targeted queries."""
    name = "MAP"
    fatal = True

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("MAP", 0, f"Searching sources for '{ctx.topic}'...")
        if ctx.research_mode:
            ctx.sources = await ctx.agent._fetch_arxiv_phase(ctx.topic)
        else:
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

        # Prepend task_context as primary signal — overrides noisy web scraping
        if ctx.task_context:
            ctx.raw_text = (
                "[TASK CONTEXT — authoritative source, prioritize over web results]\n"
                + ctx.task_context
                + "\n\n[WEB SOURCES]\n"
                + ctx.raw_text
            )
            print(f"[TASK CONTEXT] Prepended to raw_text ({len(ctx.task_context)} chars)")

        if ctx.pdf_paths:
            await ctx.emit("AGGREGATE", 0, f"Extracting images from {len(ctx.pdf_paths)} PDF(s)...")
            try:
                from backend.pdf_extractor import extract_pdf_images, extract_pdf_text
                import os
                visual_input_dir = os.path.join(os.path.dirname(__file__), "..", "shard_workspace", "visual_input")
                for pdf_path in ctx.pdf_paths:
                    extracted = await asyncio.to_thread(extract_pdf_images, pdf_path, visual_input_dir)
                    ctx.image_paths.extend(extracted)
                    print(f"[PDF] Extracted {len(extracted)} images from {pdf_path}")
                    pdf_text = await asyncio.to_thread(extract_pdf_text, pdf_path)
                    if pdf_text.strip():
                        ctx.raw_text = "\n\n".join(p for p in [ctx.raw_text.strip(), f"[PDF TEXT]\n{pdf_text[:8000]}"] if p)
                        print(f"[PDF] Appended {len(pdf_text)} chars of PDF text.")
            except Exception as e:
                print(f"[PDF] Non-fatal PDF extraction error: {e}")

        if ctx.image_paths:
            await ctx.emit("AGGREGATE", 0, f"Describing {len(ctx.image_paths)} image(s)...")
            try:
                visual_text = await asyncio.to_thread(describe_images, ctx.image_paths, ctx.topic)
            except Exception as e:
                print(f"[VLM] Non-fatal visual ingestion error: {e}")
                visual_text = ""
            if visual_text.strip():
                ctx.raw_text = "\n\n".join(part for part in [ctx.raw_text.strip(), visual_text.strip()] if part)
                print(f"[VLM] Appended {len(visual_text)} chars of visual evidence.")

        print(f"[AGGREGATE] Phase completed. {len(ctx.raw_text)} chars scraped.")

        if not ctx.raw_text.strip():
            await ctx.emit("ERROR", 0, "No content could be scraped from any source.")
            if ctx.on_error:
                await ctx.on_error(ctx.topic, "AGGREGATE", "No content could be scraped from any source")
            raise RuntimeError("No content scraped -- aborting pipeline")


# ── 4. SynthesizePhase ───────────────────────────────────────────────────────

class SynthesizePhase(BasePhase):
    """LLM synthesis + cross-referencing with existing knowledge."""
    name = "SYNTHESIZE"
    fatal = True

    async def run(self, ctx: StudyContext) -> None:
        await ctx.emit("SYNTHESIZE", 0, "Building structured knowledge...")

        # Vettore 1 -- CognitionCore: query experience before synthesis
        # If sandbox always returned 0 in past attempts, inject STRUCTURAL PIVOT
        core = getattr(ctx.agent, "cognition_core", None)
        if core is not None:
            try:
                exp = core.query_experience(ctx.topic)
                ctx.core_experience = exp
                if exp.get("sandbox_always_zero") or (exp.get("chronic_fail") and exp.get("attempt_count", 0) >= 2):
                    # Vettore 3: try to get a DIRECTED recommendation from MetaLearning
                    strat_rec = core.query_strategy_recommendation(ctx.topic)
                    if strat_rec.get("has_history") and strat_rec.get("best_strategy_text"):
                        cat = strat_rec["category"]
                        cr  = strat_rec["category_cert_rate"]
                        ctx.v3_recommended_strategy = strat_rec["best_strategy_text"]
                        ctx.pivot_directive = (
                            f"PAST FAILURE PATTERN DETECTED: sandbox returned 0 in "
                            f"{exp['attempt_count']} previous attempts for this topic. "
                            "The theoretical approach is NOT working. "
                            f"[VETTORE 3 -- DIRECTED PIVOT for '{cat}' (cert_rate={cr:.0%} storico)]: "
                            f"{strat_rec['best_strategy_text']} "
                            "Apply this pattern concretely: executable code, step-by-step, real data."
                        )
                        print(f"[VETTORE 1+3] Directed pivot for '{ctx.topic}' -- category={cat} cr={cr:.0%}")
                    else:
                        # Fallback: generic pivot (no MetaLearning history yet)
                        ctx.pivot_directive = (
                            f"PAST FAILURE PATTERN DETECTED: sandbox returned 0 in "
                            f"{exp['attempt_count']} previous attempts for this topic. "
                            "The theoretical approach is NOT working. "
                            "This synthesis MUST prioritize EXECUTABLE implementation patterns: "
                            "concrete algorithms, step-by-step code structures, real data examples. "
                            "Avoid abstract theory. Think: what Python code do I write, "
                            "in what exact order, with what data structures."
                        )
                        print(f"[VETTORE 1] Generic pivot for '{ctx.topic}' -- no MetaLearning history")
                    await ctx.emit("SYNTHESIZE", 0, "[COGNITION] Structural pivot activated -- shifting to executable focus")
            except Exception as _ce:
                pass  # non-fatal

        empirical_context = ""
        if ctx.research_mode:
            try:
                empirical_context = ctx.agent.cognition_core.query_empirical(ctx.topic)
            except Exception:
                pass  # non-fatal

        # Vettore 1+2 -- Full GWT relational_context at attempt 0 (synthesize-time).
        # Closes the 50%-coverage gap: previously GWT only fired on retry, so topics
        # that certified at attempt 0 (mostly tactical) never exercised the workspace.
        core_relational = ""
        if core is not None and not ctx.no_l3:
            try:
                core_relational = core.relational_context(ctx.topic, research_mode=ctx.research_mode)
                ctx.core_relational_ctx = core_relational
                print(f"[VETTORE 1+2] CognitionCore relational_context injected at synthesize (attempt {ctx.attempt})")
            except Exception as _cre:
                print(f"[VETTORE 1+2] relational_context FAILED at synthesize: {_cre}")

        ctx.structured = await ctx.agent.phase_synthesize(
            ctx.topic, ctx.raw_text,
            strategy_hint=ctx.best_strategy,
            previous_score=ctx.previous_score,
            episode_context=ctx.episode_context,
            pivot_directive=ctx.pivot_directive,
            research_mode=ctx.research_mode,
            sources=ctx.sources if ctx.research_mode else None,
            empirical_context=empirical_context,
            core_relational_ctx=core_relational,
        )
        print(f"[SYNTHESIZE] Phase completed. {len(ctx.structured.get('concepts', []))} concepts extracted.")
        # Persist diversity block for calibration logging in ExperimentDesignPhase
        _blocked = ctx.structured.pop("_domain_pairs_blocked", None)
        if _blocked is None:
            print("[SYNTHESIZE][WARN] No _domain_pairs_blocked received from phase_synthesize -- propagation gap")
        ctx.domain_pairs_blocked = _blocked or []

        # ── Novelty gate for research mode hypotheses (#48) ───────────────────
        # If hypothesis is already a well-known established finding, retry once
        # with an explicit "avoid this known connection" instruction injected.
        if ctx.research_mode and ctx.structured and ctx.structured.get("hypothesis"):
            try:
                _hyp = ctx.structured["hypothesis"]
                _is_novel, _novelty_reason = await ctx.agent._check_hypothesis_novelty(_hyp)
                if not _is_novel:
                    print(
                        f"[NOVELTY] Hypothesis already well-known ({_novelty_reason}) -- "
                        f"retrying synthesis: '{_hyp.get('statement', '')[:70]}'"
                    )
                    _known_block = (
                        f"\n[NOVELTY BLOCK — AVOID]\n"
                        f"This hypothesis is already a well-established finding and must NOT be repeated:\n"
                        f"  '{_hyp.get('statement', '')}'\n"
                        f"Generate a DIFFERENT, more original hypothesis that has NOT been widely studied.\n"
                    )
                    ctx.structured = await ctx.agent.phase_synthesize(
                        ctx.topic, ctx.raw_text,
                        strategy_hint=ctx.best_strategy,
                        previous_score=ctx.previous_score,
                        episode_context=ctx.episode_context,
                        pivot_directive=ctx.pivot_directive,
                        research_mode=ctx.research_mode,
                        sources=ctx.sources if ctx.research_mode else None,
                        empirical_context=empirical_context + _known_block,
                    )
                    print(f"[NOVELTY] Retry complete. New hypothesis: '{(ctx.structured or {}).get('hypothesis', {}).get('statement', 'none')[:70]}'")
            except Exception as _nv_err:
                pass  # non-fatal

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
        from constants import CROSS_POLLINATION_ENABLED
        if not CROSS_POLLINATION_ENABLED:
            print("[CROSS-POLLINATE] Skipped (CROSS_POLLINATION_ENABLED=False)")
            return

        await ctx.emit("CROSS_POLLINATE", 0, "Generating Integration Report...")
        ctx.integration_report = await ctx.agent.phase_cross_pollinate(
            ctx.topic, ctx.raw_text, ctx.structured,
        )
        if ctx.integration_report:
            await ctx.emit("CROSS_POLLINATE", 0, f"Integration Report: {ctx.integration_report[:100]}...")

        # Extract structured principles and persist to principles.json
        try:
            from principle_engine import extract_principles
            added = extract_principles(ctx.integration_report, ctx.topic)
            if added:
                print(f"[PRINCIPLES] Extracted {len(added)} new principles from '{ctx.topic}'")
        except Exception as _pe_err:
            print(f"[PRINCIPLES] Non-fatal extraction error: {_pe_err}")

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
VALIDATION REQUIREMENTS (mandatory -- this is how correctness is verified):

After your implementation, write at least 3 assert statements that test real behavior:
- Test normal inputs with known correct outputs
- Test edge cases (empty input, zero, negative, boundary values)
- Test that the implementation actually does what the topic requires

End with exactly this line:
    print("OK All assertions passed")

Example structure:
    def my_function(x):
        # ... implementation ...

    # Validation
    assert my_function(2) == 4, "basic case failed"
    assert my_function(0) == 0, "zero edge case failed"
    assert my_function(-1) == 1, "negative edge case failed"
    print("OK All assertions passed")

IMPORTANT: assert statements must test actual output values, not just that the function runs.
BAD:  assert my_function(2) is not None
GOOD: assert my_function(2) == 4
"""

        # ── Network topic flag (needed for both prompt and import ban below) ──
        _is_net_topic = is_network_topic(ctx.topic)

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

        if _is_net_topic:
            prompt_codice += """

*** SANDBOX CONSTRAINT — MANDATORY, NO EXCEPTIONS ***

This sandbox has ZERO internet access (Docker --network none).
ANY call to a real URL, hostname, or IP address will raise a connection error and your code will FAIL.
Do NOT call httpbin.org, localhost, example.com, or any real server. They do not exist here.

You MUST mock ALL network I/O using unittest.mock BEFORE any network call is made.
No mock = connection error = immediate failure. There is no alternative.

REQUIRED pattern for requests:
  import requests, unittest.mock
  _mock_resp = unittest.mock.MagicMock()
  _mock_resp.status_code = 200
  _mock_resp.json.return_value = {"key": "value"}
  _mock_resp.raise_for_status = lambda: None
  requests.get = lambda *a, **kw: _mock_resp
  # now call requests.get() normally -- the mock intercepts it

REQUIRED pattern for socket:
  import socket, unittest.mock
  _mock_sock = unittest.mock.MagicMock()
  _mock_sock.recv.return_value = b"HTTP/1.1 200 OK\\r\\n\\r\\nHello"
  _mock_sock.recvfrom.return_value = (b"response_data", ("127.0.0.1", 12345))
  socket.socket = lambda *a, **kw: _mock_sock
  # now call socket.socket() normally -- the mock intercepts it
  # recvfrom() returns a (data, addr) tuple -- required for UDP patterns like:
  #   data, addr = sock.recvfrom(1024)

Allowed imports: socket, requests, http.client, urllib, urllib.request, urllib.parse, unittest.mock, collections, json, struct, base64, hashlib
DO NOT use: pytest-mock, responses, httpretty, aioresponses, or any non-stdlib mock library.
"""
        else:
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

        # ── Network import check (fail fast, skipped for mock-network topics) ──
        # For network topics (#20), socket/requests/etc. are allowed because
        # the code uses unittest.mock to patch them -- no real connection made.
        if _is_net_topic:
            print(f"[SANDBOX] Network topic '{ctx.topic}' -- skipping import ban, expecting unittest.mock usage")
        else:
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
                print(f"[SANDBOX] Network import detected: '{banned_line}' -- retry {_net_retries}/{_MAX_NET_RETRIES}")
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
                    print("[SANDBOX] Network import persists after retries -- aborting sandbox execution")
                    ctx.codice_generato = None

        # ── Network code cleaner (AST rewrite before sandbox) ────────────
        # Rewrites 'with socket.socket(...) as s:' → try/finally pattern so
        # that unittest.mock monkeypatching works correctly in benchmarks.
        # Silent, idempotent, fail-safe -- original code returned on any error.
        if ctx.codice_generato and is_network_topic(ctx.topic):
            from backend.code_cleaner import clean_network_code as _clean
            _cleaned = _clean(ctx.codice_generato)
            if _cleaned != ctx.codice_generato:
                print(f"[CODE_CLEANER] Rewrote 'with socket.socket()' in solve() for '{ctx.topic}'")
                ctx.codice_generato = _cleaned

        # ── Mock injection (external service deps) ───────────────────────
        # Prepend minimal mocks for redis/requests/psycopg2/pymongo so that
        # code exercising external services runs in the sandboxed Docker
        # environment without a real server. Idempotent and fail-safe.
        if ctx.codice_generato:
            try:
                from mock_injector import inject_mocks as _inject_mocks
                _patched = _inject_mocks(ctx.codice_generato, ctx.topic)
                if _patched != ctx.codice_generato:
                    ctx.codice_generato = _patched
            except Exception as _mi_err:
                pass  # always non-fatal

        # ── Execution ────────────────────────────────────────────────────
        if ctx.codice_generato:
            try:
                await ctx.emit("SANDBOX", 0, "Executing generated code")
                print("[SANDBOX] Executing generated code")

                ctx.sandbox_result = await ctx.agent.run_sandbox(ctx.topic, ctx.codice_generato)

                # ── Assertion marker check ────────────────────────────────
                # If code ran but assertions marker is missing, treat as
                # functional failure -- code ran but proved nothing.
                if ctx.sandbox_result.get("success", False):
                    stdout = ctx.sandbox_result.get("stdout", "")
                    # Check for marker without the OK character to avoid Windows/Docker
                    # encoding corruption (OK arrives as âœ" on some Windows setups)
                    if "All assertions passed" not in stdout:
                        print("[SANDBOX] [WARN]️  No assertion marker in stdout -- code ran but did not validate behavior")
                        ctx.sandbox_result["success"] = False
                        ctx.sandbox_result["stderr"] = (
                            ctx.sandbox_result.get("stderr", "") +
                            "\n[SANDBOX] AssertionError: missing 'OK All assertions passed' -- "
                            "add assert statements that verify actual output values, "
                            "then print('OK All assertions passed')"
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

        # Detect assertion failure vs crash -- different repair strategies
        is_assertion_failure = (
            "AssertionError" in stderr_text
            or "All assertions passed" in stderr_text
        )
        if is_assertion_failure:
            print("[SANDBOX] Assertion failure detected -- code logic is wrong, not syntax")
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
            print("[SIMULATION] no sandbox file path -- skipping repair")

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
                raise  # fatal -- propagates to pipeline

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
                ctx.best_score = max(ctx.best_score, ctx.score)

                # Strategy extraction + storage
                await self._extract_and_store_strategy(ctx)

                # Experiment cache + replay
                if ctx.eval_data and ctx.eval_data.get("score", 0) < SUCCESS_SCORE_THRESHOLD:
                    current_skills = len(ctx.agent.capability_graph.capabilities) if ctx.agent.capability_graph else 0
                    ctx.agent.experiment_cache.register_failure(ctx.topic, current_skills)

                ctx.agent.replay_engine.add_experiment(ctx.topic)

            except Exception as e:
                raise  # fatal -- propagates to pipeline

            # ── BENCHMARK (non-fatal) ────────────────────────────────
            try:
                bench_update = await ctx.agent.phase_benchmark(
                    ctx.topic, ctx.codice_generato or "", ctx.eval_data,
                )
                ctx.eval_data = {**ctx.eval_data, **bench_update}
                ctx.score = ctx.eval_data.get("score", ctx.score)
                ctx.best_score = max(ctx.best_score, ctx.score)
            except Exception as bench_phase_err:
                print(f"[BENCHMARK] Non-fatal phase error -- skipping: {bench_phase_err}")

            # ── CERTIFY ──────────────────────────────────────────────
            ctx.certified = await ctx.agent.phase_certify(ctx.topic, ctx.eval_data)

            if ctx.certified:
                await ctx.emit("CERTIFY", ctx.score, f"Topic certified! Score: {ctx.score}/10")
                await ctx.emit("CERTIFY", ctx.score, f"SHARD stance: {ctx.eval_data.get('shard_stance', '')[:120]}")
                # Mark any classified error from this attempt as resolved so
                # the next topic's [PREVIOUS FAILURES] block won't over-warn.
                if ctx.classified_error_type:
                    ctx.resolved_errors.add(ctx.classified_error_type)
                if ctx.on_certify:
                    await ctx.on_certify(ctx.topic, ctx.score, {
                        **ctx.eval_data,
                        "sandbox": ctx.sandbox_result,
                        "concepts": ctx.structured.get("concepts", []),
                        "shard_opinion": ctx.structured.get("shard_opinion", ""),
                        "connections": ctx.connections,
                        "validation_qa": ctx.validation_data.get("validation_qa", []),
                        "winning_code": ctx.codice_generato or "",
                    })

                # Knowledge contradiction check -- fires at certification time
                # Compares new knowledge against ChromaDB before it pollutes the KB
                await self._check_knowledge_contradictions(ctx)

                # Extract typed memories from certified knowledge → shard.db memories table
                await self._extract_and_store_memories(ctx)

                # Self-generated benchmarks post-certification
                await self._post_certify_benchmarks(ctx)

            else:
                ctx.gaps = ctx.eval_data.get("gaps", [])
                focus = ctx.eval_data.get("improvement_focus", "")
                await ctx.emit("VALIDATE", ctx.score, f"Score {ctx.score}/10 -- Retrying. Focus: {focus[:80]}")

                if ctx.attempt < MAX_RETRY:
                    # On attempt 2+: ask CriticAgent for LLM meta-critique
                    # "What am I doing wrong systematically?" -- injects into retry prompt
                    if ctx.attempt >= 2:
                        try:
                            # Vettore 2 -- CognitionCore: pass identity to CriticAgent
                            # "How confident are we really in this category?"
                            _identity_ctx = None
                            _core = getattr(ctx.agent, "cognition_core", None)
                            if _core is not None:
                                _identity_ctx = _core.query_identity()
                            # Desire engine: inject frustration_hits into identity context
                            try:
                                from desire_engine import get_desire_engine as _get_de3
                                _frustration = _get_de3().get_frustration(ctx.topic)
                                if _identity_ctx is None:
                                    _identity_ctx = {}
                                _identity_ctx["frustration_hits"] = _frustration
                            except Exception:
                                pass
                            critique = await ctx.agent.critic_agent.analyze_with_llm(
                                ctx.topic, ctx.score, ctx.gaps, ctx.attempt,
                                identity_context=_identity_ctx,
                            )
                            if critique:
                                ctx.critic_meta_critique = critique
                                await ctx.emit("VALIDATE", ctx.score, f"[CRITIC] {critique[:100]}...")
                        except Exception as _ce:
                            pass  # non-fatal
                    await self._retry_gap_fill(ctx)

        if not ctx.certified:
            _best = getattr(ctx, "best_score", ctx.score)
            await ctx.emit("FAILED", ctx.score, f"Could not certify '{ctx.topic}' after {MAX_RETRY} attempts. Best: {_best}/10")
            # #42 EPISODE_FAILURE: use best_score (last attempt can regress).
            # Also fire for benchmark-only failures (classified_error_type may be None).
            if _best >= 1.5:
                await self._store_failure_memory(ctx)

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

    async def _extract_and_store_memories(self, ctx: StudyContext) -> None:
        """Extract typed memories from certified knowledge → shard.db memories table.

        Runs post-certification (non-fatal). Extracts FACT/PREFERENCE/EPISODE/GOAL/RELATION
        objects from ctx.structured and persists them with is_latest tracking.
        """
        extractor = getattr(ctx.agent, "memory_extractor", None)
        if not extractor:
            return
        try:
            memories = await extractor.extract_from_study(
                topic=ctx.topic,
                structured=ctx.structured,
                score=ctx.score,
                certified=ctx.certified,
            )
            if memories:
                saved = extractor.save(memories)
                print(
                    f"[MEMORY] Extracted {saved}/{len(memories)} typed memories "
                    f"for '{ctx.topic}'"
                )
            else:
                print(f"[MEMORY] No memories extracted for '{ctx.topic}'")
        except Exception as e:
            print(f"[MEMORY] Non-fatal extraction error: {e}")

    async def _check_knowledge_contradictions(self, ctx: StudyContext) -> None:
        """Run CertContradictionChecker after certification (non-fatal).

        Compares newly certified knowledge against ChromaDB.
        Logs MEDIUM+ contradictions to self_inconsistencies.jsonl.
        """
        checker = getattr(ctx.agent, "cert_contradiction_checker", None)
        if not checker:
            return
        try:
            result = await checker.check(
                topic=ctx.topic,
                structured=ctx.structured,
            )
            if result.get("has_contradiction"):
                severity = result.get("severity", "?")
                ctype    = result.get("contradiction_type", "?")
                expl     = result.get("explanation", "")[:120]
                res      = result.get("resolution", "PENDING")
                print(
                    f"[CERT_CONTRADICTION] ⚠️  {severity} {ctype} on '{ctx.topic}' "
                    f"→ {res} | {expl}"
                )
                # Auto-resolve if severity is HIGH or CRITICAL and resolution is actionable
                _AUTO_RESOLVE_MIN = {"HIGH", "CRITICAL"}
                _AUTO_RESOLVE_OK  = {"KEEP_NEW", "KEEP_OLD", "MERGE", "DEPRECATE_BOTH"}
                if severity in _AUTO_RESOLVE_MIN and res in _AUTO_RESOLVE_OK:
                    print(f"[CERT_CONTRADICTION] Auto-resolving ({res})...")
                    resolution_result = await checker.resolve(ctx.topic, result)
                    action = resolution_result.get("action", "?")
                    detail = resolution_result.get("detail", "")
                    if resolution_result.get("resolved"):
                        print(f"[CERT_CONTRADICTION] ✓ Resolved: {action} — {detail}")
                    else:
                        print(f"[CERT_CONTRADICTION] Resolution failed: {detail}")
            else:
                print(f"[CERT_CONTRADICTION] ✓ No contradiction found for '{ctx.topic}'")
        except Exception as e:
            print(f"[CERT_CONTRADICTION] Non-fatal error: {e}")

    async def _post_certify_benchmarks(self, ctx: StudyContext) -> None:
        """Run self-generated benchmarks after certification using real async generator."""
        try:
            # Use the real async generate() — NOT the legacy stub
            benchmark_data = await ctx.agent.benchmark_generator.generate(
                topic=ctx.topic,
                synthesized_code=ctx.codice_generato or "",
                n_tests=3,
            )

            if not benchmark_data.get("available"):
                print(f"[BENCHMARK] post-certify: generator unavailable for '{ctx.topic}'")
                return

            # Ensure implementation has def solve(input_data) signature.
            # ctx.codice_generato is free-form code from the sandbox phase — it may
            # use any function name.  benchmark_runner requires exactly def solve(.
            impl_code = ctx.codice_generato or ""
            if "def solve(" not in impl_code:
                scaffold = benchmark_data.get("scaffold", "def solve(input_data):\n    pass")
                import re as _re_pcb
                solve_prompt = (
                    f"You just studied and were certified on: '{ctx.topic}'.\n"
                    f"Implement the following scaffold by applying what you know:\n\n"
                    f"{scaffold}\n\n"
                    f"Return ONLY the complete Python function. No explanation, no markdown."
                )
                try:
                    new_impl = await ctx.agent._think_fast(solve_prompt)
                    new_impl = _re_pcb.sub(r"```(?:python)?|```", "", new_impl or "").strip()
                    if new_impl and "def solve(" in new_impl:
                        impl_code = new_impl
                        print(f"[BENCHMARK] post-certify: generated solve() impl ({len(impl_code)} chars)")
                    else:
                        print(f"[BENCHMARK] post-certify: solve() generation failed — skipping benchmark")
                        return
                except Exception as _e:
                    print(f"[BENCHMARK] post-certify: solve() generation error: {_e} — skipping")
                    return

            # Run via real async run_benchmark() — signature: (benchmark, implementation_code, topic)
            result = await ctx.agent.benchmark_runner.run_benchmark(
                benchmark=benchmark_data,
                implementation_code=impl_code,
                topic=ctx.topic,
            )

            passed = result.get("passed", 0)
            total = result.get("total", 0)
            pass_rate = result.get("pass_rate", 0.0)
            success = result.get("success", False)
            status = "PASS" if success else "FAIL"
            print(f"[BENCHMARK] post-certify '{ctx.topic}' | {passed}/{total} | {status}")
            ctx.benchmark_result = {
                "pass_rate":           pass_rate,
                "passed":              passed,
                "total":               total,
                "success":             success,
                "dominant_input_type": result.get("dominant_input_type"),
            }

            # Type-mismatch recovery: if 0% pass rate and we know the dominant type,
            # regenerate the implementation with an explicit type constraint and retry once.
            dominant_type = result.get("dominant_input_type")
            if pass_rate == 0.0 and total > 0 and dominant_type:
                print(
                    f"[BENCHMARK] 0/{total} pass rate — dominant input_data type is '{dominant_type}'. "
                    f"Attempting type-constrained regeneration..."
                )
                type_regen_prompt = f"""Rewrite a minimal executable Python script for: {ctx.topic}

CRITICAL CONSTRAINT: The function solve(input_data) will be called with input_data of type '{dominant_type}'.
Your implementation MUST handle {dominant_type} input correctly.
Do NOT call dict methods (.items(), .keys(), .values()) on a list.
Do NOT call list methods (.append(), indexing) on a dict.
Match the actual type.

Previous implementation for reference (type handling was wrong):
{impl_code[:800]}

Rules:
- valid Python, no markdown, no explanations, terminates automatically
- only use: Python stdlib, numpy, math, random, itertools, collections, concurrent.futures
- NO external APIs, NO pip installs, NO servers or infinite loops
"""
                try:
                    new_code = await ctx.agent._think_fast(type_regen_prompt)
                    if new_code and "```" in new_code:
                        new_code = "\n".join(
                            l for l in new_code.split("\n")
                            if not l.strip().startswith("```")
                        ).strip()
                    if new_code and "def solve(" in new_code:
                        ctx.codice_generato = new_code
                        retry_result = await ctx.agent.benchmark_runner.run_benchmark(
                            benchmark=benchmark_data,
                            implementation_code=new_code,
                            topic=ctx.topic,
                        )
                        r_passed = retry_result.get("passed", 0)
                        r_total = retry_result.get("total", 0)
                        print(
                            f"[BENCHMARK] type-constrained retry '{ctx.topic}': "
                            f"{r_passed}/{r_total} passed"
                        )
                        result = retry_result
                        passed = r_passed
                        total = r_total
                        success = retry_result.get("success", False)
                except Exception as regen_err:
                    print(f"[BENCHMARK] type-constrained regen failed (non-fatal): {regen_err}")

            # Cross-domain concrete angle fallback: still 0% after type retry →
            # ask SHARD to find a connected certified topic and propose a concrete
            # Python problem that demonstrates the abstract topic. Benchmark still
            # runs in full — nothing is skipped.
            if passed == 0 and total > 0:
                xd_result = await self._cross_domain_benchmark(ctx)
                if xd_result and xd_result.get("passed", 0) > 0:
                    result  = xd_result
                    passed  = xd_result.get("passed", 0)
                    total   = xd_result.get("total", 0)
                    success = xd_result.get("success", False)
                    ctx.benchmark_result = {
                        "pass_rate":           xd_result.get("pass_rate", 0.0),
                        "passed":              passed,
                        "total":               total,
                        "success":             success,
                        "dominant_input_type": xd_result.get("dominant_input_type"),
                        "cross_domain":        True,
                    }

            if not success:
                try:
                    analysis = ctx.agent.critic_agent.analyze_failure(result)
                    print(f"[CRITIC] Failure analysis: {analysis}")
                    ctx.agent.critic_feedback_engine.process_feedback(analysis)
                except Exception as critic_err:
                    print(f"[BENCHMARK] critic analysis failed (non-fatal): {critic_err}")
                await self._auto_debug(ctx, result)

        except Exception as bench_err:
            print(f"[BENCHMARK] post-certify non-fatal error: {bench_err}")

    async def _cross_domain_benchmark(self, ctx: StudyContext) -> dict | None:
        """Fallback: find a concrete cross-domain angle for an abstract topic.

        When a topic is too abstract to produce a passing benchmark (e.g.
        'algorithm complexity', 'performance optimization'), SHARD:
          1. Queries ChromaDB for the 3 most similar certified topics.
          2. Asks the LLM to propose ONE concrete Python problem that
             demonstrates the abstract topic using those known concepts.
          3. Runs a FULL benchmark on that concrete problem — nothing skipped.

        Returns the benchmark result dict, or None on any failure.
        """
        topic = ctx.topic
        print(f"[XDOMAIN] Abstract topic '{topic}' — searching for concrete angle...")

        # 1. Find connected certified topics from ChromaDB
        connected: list[str] = []
        try:
            results = ctx.agent.kb.query(
                query_texts=[topic],
                n_results=5,
                where={"certified": True},
            )
            if results.get("metadatas") and results["metadatas"][0]:
                for meta in results["metadatas"][0]:
                    t = meta.get("topic", "")
                    if t and t != topic:
                        connected.append(t)
        except Exception as e:
            print(f"[XDOMAIN] ChromaDB query failed: {e}")

        if not connected:
            print(f"[XDOMAIN] No connected certified topics found — skipping cross-domain")
            return None

        connected_str = ", ".join(connected[:3])
        print(f"[XDOMAIN] Connected certified topics: {connected_str}")

        # 2. Ask LLM to propose ONE concrete Python problem (single concept, no mixing)
        propose_prompt = (
            f"The topic '{topic}' is too abstract for a concrete benchmark.\n"
            f"SHARD has certified one of these related topics: {connected_str}.\n\n"
            f"Pick ONE of those certified topics and name a specific Python implementation task.\n"
            f"Rules:\n"
            f"  - Single concept only — do NOT combine multiple topics\n"
            f"  - Must be implementable as: def solve(input_data) -> result\n"
            f"  - 3-6 words maximum\n"
            f"  - No 'and', no 'with', no conjunctions\n\n"
            f"Reply with ONLY the task name. Example: 'binary search on sorted list'"
        )
        try:
            concrete_topic = await ctx.agent._think_fast(propose_prompt)
            concrete_topic = concrete_topic.strip().strip('"').strip("'")[:60]
        except Exception as e:
            print(f"[XDOMAIN] LLM proposal failed: {e}")
            return None

        # Reject if it looks like a multi-topic mashup
        if not concrete_topic or len(concrete_topic) < 5:
            return None
        if any(w in concrete_topic.lower() for w in [" and ", " with ", " plus ", " & "]):
            print(f"[XDOMAIN] Rejected multi-topic proposal: '{concrete_topic}'")
            # Fall back to first connected topic directly
            concrete_topic = connected[0]
            print(f"[XDOMAIN] Using first certified topic as fallback: '{concrete_topic}'")

        print(f"[XDOMAIN] Concrete angle proposed: '{concrete_topic}'")

        # 3. Generate a FULL benchmark for the concrete topic
        try:
            benchmark_data = await ctx.agent.benchmark_generator.generate(
                topic=concrete_topic,
                synthesized_code="",  # fresh — don't bias generator with abstract code
                n_tests=3,
            )
            if not benchmark_data.get("available"):
                print(f"[XDOMAIN] Benchmark generator unavailable for '{concrete_topic}'")
                return None
        except Exception as e:
            print(f"[XDOMAIN] Benchmark generation failed: {e}")
            return None

        # 4. Regenerate implementation specifically for the concrete topic
        # (ctx.codice_generato was written for the abstract topic — it will fail)
        scaffold = benchmark_data.get("scaffold", "def solve(input_data):\n    pass")
        impl_prompt = (
            f"You understand '{ctx.topic}'. Demonstrate this by implementing:\n\n"
            f"{scaffold}\n\n"
            f"The function must solve: {concrete_topic}\n"
            f"Return ONLY the complete Python function. No explanation, no markdown."
        )
        try:
            import re as _re
            impl_code = await ctx.agent._think_fast(impl_prompt)
            impl_code = _re.sub(r"```(?:python)?|```", "", impl_code or "").strip()
            if not impl_code or "def solve(" not in impl_code:
                print(f"[XDOMAIN] Implementation generation failed — no solve() found")
                return None
            print(f"[XDOMAIN] Implementation generated ({len(impl_code)} chars)")
        except Exception as e:
            print(f"[XDOMAIN] Implementation generation failed: {e}")
            return None

        # 5. Run the benchmark — standard pipeline
        try:
            result = await ctx.agent.benchmark_runner.run_benchmark(
                benchmark=benchmark_data,
                implementation_code=impl_code,
                topic=concrete_topic,
            )
            passed = result.get("passed", 0)
            total  = result.get("total", 0)
            print(
                f"[XDOMAIN] Cross-domain benchmark '{concrete_topic}': "
                f"{passed}/{total} passed"
            )
            return result
        except Exception as e:
            print(f"[XDOMAIN] Benchmark run failed: {e}")
            return None

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

    async def _swarm_regen_code(self, ctx: StudyContext, regen_prompt: str) -> str | None:
        """Architect→Coder swarm for retry attempt >= 2.

        Architect analyzes why previous code failed and produces a strategy document.
        Coder implements the strategy. Cheaper than the full benchmark_loop swarm —
        no reviewer step, since we just need better code, not production-quality code.

        Returns new code string or None if the swarm fails.
        """
        try:
            from llm_router import llm_complete

            # ── Architect prompt ─────────────────────────────────────────────
            failed_code_snippet = (ctx.codice_generato or "")[:1200]
            gap_list = "\n".join(f"  - {g}" for g in (ctx.gaps or [])[:6]) or "  (no gap info)"
            critique_block = f"\n\nLLM critic's diagnosis:\n{ctx.critic_meta_critique}" if ctx.critic_meta_critique else ""

            architect_prompt = f"""You are a software architect analyzing a FAILED study-pipeline code generation.

Topic: {ctx.topic}
Study attempt: {ctx.attempt}

FAILED CODE (produced on last attempt):
```python
{failed_code_snippet}
```

IDENTIFIED GAPS (why the theory scored low):
{gap_list}{critique_block}

Produce a STRATEGY DOCUMENT (plain text, no code) answering:
1. Root cause: why does the code fail to demonstrate the topic correctly?
2. What is the single most important structural change needed?
3. Concrete implementation plan: what functions/data-structures/algorithms to use.
4. Anti-patterns to avoid (what keeps going wrong).

Output ONLY the strategy document. No code. No markdown. Plain text. Max 400 words."""

            strategy = await llm_complete(
                architect_prompt,
                system="You are a software architect. Output only a plain-text strategy document. No code.",
                providers=PROVIDERS_PRIMARY,
                max_tokens=600,
                temperature=0.3,
            )
            if not strategy or len(strategy.strip()) < 50:
                print("[SWARM] Architect produced empty strategy")
                return None
            print(f"[SWARM] Architect strategy ({len(strategy)} chars)")

            # ── Coder prompt ─────────────────────────────────────────────────
            coder_prompt = f"""You are a precise Python implementation agent.

An Architect analyzed a failed attempt and produced this strategy:
--- STRATEGY ---
{strategy}
--- END STRATEGY ---

Now implement this strategy as a minimal executable Python script for: {ctx.topic}

Rules:
- Valid Python, no markdown fences, no explanations, terminates automatically
- Only use: Python stdlib, numpy, math, random, itertools, collections, concurrent.futures
- NO external APIs, NO pip installs, NO servers or infinite loops
- MUST include assert statements testing actual behavior + print("OK All assertions passed")
- Follow the Architect's strategy EXACTLY — do not fall back to the previous approach"""

            code = await llm_complete(
                coder_prompt,
                system="You are a Python implementation agent. Output ONLY valid Python code. No markdown, no explanations.",
                providers=PROVIDERS_PRIMARY,
                max_tokens=2048,
                temperature=0.1,
            )

            if not code:
                return None

            # Strip markdown fences if model ignores the instruction
            if "```" in code:
                lines = code.split("\n")
                code = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()

            print(f"[SWARM] Coder produced {len(code)} chars")
            return code if code.strip() else None

        except Exception as swarm_err:
            print(f"[SWARM] Architect→Coder failed (non-fatal): {swarm_err}")
            return None

    async def _store_failure_memory(self, ctx: StudyContext) -> None:
        """#42 — Persist EPISODE_FAILURE memory for diagnostically useful failures."""
        try:
            from memory_extractor import MemoryExtractor
            # Prefer classified sandbox error; fall back to benchmark_failure for
            # cases where sandbox passed but benchmark gate blocked certification.
            # Fall back to "benchmark_failure" when error is unclassifiable (None,
            # "generic", "other", "unknown") — those normalise to "other" and would
            # block the save silently.
            _raw_et = str(ctx.classified_error_type) if ctx.classified_error_type else ""
            _unclassifiable = {"", "generic", "other", "unknown", "generic_error"}
            error_type = _raw_et if _raw_et not in _unclassifiable else "benchmark_failure"
            # Build error message: prefer sandbox stderr, else benchmark pass_rate summary
            stderr_raw = ""
            if ctx.sandbox_result:
                stderr_raw = ctx.sandbox_result.get("stderr", "") or ""
            if stderr_raw.strip():
                error_msg = stderr_raw.strip().splitlines()[-1][:200]
            elif ctx.eval_data:
                pass_rate = ctx.eval_data.get("pass_rate", 0)
                error_msg = f"Benchmark pass_rate={pass_rate:.0%} — solution logic incorrect."
            else:
                error_msg = error_type
            best = getattr(ctx, "best_score", ctx.score)
            saved = MemoryExtractor.save_failure_memory(
                topic=ctx.topic,
                error_type=error_type,
                error_msg=error_msg,
                score=best,
                attempt=ctx.attempt,
                container_tag=getattr(ctx, "container_tag", "shard"),
            )
            if saved:
                _logger.info("[MEMORY_FAIL] Stored EPISODE_FAILURE for '%s' (best_score=%.1f, error=%s)",
                             ctx.topic, best, error_type)
        except Exception as _mf_err:
            _logger.warning("[MEMORY_FAIL] Non-fatal store error: %s", _mf_err)

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
            critique_block = f"\n\nCRITICAL SELF-EVALUATION (read carefully -- this is what you keep getting wrong):\n{ctx.critic_meta_critique}\n"
            print(f"[CRITIC-LLM] Injecting meta-critique into retry prompt for '{ctx.topic}'")

        # Vettore 1+2 -- CognitionCore relational_context on every retry
        # Full tension-aware context: Identity vs Experience vs Knowledge
        # Skipped when ctx.no_l3 is True (#45 A/B gate)
        # Note: this method only runs during retry, so ctx.attempt is always >= 1.
        # The previous explicit guard was redundant and is removed for clarity.
        core_block = ""
        core = getattr(ctx.agent, "cognition_core", None)
        if core is not None and not ctx.no_l3:
            try:
                ctx.core_relational_ctx = core.relational_context(ctx.topic, research_mode=ctx.research_mode)
                core_block = f"\n\n[COGNITION CORE -- INTERNAL STATE]\n{ctx.core_relational_ctx}\n"
                print(f"[VETTORE 1+2] CognitionCore relational_context injected at attempt {ctx.attempt}")
            except Exception as _cre:
                print(f"[VETTORE 1+2] relational_context FAILED at attempt {ctx.attempt}: {_cre}")
                import traceback; traceback.print_exc()
        elif ctx.no_l3:
            print(f"[NO-L3] relational_context skipped at attempt {ctx.attempt} (#45 A/B baseline)")

        # Track previous strategy for audit_emergence
        prev_strategy = ctx.strategy_used

        # Near-miss alert: when score is close to the certification threshold (7.5),
        # inject a targeted block so the LLM knows it's close and what to improve.
        near_miss_block = ""
        _score_now = ctx.score or 0.0
        if 5.5 <= _score_now < 7.5:
            _gap_to_cert = round(7.5 - _score_now, 1)
            near_miss_block = (
                f"\n\nNEAR-MISS: current score {_score_now}/10 -- only {_gap_to_cert} points "
                f"from certification (threshold=7.5). Do NOT change the overall approach. "
                f"Refine and deepen: add precise code examples, cover edge cases explicitly, "
                f"and ensure the most complex concept is fully explained with working code.\n"
            )

        # 1. Re-synthesize theory with gap focus
        gap_prompt = f"""
Previous study of "{ctx.topic}" had these gaps: {gaps}
Focus area: {focus}{critique_block}{core_block}{near_miss_block}
Re-synthesize with emphasis on filling these specific gaps.
If the critical self-evaluation or the Cognition Core signals above identify a systematic mistake, CHANGE YOUR APPROACH -- do not repeat the same strategy.
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
Focus area: {focus}{critique_block}{core_block}
Fix those gaps explicitly in the new implementation.
If the critical self-evaluation or the Cognition Core signals above identify a systematic mistake, CHANGE YOUR IMPLEMENTATION APPROACH -- use a different pattern, different data structures, or different algorithm.

Rules:
- valid Python, no markdown, no explanations, terminates automatically
- only use: Python stdlib, numpy, math, random, itertools, collections, concurrent.futures
- NO external APIs, NO pip installs, NO servers or infinite loops
"""
        prev_sandbox_score = ctx.sandbox_result.get("score", 0.0) if ctx.sandbox_result else 0.0
        try:
            # On attempt >= 2: escalate to Architect→Coder swarm — simple retry has already failed
            if ctx.attempt >= 2 and ctx.codice_generato:
                print(f"[SWARM] Activating Architect→Coder pipeline (attempt {ctx.attempt})")
                swarm_code = await self._swarm_regen_code(ctx, regen_prompt)
                if swarm_code:
                    ctx.codice_generato = swarm_code
                else:
                    # Swarm failed — fall back to standard single-shot regen
                    print("[SWARM] Swarm produced no output — falling back to standard regen")
                    ctx.codice_generato = await ctx.agent._think_fast(regen_prompt)
            else:
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

                # Vettore 1 -- Shadow Diagnostic: audit emergence after retry
                if core is not None and ctx.core_relational_ctx:
                    try:
                        new_score = ctx.sandbox_result.get("score", 0.0) or 0.0
                        new_strategy = ctx.strategy_used or "retry"
                        delta = {
                            "strategy_used":           new_strategy,
                            "strategy_prev":           prev_strategy,
                            "sandbox_score":           new_score,
                            "sandbox_score_prev":      prev_sandbox_score,
                            "attempt_number":          ctx.attempt,
                            "tension_present":         bool(ctx.core_relational_ctx),
                            "prompt_tokens":           len(regen_prompt) // 4,
                            "v3_active":               bool(getattr(ctx, "v3_recommended_strategy", None)),
                            "v3_recommended_strategy": getattr(ctx, "v3_recommended_strategy", None),
                        }
                        audit = await core.audit_emergence(ctx.topic, "retry", delta)
                        print(f"[SHADOW DIAGNOSTIC] {audit} -- topic='{ctx.topic}' attempt={ctx.attempt}")
                        ctx.prev_strategy_used = new_strategy
                    except Exception:
                        pass  # non-fatal

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

        # Semantic memory: index this study session with rich content
        try:
            from semantic_memory import get_semantic_memory as _get_sem_ps
            _sem_ps = _get_sem_ps()
            if ctx.certified:
                # Build a rich knowledge entry: strategy + code snippet + key concepts
                _content_parts = [
                    f"Topic certified with score {ctx.score:.1f}/10.",
                    f"Strategy used: {ctx.strategy_used or 'default'}.",
                ]
                if ctx.connections:
                    _content_parts.append(f"Key connections: {', '.join(ctx.connections[:5])}.")
                if ctx.codice_generato:
                    _content_parts.append(
                        f"Working code snippet:\n```python\n{ctx.codice_generato[:600]}\n```"
                    )
                _sem_ps.add_knowledge(
                    title=ctx.topic,
                    content="\n".join(_content_parts),
                    source="study_certified",
                )
                print(f"[SEMANTIC] Indexed certified knowledge: '{ctx.topic}'")
            elif ctx.score > 0 and ctx.classified_error_type:
                # Failed but has a classifiable error -- save as error pattern
                _sem_ps.add_error_pattern(
                    error_text=f"{ctx.topic}: {ctx.classified_error_type}",
                    fix=f"Strategy attempted: {ctx.strategy_used or 'none'}. Score: {ctx.score:.1f}/10.",
                    lang="python",
                )
        except Exception:
            pass
