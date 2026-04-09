import os
import asyncio
import re
import json
import random
import subprocess
import uuid
import pathlib
from typing import List, Dict, Any, Optional, Callable
from importlib.util import spec_from_file_location, module_from_spec
from datetime import datetime
# LLM calls go through llm_router -- no direct groq/anthropic clients needed here
from chromadb.utils import embedding_functions
from db_manager import get_collection, DB_PATH_KNOWLEDGE_DB
from filesystem_tools import write_file
from strategy_memory import StrategyMemory
from capability_graph import CapabilityGraph
from goal_engine import GoalEngine
from skill_discovery import SkillDiscovery
from experiment_replay import ExperimentReplay
from research_agenda import ResearchAgenda
from experiment_inventor import ExperimentInventor
from experiment_cache import SemanticExperimentCache
from strategy_extractor import StrategyExtractor
from strategy_tracker import StrategyTracker
from meta_learning import MetaLearning
from critic_feedback_engine import CriticFeedbackEngine
from benchmark_generator import BenchmarkGenerator
from benchmark_runner import BenchmarkRunner
from cert_contradiction_checker import CertContradictionChecker
from memory_extractor import MemoryExtractor
from derivation_engine import DerivationEngine
from skill_utils import normalize_capability_name
from swe_agent import SWEAgent
from cognition.simulation_engine import SimulationEngine
from cognition.self_model import SelfModel
from dotenv import load_dotenv
from study_utils import (
    find_file, safe_json_load, STOPWORDS, TECH_REFERENCE, GENERIC_CONCEPTS,
    semantic_concept_score, valid_concept, PHASES, ProgressTracker,
    _extract_json_block, _filter_concepts,
)
from sandbox_runner import DockerSandboxRunner
from browser_scraper import StudyBrowserScraper
try:
    from llm_router import llm_complete
except ImportError:
    from backend.llm_router import llm_complete


class TopicBudgetExceeded(Exception):
    """Raised when a single topic burns more LLM calls than the per-topic budget."""
    pass


# Default per-topic LLM call limit. Overridable via StudyAgent._topic_llm_budget.
DEFAULT_TOPIC_LLM_BUDGET = 200


def _load_reliability_module(relative_path: str, module_name: str):
    """Load reliability extension modules from repo-level shard/ without refactoring imports."""
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    target = repo_root / relative_path
    spec = spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {target}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_episodic_memory_mod = _load_reliability_module(
    "shard/memory/episodic_memory.py",
    "shard_memory_episodic_memory",
)
store_episode = _episodic_memory_mod.store_episode

_error_classifier_mod = _load_reliability_module(
    "shard/debug/error_classifier.py",
    "shard_debug_error_classifier",
)
FailureType = _error_classifier_mod.FailureType
classify_error = _error_classifier_mod.classify_error

_heuristic_repairs_mod = _load_reliability_module(
    "shard/debug/heuristic_repairs.py",
    "shard_debug_heuristic_repairs",
)
attempt_heuristic_fix = _heuristic_repairs_mod.attempt_heuristic_fix

# ── CONFIG ────────────────────────────────────────────────────────────────────
load_dotenv()
import sys
sys.stdout.reconfigure(encoding='utf-8')

CHROMA_DB_PATH   = DB_PATH_KNOWLEDGE_DB  # Ora da db_manager (path assoluto, CWD-indipendente)
SANDBOX_DIR      = os.path.join(os.getcwd(), "sandbox")
WORKSPACE_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shard_workspace")
from constants import (
    SUCCESS_SCORE_THRESHOLD,
    BENCHMARK_ENABLED,
    BENCHMARK_PASS_THRESHOLD,
    BENCHMARK_WEIGHT,
    PROVIDERS_PRIMARY,
    PROVIDERS_FULL,
)
MAX_RETRY        = 3

os.makedirs(SANDBOX_DIR, exist_ok=True)


class StudyAgent:
    def __init__(self, goal_engine: GoalEngine = None):
        # LLM calls go through llm_router (Gemini -> Groq -> Claude fallback chain)
        # No direct client initialization needed here
        self.emb_fn      = embedding_functions.DefaultEmbeddingFunction()
        self.embed       = self.emb_fn  # Semantic validation use
        # Usa il singleton db_manager -- terzo client ChromaDB unificato
        self.kb          = get_collection(
            CHROMA_DB_PATH,
            name="shard_knowledge_base",
            embedding_function=self.emb_fn
        )
        self.is_running  = False
        self.browser     = None
        self.playwright  = None
        self.bctx        = None
        self.progress    = ProgressTracker()

        # ── Per-topic LLM budget (SSJ12) ──────────────────────────────────────
        self._topic_llm_calls  = 0
        self._topic_llm_budget = DEFAULT_TOPIC_LLM_BUDGET

        # ── Session-level context injected by NightRunner ─────────────────────
        # Populated from SessionReflection.get_context_block() before study loop.
        # Appended to every _think / _think_fast system prompt as background context.
        self.session_context: str = ""

        # ── Extracted sub-components (SSJ3 Phase 1) ──
        self.sandbox_runner = DockerSandboxRunner(
            sandbox_dir=SANDBOX_DIR,
            analysis_fn=self._think,
        )
        self.browser_scraper = StudyBrowserScraper()


        
        # Callback for sending browser screenshots to frontend
        self.on_web_data = None
        
        # ── Strategy Memory & Capability Graph ──
        self.capability_graph = CapabilityGraph()
        # if a goal engine exists, register its callback listener for capability events
        if goal_engine:
            self.capability_graph.register_capability_listener(
                goal_engine.on_capability_added
            )

        # create or adopt a GoalEngine for use by other components
        if goal_engine is None:
            self.goal_engine = None
        else:
            self.goal_engine = goal_engine
            # ensure the engine knows about our graph in case it was created
            # earlier without one
            if not self.goal_engine.capability_graph:
                self.goal_engine.capability_graph = self.capability_graph
            # ensure listener registered as well (in case engine created earlier)
            self.capability_graph.register_capability_listener(
                self.goal_engine.on_capability_added
            )

        self.strategy_memory = StrategyMemory()
        self.skill_discovery = SkillDiscovery(self.capability_graph)
        self.replay_engine = ExperimentReplay()
        self.experiment_inventor = ExperimentInventor(self.capability_graph)
        self.experiment_cache = SemanticExperimentCache()
        self.tracker = StrategyTracker()
        self.meta_learning = MetaLearning(self.strategy_memory)
        from cognition.world_model import world_model
        self.world_model = world_model
        self.sim_engine = SimulationEngine(self.world_model)
        self.research_agenda = ResearchAgenda(
            capability_graph=self.capability_graph,
            replay_engine=self.replay_engine,
            goal_engine=self.goal_engine,
        )
        self.self_model = SelfModel(
            self.capability_graph,
            self.strategy_memory,
            self.research_agenda,
            self.world_model
        )

        # ── CognitionCore (Senso Interno) -- 5-layer Global Workspace ─────────────
        try:
            from cognition.cognition_core import get_cognition_core
            from episodic_memory import EpisodicMemory
            self.cognition_core = get_cognition_core(
                self_model=self.self_model,
                episodic_memory=EpisodicMemory(),
                strategy_memory=self.strategy_memory,
                meta_learning=self.meta_learning,
            )
            print("[COGNITION CORE] Senso Interno initialized")
        except Exception as _cc_err:
            print(f"[COGNITION CORE] Init failed (non-fatal): {_cc_err}")
            self.cognition_core = None

        # ── CriticAgent for failure analysis ──
        from critic_agent import CriticAgent
        self.critic_agent = CriticAgent(self.capability_graph, self.strategy_memory)
        self.critic_feedback_engine = CriticFeedbackEngine(self.research_agenda, self.capability_graph)
        
        try:
            self.swe_agent = SWEAgent()
        except Exception as e:
            print(f"[SWE] Initialization failed: {e}")
            self.swe_agent = None
        
        # ── Benchmark system ──────────────────────────────────────────────────
        # think_fn and sandbox_runner are wired here so the real implementations
        # can call the LLM and Docker sandbox without circular dependencies.
        self.benchmark_generator       = BenchmarkGenerator(think_fn=self._think_fast)
        self.benchmark_runner          = BenchmarkRunner(sandbox_runner=self.sandbox_runner)
        self.cert_contradiction_checker = CertContradictionChecker(
            think_fn=self._think_fast,
            kb=self.kb,
        )
        self.memory_extractor   = MemoryExtractor(think_fn=self._think_fast)
        self.derivation_engine  = DerivationEngine(think_fn=self._think_fast)

    # ── LLM REASONING ENGINES ────────────────────────────────────────────────

    @staticmethod
    def _clean_json(raw: str) -> str:
        """Strip Markdown fences, backticks, and junk around JSON from LLM output."""
        if not raw:
            return raw
        text = raw.strip()
        # Remove ```json ... ``` or ``` ... ``` wrappers
        if text.startswith("```"):
            # Strip opening fence (```json or ```)
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            else:
                text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        # If there's still junk before the first '{' or '[', strip it
        for start_char in ('{', '['):
            idx = text.find(start_char)
            if idx != -1:
                # Find the matching closing bracket from the end
                end_char = '}' if start_char == '{' else ']'
                end_idx = text.rfind(end_char)
                if end_idx > idx:
                    text = text[idx:end_idx + 1]
                    break
        return text

    def _safe_parse_json(self, raw_text: str) -> Dict:
        """Robust JSON parsing with recovery.

        Prevents SYNTHESIZE crashes from malformed model output.
        """
        # Step 1: extract JSON block, then clean, then parse
        clean = _extract_json_block(raw_text)
        cleaned = self._clean_json(clean)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print("[SYNTHESIZE] JSON invalid -- attempting recovery")

        # Step 2: attempt brute force extraction of { ... }
        start = raw_text.find("{")
        end = raw_text.rfind("}")

        if start != -1 and end != -1:
            try:
                recovered = raw_text[start:end+1]
                return json.loads(recovered)
            except Exception:
                pass

        print("[SYNTHESIZE] Recovery failed -- returning empty structure")
        return {"concepts": [], "summary": "", "insights": []}

    async def retrieve_strategy(self, topic: str):
        """
        Retrieve the most relevant past strategy for the given topic.
        """
        if not self.strategy_memory:
            return None

        try:
            results = self.strategy_memory.collection.query(
                query_texts=[topic],
                n_results=1
            )

            if results and results.get("documents"):
                docs = results["documents"][0]
                if docs:
                    strategy = docs[0]
                    
                    # Filtra: strategy_len > 20 and context matching
                    if strategy and len(strategy) > 20:
                        if topic.lower() in strategy.lower():
                            print("[STRATEGY RETRIEVAL] Found prior strategy")
                            return strategy
                        else:
                            print("[STRATEGY RETRIEVAL] Strategy found but out-of-context; discarding.")

        except Exception as e:
            print(f"[STRATEGY RETRIEVAL] Retrieval failed: {e}")

        return None

    async def _think(self, prompt: str, system: str = "You are SHARD, an autonomous reasoning AI.", json_mode: bool = False) -> str:
        """Core reasoning call using the global llm_router.
        Prefers Gemini (free) -> Groq -> Claude.
        """
        self._topic_llm_calls += 1
        if self._topic_llm_calls > self._topic_llm_budget:
            raise TopicBudgetExceeded(
                f"Topic burned {self._topic_llm_calls} LLM calls (budget={self._topic_llm_budget})"
            )
        effective_system = system
        if self.session_context:
            effective_system += f"\n\n{self.session_context[:600]}"
        if json_mode:
            effective_system += "\nOUTPUT ONLY VALID JSON. Do not include markdown formatting, backticks, code fences, or any conversational text."

        return await llm_complete(
            prompt=prompt,
            system=effective_system,
            max_tokens=2000,
            temperature=0.3,
            providers=PROVIDERS_FULL
        )

    async def _think_fast(self, prompt: str, system: str = "You are SHARD, an autonomous reasoning AI.", json_mode: bool = False) -> str:
        """Fast reasoning call using the global llm_router.
        Prefers Gemini (free) -> Groq -> Claude.
        """
        self._topic_llm_calls += 1
        if self._topic_llm_calls > self._topic_llm_budget:
            raise TopicBudgetExceeded(
                f"Topic burned {self._topic_llm_calls} LLM calls (budget={self._topic_llm_budget})"
            )
        effective_system = system
        if self.session_context:
            effective_system += f"\n\n{self.session_context[:600]}"
        if json_mode:
            effective_system += "\nOUTPUT ONLY VALID JSON. Do not include markdown formatting, backticks, code fences, or any conversational text."

        return await llm_complete(
            prompt=prompt,
            system=effective_system,
            max_tokens=2000,
            temperature=0.3,
            providers=PROVIDERS_FULL
        )

    # ── PHASE 1: MAP ──────────────────────────────────────────────────────────

    async def phase_map(self, topic: str, tier: int) -> List[Dict]:
        """Search sources with multiple targeted queries for better relevance."""
        print(f"[MAP] Searching sources for: {topic} (Tier {tier})")
        self.progress.set_phase("MAP", 0.0)
        sources = []

        # Generate smart search queries using Groq (fast task)
        query_prompt = f"""Generate 3-4 specific search queries to deeply research "{topic}".
Each query should target different aspects: tutorials, official docs, advanced patterns, real-world examples.
Respond ONLY with a JSON array of strings, nothing else.
Example: ["query 1", "query 2", "query 3"]"""

        try:
            raw = await self._think_fast(query_prompt, json_mode=True)
            queries = json.loads(raw)
            if isinstance(queries, dict):
                queries = list(queries.values())[0] if queries else [topic]
            if not isinstance(queries, list):
                queries = [topic]
        except:
            queries = [topic]

        # Always include the original topic
        if topic not in queries:
            queries.insert(0, topic)

        print(f"[MAP] Smart queries: {queries}")

        # Blocked domains that return garbage or off-topic results
        blocked = [
            "zhihu.com", "quora.com", "pinterest.com", "facebook.com",
            "instagram.com", "tiktok.com", "reddit.com/user/",
            "youtube.com", "kela.fi",
            # Off-topic domains (SNMP traps, non-programming content)
            "microfocus.com", "cuddletech.com", "helpndoc.com",
            "github.com/rcore-os",
        ]

        # Authoritative domains get a relevance boost
        priority_domains = [
            "developer.mozilla.org", "docs.python.org", "dev.to",
            "stackoverflow.com", "w3.org", "realpython.com",
            "wikipedia.org", "github.com", "readthedocs.io",
        ]

        def _search():
            from ddgs import DDGS  # lazy: only needed during MAP web search
            results = []
            with DDGS(timeout=15) as ddgs:
                for query in queries[:4]:
                    try:
                        for r in ddgs.text(query, max_results=5):
                            url = r.get("href", "")
                            # Skip relative URLs (invalid)
                            if not url.startswith("http"):
                                continue
                            # Filter out blocked domains
                            if any(b in url.lower() for b in blocked):
                                continue
                            results.append({
                                "url": url,
                                "title": r.get("title", ""),
                                "query": query,
                                "tier": 1
                            })
                    except Exception as e:
                        print(f"[MAP] Query failed: {query} -- {e}")

                if tier >= 2:
                    wiki_queries = [
                        f"site:wikipedia.org {topic}",
                        f"site:docs.python.org {topic}" if "python" in topic.lower() else f"official documentation {topic}",
                        f"site:realpython.com {topic}" if "python" in topic.lower() else f"tutorial {topic}",
                        f"site:dev.to {topic}",
                        f"site:medium.com {topic}",
                    ]
                    for q in wiki_queries:
                        try:
                            for r in ddgs.text(q, max_results=2):
                                url = r.get("href", "")
                                if any(b in url.lower() for b in blocked):
                                    continue
                                results.append({
                                    "url": url,
                                    "title": r.get("title", ""),
                                    "query": q,
                                    "tier": 2
                                })
                        except:
                            pass
            return results

        sources = await asyncio.to_thread(_search)

        # Deduplicate by URL
        seen = set()
        unique = []
        for s in sources:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique.append(s)
        sources = unique

        # Score and sort by relevance (topic overlap + tier + priority domain boost)
        topic_words = set(topic.lower().split())
        for s in sources:
            title_words = set(s["title"].lower().split())
            domain_boost = 2 if any(d in s["url"] for d in priority_domains) else 0
            s["relevance"] = len(topic_words & title_words) + (1 if s["tier"] == 2 else 0) + domain_boost
        sources.sort(key=lambda x: x["relevance"], reverse=True)

        # Cap at 15 to avoid LLM context bloat
        sources = sources[:15]

        print(f"[MAP] Found {len(sources)} unique sources (sorted by relevance)")
        for s in sources[:8]:
            print(f"  [{s['relevance']}] {s['title'][:60]} -- {s['url'][:50]}")

        self.progress.complete_phase("MAP")
        return sources

    # ── PHASE 2: AGGREGATE ────────────────────────────────────────────────────

    async def phase_aggregate(self, sources: List[Dict]) -> str:
        """Scrape and clean text from web pages with visible Playwright.

        Delegates to StudyBrowserScraper -- browser is always closed via finally.
        """
        max_sources = min(len(sources), 6)
        self.progress.set_phase("AGGREGATE", 0.0)
        all_text = await self.browser_scraper.scrape_sources(
            sources,
            max_sources=max_sources,
            progress=self.progress,
            on_web_data_fn=self.on_web_data,
        )
        self.progress.complete_phase("AGGREGATE")
        return all_text

    # ── MEMORY CONTEXT HELPER ─────────────────────────────────────────────────

    @staticmethod
    def _memory_context_block(
        topic: str,
        memory_types: Optional[List[str]] = None,
        label: str = "SHARD MEMORY",
        limit: int = 6,
    ) -> str:
        """Return a formatted block of relevant memories for prompt injection.

        Returns empty string if no memories found or on any error.
        """
        try:
            from memory_extractor import MemoryExtractor
            mems = MemoryExtractor.search_for_prompt(
                topic, memory_types=memory_types, limit=limit
            )
            if not mems:
                return ""
            lines = [f"[{label}]"]
            for m in mems:
                mtype = m.get("memory_type", "FACT")
                conf  = m.get("confidence", 1.0)
                content = m.get("content", "")
                lines.append(f"  [{mtype}] ({conf:.2f}) {content}")
            lines.append("")
            return "\n".join(lines) + "\n"
        except Exception:
            return ""

    # ── PHASE 3: SYNTHESIZE ───────────────────────────────────────────────────

    async def phase_synthesize(self, topic: str, raw: str, strategy_hint: str = None,
                               previous_score: float = None,
                               episode_context: str = None,
                               pivot_directive: str = None) -> Dict:
        """SHARD processes, connects and reasons on raw content (Metodo Feynman)."""
        print(f"[SYNTHESIZE] Building structured knowledge (Metodo Feynman) for: {topic}")
        self.progress.set_phase("SYNTHESIZE", 0.0)

        meta_line = (
            f"\nMeta-learning hint (historically best approach for this category): {strategy_hint}\n"
            if strategy_hint else ""
        )
        score_line = (
            f"\nPrevious attempt score: {previous_score}/10. Focus on depth and correctness "
            f"-- the previous synthesis was incomplete. Be more precise and cover more concepts.\n"
            if previous_score is not None else ""
        )
        episodic_line = (
            f"\n{episode_context}\n"
            if episode_context else ""
        )
        # Vettore 1 -- CognitionCore Structural Pivot Directive
        pivot_line = (
            f"\n[COGNITION CORE -- STRUCTURAL PIVOT]\n{pivot_directive}\n"
            if pivot_directive else ""
        )

        # GraphRAG: inject causal relations already known about this topic
        causal_line = ""
        try:
            from graph_rag import query_causal_context
            causal = query_causal_context(topic)
            if causal:
                causal_line = f"\n{causal}\nUse these known relations to enrich your extraction -- confirm, contradict, or extend them.\n"
                print(f"[SYNTHESIZE] GraphRAG injected {causal.count(chr(10)) + 1} causal warnings")
        except Exception:
            pass

        # MEMORY: inject prior FACT/RELATION memories about this topic
        memory_line = ""
        _mem_block = self._memory_context_block(
            topic, memory_types=["FACT", "RELATION"],
            label="PRIOR KNOWLEDGE FROM SHARD MEMORY", limit=6,
        )
        if _mem_block:
            memory_line = f"\n{_mem_block}Build on this prior knowledge — go deeper, correct, or extend it.\n"
            print(f"[SYNTHESIZE] Memory injected {_mem_block.count(chr(10))} prior memories")

        prompt = f"""
You must extract structured concepts from the text and form a personal opinion.{meta_line}{score_line}{episodic_line}{pivot_line}{causal_line}{memory_line}
Return ONLY valid JSON.

Do not include explanations.
Do not include markdown.
Do not include text before or after the JSON.

Required format:

{{
"shard_opinion": "1-2 sentence evaluation: why this topic matters, what makes it hard, or where people typically go wrong -- not a summary",
"concepts": [
{{
"name": "concept_name",
"dependencies": [],
"applications": []
}}
]
}}

Rules:

• shard_opinion must be an evaluative judgment, not a description
• name must be a technical concept
• dependencies must list prerequisite concepts
• applications must list real-world uses
• if nothing is found return:

{{
"shard_opinion": "",
"concepts": []
}}

RAW CONTENT:
{raw[:16000]}
"""
        self.progress.set_phase("SYNTHESIZE", 0.5)
        prompt = "You MUST respond with valid JSON only.\n\n" + prompt
        raw_json = await self._think(prompt, json_mode=True)

        data = safe_json_load(raw_json)

        if data:
            print("[SYNTHESIZE] JSON recovered successfully")
        else:
            print("[SYNTHESIZE] JSON recovery failed")

        if not isinstance(data, dict):
            data = {"concepts": []}

        if "concepts" not in data:
            data["concepts"] = []

        if not data.get("concepts"):
            print("[SYNTHESIZE] LLM returned empty concepts list")

        result = data

        if result.get("concepts"):
            print(f"[SYNTHESIZE] JSON parsed successfully ({len(result['concepts'])} concepts)")
        else:
            print(f"[SYNTHESIZE] Warning: no concepts extracted")
            # Fallback: extract top-frequency words from raw text as minimal concepts
            _STOPWORDS = {
                "function", "result", "value", "system", "data", "object", "class",
                "cookie", "cookies", "privacy", "accept", "banner", "login", "advertisement",
            }
            words = re.findall(r'\b[A-Za-z][a-z]{4,}\b', raw)
            freq: Dict[str, int] = {}
            for w in words:
                lw = w.lower()
                if lw not in _STOPWORDS:
                    freq[lw] = freq.get(lw, 0) + 1
            top_kw = sorted(freq, key=lambda k: freq[k], reverse=True)[:5]
            if top_kw:
                result["concepts"] = [{"name": kw, "explanation": "", "importance": 5} for kw in top_kw]
                print(f"[SYNTHESIZE] Fallback: {len(result['concepts'])} keywords promoted to concepts: {top_kw}")

        # Filter low-quality / noisy concepts before returning
        if result.get("concepts"):
            # Use semantic validator with embeddings
            concepts = [
                c for c in result.get("concepts", [])
                if valid_concept(c.get("name", ""), embed_fn=self.embed)
            ]
            result["concepts"] = concepts

            # World Model ingestion (non-fatal, does not alter pipeline outputs)
            try:
                from cognition.world_model import world_model

                world_model.reset()
                world_model.ingest_concepts(concepts)
                print(
                    f"[WORLD MODEL] entities: {world_model.graph.number_of_nodes()} "
                    f"edges: {world_model.graph.number_of_edges()}"
                )

                hubs = world_model.compute_hubs()
                if hubs:
                    top = hubs[:5]

                    for name, degree in top:
                        print(f"[WORLD MODEL] hub detected: {name} (degree {degree})")
            except Exception as e:
                print(f"[WORLD MODEL] ingestion skipped: {e}")

            print(f"[SYNTHESIZE] concepts extracted: {len(concepts)} after semantic validation")

            # GraphRAG: extract causal relations (non-fatal, async fire-and-forget)
            try:
                import asyncio
                from graph_rag import extract_and_store_relations
                asyncio.ensure_future(
                    extract_and_store_relations(topic, concepts, raw)
                )
            except Exception as e:
                print(f"[GRAPH_RAG] skipped: {e}")

        self.progress.complete_phase("SYNTHESIZE")
        return result

    # ── PHASE 4: STORE ────────────────────────────────────────────────────────

    async def phase_store(self, topic: str, data: Dict):
        """Save knowledge to ChromaDB for future use and cross-referencing."""
        print(f"[STORE] Persisting knowledge for: {topic}")
        self.progress.set_phase("STORE", 0.0)
        
        try:
            doc_text = f"Topic: {topic}\n"
            doc_text += f"Opinion: {data.get('shard_opinion', '')}\n"
            doc_text += "Concepts: " + ", ".join([c["name"] for c in data.get("concepts", [])])

            self.kb.upsert(
                ids=[f"{topic}_{datetime.now().strftime('%Y%m%d%H%M%S')}"],
                documents=[doc_text],
                metadatas=[{"topic": topic, "timestamp": datetime.now().isoformat()}]
            )
            print(f"[STORE] ✅ Saved to ChromaDB")
        except Exception as e:
            print(f"[STORE] ❌ ChromaDB error: {e}")
        
        self.progress.complete_phase("STORE")

    # ── PHASE 4b: CROSS-POLLINATE (Integration Report) ────────────────────────

    async def phase_cross_pollinate(self, topic: str, raw_text: str, structured: Dict) -> str:
        """Query existing knowledge and generate an Integration Report linking old and new."""
        print(f"[CROSS-POLLINATE] Generating Integration Report for: {topic}")
        self.progress.set_phase("CROSS_POLLINATE", 0.0)

        # 1. Retrieve top-3 similar docs from ChromaDB (excluding current topic)
        old_knowledge = ""
        try:
            query = topic + " " + " ".join([c["name"] for c in structured.get("concepts", [])[:5]])
            results = self.kb.query(
                query_texts=[query],
                n_results=3,
                where={"topic": {"$ne": topic}}
            )
            if results["documents"] and results["documents"][0]:
                for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
                    old_topic = meta.get("topic", "Unknown")
                    old_knowledge += f"\n--- [{old_topic}] ---\n{doc}\n"
                print(f"[CROSS-POLLINATE] Found {len(results['documents'][0])} related documents in memory")
            else:
                print("[CROSS-POLLINATE] No existing knowledge found -- this is SHARD's first topic")
        except Exception as e:
            print(f"[CROSS-POLLINATE] ChromaDB query error: {e}")

        self.progress.set_phase("CROSS_POLLINATE", 0.3)

        # 2. LLM call to generate Integration Report
        if old_knowledge:
            system_prompt = (
                f"Sei il nucleo logico di SHARD. Hai appena studiato '{topic}' e hai questi raw data. "
                f"Dalla tua memoria a lungo termine sai già queste cose: {old_knowledge} "
                f"Scrivi un 'Rapporto di Integrazione' di max 150 parole in cui spieghi i collegamenti "
                f"logici tra la vecchia e la nuova conoscenza, evidenziando cosa hai imparato di nuovo."
            )
        else:
            system_prompt = (
                f"Sei il nucleo logico di SHARD. Hai appena studiato '{topic}' per la prima volta. "
                f"Non hai conoscenze pregresse. Scrivi un breve 'Rapporto di Integrazione' di max 150 parole "
                f"che sintetizzi i concetti chiave appresi e come li colleghi tra loro."
            )

        concepts_summary = json.dumps(structured.get("concepts", []), indent=2)[:3000]
        user_prompt = f"""Nuovi concetti appresi su '{topic}':
{concepts_summary}

Opinione SHARD: {structured.get('shard_opinion', 'N/A')}

Genera il Rapporto di Integrazione (max 150 parole)."""

        self.progress.set_phase("CROSS_POLLINATE", 0.5)
        report = await self._think(user_prompt, system=system_prompt)
        print(f"[CROSS-POLLINATE] ✅ Integration Report generated ({len(report)} chars)")
        print(f"[CROSS-POLLINATE] Report preview: {report[:200]}...")

        self.progress.set_phase("CROSS_POLLINATE", 0.8)

        # 3. Save Integration Report to ChromaDB as deep_knowledge
        try:
            report_id = f"integration_{topic}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            self.kb.upsert(
                ids=[report_id],
                documents=[f"Integration Report -- {topic}:\n{report}"],
                metadatas=[{
                    "topic": topic,
                    "type": "deep_knowledge",
                    "timestamp": datetime.now().isoformat(),
                    "source": "cross_pollination"
                }]
            )
            print(f"[CROSS-POLLINATE] ✅ Report saved to ChromaDB (type: deep_knowledge)")
        except Exception as e:
            print(f"[CROSS-POLLINATE] ❌ ChromaDB save error: {e}")

        self.progress.complete_phase("CROSS_POLLINATE")
        return report

    # ── PHASE 4c: MATERIALIZE (Cheat Sheet to File System) ────────────────────

    async def phase_materialize(self, topic: str, structured: Dict, strategy_hint: str = None,
                                previous_score: float = None,
                                episode_context: str = None) -> bool:
        """Generate a structured Cheat Sheet and write it to the filesystem."""
        print(f"[MATERIALIZE] Creating Cheat Sheet for: {topic}")
        self.progress.set_phase("MATERIALIZE", 0.0)

        # 1. Build LLM prompt for Cheat Sheet generation
        concepts_summary = json.dumps(structured.get("concepts", []), indent=2)[:3000]
        code_snippet = structured.get("code_snippet", "")

        meta_line = (
            f"\nMeta-learning hint -- apply this approach in the Practical Example: {strategy_hint}\n"
            if strategy_hint else ""
        )
        score_line = (
            f"\nPrevious attempt scored {previous_score}/10. The Practical Example was weak -- "
            f"make the code snippet complete, runnable, and well-commented this time.\n"
            if previous_score is not None else ""
        )
        episodic_line = (
            f"\n{episode_context}\n"
            if episode_context else ""
        )

        prompt = f"""You are SHARD. Generate a structured Cheat Sheet in Markdown for the topic "{topic}".{meta_line}{score_line}{episodic_line}

Based on these synthesized concepts:
{concepts_summary}

SHARD's opinion: {structured.get('shard_opinion', 'N/A')}

The Cheat Sheet MUST follow this exact structure:

# {topic} -- SHARD Cheat Sheet

## Key Concepts
(bullet list of the most important concepts with one-line explanations)

## Pro & Contro
| Pro | Contro |
|-----|--------|
| ... | ...    |

## Practical Example
(a concise, runnable code snippet or real-world example)

## SHARD's Take
(your reasoned opinion in 2-3 sentences)

---
*Generated by SHARD Autonomous Learning Engine*

IMPORTANT: Output ONLY the Markdown content, no extra commentary."""

        self.progress.set_phase("MATERIALIZE", 0.3)
        cheat_sheet = await self._think(prompt)
        print(f"[MATERIALIZE] ✅ Cheat Sheet generated ({len(cheat_sheet)} chars)")

        self.progress.set_phase("MATERIALIZE", 0.6)

        # 2. Format topic name for filename
        safe_name = re.sub(r'[^\w\-]', '_', topic.lower()).strip('_')[:80]
        file_path = f"knowledge_base/{safe_name}.md"

        # 3. Write to filesystem via sandboxed write_file
        result = write_file(file_path, cheat_sheet, WORKSPACE_DIR)
        if "success" in result.lower():
            print(f"[MATERIALIZE] ✅ Cheat Sheet written to: shard_workspace/{file_path}")
            print(f"[MATERIALIZE] Result: {result}")
            self.progress.complete_phase("MATERIALIZE")
            return True
        else:
            print(f"[MATERIALIZE] ❌ File write failed: {result}")
            self.progress.complete_phase("MATERIALIZE")
            return False

    # ── PHASE 5: VALIDATE ─────────────────────────────────────────────────────

    async def phase_validate(self, topic: str, data: Dict, sandbox_result: Dict = None) -> Dict:
        """SHARD self-interrogation: generates 2 complex Q&A pairs + integrates sandbox results."""
        print(f"[VALIDATE] Self-interrogation on: {topic}")
        self.progress.set_phase("VALIDATE", 0.0)

        # Build context from sandbox execution
        sandbox_context = ""
        if sandbox_result:
            sandbox_context = f"""

RISULTATI ESECUZIONE CODICE:
Successo: {sandbox_result.get('success', False)}
Output: {sandbox_result.get('stdout', '(nessuno)')[:500]}
Errori: {sandbox_result.get('stderr', '(nessuno)')[:500]}
"""

        teoria = data.get("teoria", data.get("shard_opinion", ""))

        # GraphRAG: inject causal warnings so Q&A probes known pitfalls
        causal_block = ""
        try:
            from graph_rag import query_causal_context
            causal = query_causal_context(topic)
            if causal:
                causal_block = f"\n{causal}\nIncorpora queste relazioni causali nelle domande dove pertinente.\n"
                print(f"[VALIDATE] GraphRAG injected {causal.count(chr(10)) + 1} causal warnings")
        except Exception:
            pass

        # MEMORY: inject past certification/failure episodes to guide Q&A depth
        memory_validate_block = self._memory_context_block(
            topic, memory_types=["EPISODE", "FACT"],
            label="STORICO SHARD SU QUESTO TOPIC", limit=4,
        )
        if memory_validate_block:
            print(f"[VALIDATE] Memory injected episode history")

        prompt = f"""
Sei SHARD. Hai appena studiato "{topic}".

TEORIA APPRESA:
{teoria[:2000]}
{sandbox_context}{causal_block}{memory_validate_block}
GENERA ESATTAMENTE 2 DOMANDE COMPLESSE sull'argomento e rispondi a ciascuna.
Le domande devono testare comprensione PROFONDA, non semplice recall.
Le risposte devono essere dettagliate, pratiche, con esempi concreti.

Respond ONLY with valid JSON:
{{
"validation_qa": [
    {{
        "domanda": "Domanda complessa 1...",
        "risposta": "Risposta dettagliata con esempi pratici..."
    }},
    {{
        "domanda": "Domanda complessa 2...",
        "risposta": "Risposta dettagliata con esempi pratici..."
    }}
]
}}
"""
        self.progress.set_phase("VALIDATE", 0.5)
        raw = await self._think(prompt, json_mode=True)

        try:
            cleaned = self._clean_json(raw)
            result = json.loads(cleaned)
            validation_qa = result.get("validation_qa", [])
        except Exception as e:
            print(f"[VALIDATE] JSON parse error: {e}")
            # Recovery: JSON troncato a max_tokens -- estrai coppie complete via regex
            validation_qa = []
            try:
                import re
                pattern = r'"domanda"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"risposta"\s*:\s*"((?:[^"\\]|\\.)*)"'
                matches = re.findall(pattern, raw, re.DOTALL)
                for domanda, risposta in matches:
                    validation_qa.append({
                        "domanda":  domanda.replace("\\n", "\n").replace('\\"', '"'),
                        "risposta": risposta.replace("\\n", "\n").replace('\\"', '"'),
                    })
                if validation_qa:
                    print(f"[VALIDATE] Regex recovery: {len(validation_qa)} Q&A salvate")
            except Exception:
                pass

        # Also build backward-compatible answers dict
        answers = {}
        for qa in validation_qa:
            q = qa.get("domanda", "?")
            a = qa.get("risposta", "")
            answers[q] = a
            print(f"[VALIDATE] Q: {q[:60]}... -> answered")

        self.progress.complete_phase("VALIDATE")
        return {"answers": answers, "validation_qa": validation_qa}

    # ── PHASE 6: EVALUATE ─────────────────────────────────────────────────────

    async def phase_evaluate(self, topic: str, validation_data: Dict, sandbox_result: Dict = None, gaps: List[str] = None, generated_code: str = None) -> Dict:
        """Evaluate with Test-Driven Learning Protocol: teoria + sandbox + auto-esame."""
        print(f"[EVALUATE] Scoring understanding of: {topic}")
        self.progress.set_phase("EVALUATE", 0.0)

        # 1. Programmatic Sandbox Score (0-2)
        sandbox_score = 0.0
        sandbox_status = "NONE"
        sandbox_stdout = ""
        sandbox_stderr = ""
        sandbox_failed = True

        if sandbox_result:
            sandbox_success = sandbox_result.get("success", False)
            sandbox_stdout = sandbox_result.get("stdout", "")[:800]
            sandbox_stderr = sandbox_result.get("stderr", "")[:500]
            
            if sandbox_success and not sandbox_stderr:
                sandbox_score = 10.0
                sandbox_status = "SUCCESS"
                sandbox_failed = False
            elif sandbox_success and sandbox_stderr:
                sandbox_score = 5.0  # Esegue ma con warning (stdout ok ma stderr non vuoto p.es.)
                sandbox_status = "WARNING"
                sandbox_failed = False
            else:
                sandbox_score = 0.0  # Crash, timeout, ecc.
                sandbox_status = "FAILURE"
                sandbox_failed = True

        # Domain mismatch penalty: penalize when topic signals a domain the code ignores
        _DOMAIN_RULES = [
            (["quantum"], ["hashlib", "hmac", "sha256", "sha512", "md5", "base64"],
             "quantum topic uses only standard hashing libraries"),
        ]
        if generated_code:
            topic_lower = topic.lower()
            code_lower = generated_code.lower()
            for topic_kws, code_kws, reason in _DOMAIN_RULES:
                if any(kw in topic_lower for kw in topic_kws):
                    uses_mismatch = any(kw in code_lower for kw in code_kws)
                    uses_topic_kw = any(kw in code_lower for kw in topic_kws)
                    if uses_mismatch and not uses_topic_kw:
                        print(f"[EVALUATE] [WARN]️ Domain mismatch: {reason}")
                        sandbox_score = max(0.0, sandbox_score - 5.0)

        # Extract answers and validation_qa
        answers = validation_data.get("answers", validation_data)
        validation_qa = validation_data.get("validation_qa", [])

        # GraphRAG: inject causal context so evaluator checks causal understanding
        causal_eval_block = ""
        try:
            from graph_rag import query_causal_context
            causal = query_causal_context(topic)
            if causal:
                causal_eval_block = f"\n=== CAUSAL KNOWLEDGE (known pitfalls for this topic) ===\n{causal}\nCheck whether the agent's answers reflect awareness of these causal relations.\n"
                print(f"[EVALUATE] GraphRAG injected {causal.count(chr(10)) + 1} causal warnings")
        except Exception:
            pass

        prompt = f"""
You are evaluating the understanding of an autonomous learning agent.

Topic: {topic}

Score the following criteria independently.
Return ONLY JSON.

{{
 "theory_score": 0.0,
 "code_score": 0.0,
 "synthesis_score": 0.0,
 "explanation": "short explanation",
 "gaps": ["specific gap 1", "specific gap 2"],
 "hypotheses": ["hypothesis 1", "hypothesis 2"],
 "improvement_focus": "one concrete thing to focus on in the next attempt"
}}

Important rules:
- Score 0 is a valid score. Use it when appropriate.
- A score of 3/3 means exceptional, not merely acceptable.
- If the topic is not a real technical concept, theory_score must be 0.
- Be strict. Avoid default middle scores.
- Penalize hallucinated concepts.

# SCORING RUBRIC

1 - THEORY UNDERSTANDING (0-10)
Evaluate: conceptual correctness, technical validity of topic, synthesis quality.
Rules: 0 = invented/not real, 1-3 = superficial, 4-6 = good, 7-9 = solid, 10 = exceptional.

2 - CODE QUALITY (0-10)
Evaluate: logic correctness, library usage, structure.
Rules: 0 = broken, 1-3 = minimal/fragile, 4-6 = working, 7-9 = robust, 10 = exemplary.

3 - KNOWLEDGE SYNTHESIS (0-10)
Evaluate: integration with previous knowledge, capability graph connections.
Rules: 0 = none, 1-3 = weak, 4-6 = moderate, 7-9 = significant, 10 = deep.

Sandbox context:
Sandbox result: {sandbox_status}
Sandbox stdout excerpt: {sandbox_stdout}
Sandbox stderr excerpt: {sandbox_stderr}

If the sandbox failed, code_score cannot be higher than 1.
{causal_eval_block}
AUTO-EXAM (Questions and Answers):
{json.dumps(validation_qa if validation_qa else answers, indent=2, ensure_ascii=False)}
"""

        print("[EVALUATE] Scoring via Groq (Groq -> Gemini -> Claude fallback)...")
        raw = await self._think_fast(prompt, json_mode=True)
        
        try:
            cleaned = self._clean_json(raw)
            parsed = json.loads(cleaned)
            theory_score = float(parsed.get("theory_score", 0.0))
            code_score = float(parsed.get("code_score", 0.0))
            synthesis_score = float(parsed.get("synthesis_score", 0.0))
            explanation = parsed.get("explanation", "")
            gaps_out = parsed.get("gaps", [])
            hypotheses = parsed.get("hypotheses", [])
            improvement_focus = parsed.get("improvement_focus", "")
            
            # Enforce constraints
            if sandbox_failed:
                code_score = min(code_score, 1.0)

        except Exception as e:
            print(f"[EVALUATE WARNING] Invalid JSON from evaluator \u2014 fallback score applied ({e})")
            print(f"[EVALUATE] Raw response (first 300 chars): {raw[:300]}")
            theory_score = 0.0
            code_score = 0.0
            synthesis_score = 0.0
            explanation = "JSONDecodeError Fallback"
            gaps_out = ["Parse error"]
            hypotheses = []
            improvement_focus = ""

        # ── Rule-based fallback for invalid or inconsistent LLM scores ────
        _scores_out_of_range = (
            not (0.0 <= theory_score <= 10.0)
            or not (0.0 <= code_score <= 10.0)
            or not (0.0 <= synthesis_score <= 10.0)
        )
        _scores_inconsistent = (
            not sandbox_failed and validation_qa and synthesis_score < 5
        )
        if _scores_out_of_range or _scores_inconsistent:
            print("[EVALUATE] Using rule-based fallback scoring")
            sandbox_score   = 10.0 if not sandbox_failed else 0.0
            theory_score    = max(0.0, min(10.0, theory_score))
            code_score      = max(0.0, min(10.0, code_score))
            synthesis_score = max(0.0, min(10.0, synthesis_score))
            if validation_qa and synthesis_score < 5:
                synthesis_score = 5.0

        total_score = round((theory_score + code_score + sandbox_score + synthesis_score) / 40 * 10, 2)
        total_score = max(0.0, min(10.0, total_score))
        # Floor: a passing sandbox guarantees a minimum meaningful score
        if not sandbox_failed:
            total_score = max(3.0, total_score)
        
        # Logging
        print("[EVALUATE]")
        print(f"theory={theory_score}")
        print(f"code={code_score}")
        print(f"sandbox={sandbox_score}")
        print(f"synthesis={synthesis_score}")
        print(f"total={total_score}")
        
        result = {
            "score": total_score,
            "verdict": "PASS" if total_score >= SUCCESS_SCORE_THRESHOLD else "FAIL",
            "gaps": gaps_out,
            "hypotheses": hypotheses,
            "explanation": explanation,
            "improvement_focus": improvement_focus,
            "details": {
                "theory": theory_score,
                "code": code_score,
                "sandbox": sandbox_score,
                "synthesis": synthesis_score
            }
        }
        
        self.progress.complete_phase("EVALUATE")
        return result

    # ── PHASE 7: CERTIFY ──────────────────────────────────────────────────────

    async def phase_certify(self, topic: str, eval_data: Dict) -> bool:
        self.progress.set_phase("CERTIFY", 0.0)
        score     = eval_data.get("score", 0)
        details   = eval_data.get("details", {})
        synthesis = details.get("synthesis", 0)
        sandbox   = details.get("sandbox", 0)

        # Benchmark gate: if a real benchmark ran, pass_rate must meet the threshold.
        # If benchmark was unavailable (fallback mode), this gate is skipped entirely.
        pass_rate            = eval_data.get("pass_rate", None)
        benchmark_available  = eval_data.get("benchmark_available", False)

        reasons = []
        if score < SUCCESS_SCORE_THRESHOLD:
            reasons.append(f"score {score} < {SUCCESS_SCORE_THRESHOLD}")
        if synthesis < 5:
            reasons.append(f"synthesis {synthesis} < 5")
        if sandbox < 5:
            reasons.append(f"sandbox {sandbox} < 5")
        if benchmark_available and pass_rate is not None and pass_rate < BENCHMARK_PASS_THRESHOLD:
            reasons.append(
                f"pass_rate {pass_rate:.0%} < {BENCHMARK_PASS_THRESHOLD:.0%} "
                f"(benchmark gate -- fin delle auto-congratulazioni)"
            )

        if not reasons:
            bench_tag = f" | pass_rate={pass_rate:.0%}" if benchmark_available else " | LLM-only"
            print(f"[CERTIFY] ✅ '{topic}' CERTIFIED -- Score: {score}/10{bench_tag}")
            self.progress.complete_phase("CERTIFY")
            return True
        else:
            print(f"[CERTIFY] ❌ '{topic}' FAILED -- {', '.join(reasons)}")
            return False

    # ── PHASE 7b: BENCHMARK ───────────────────────────────────────────────────

    async def phase_benchmark(
        self,
        topic: str,
        synthesized_code: str,
        eval_data: Dict,
    ) -> Dict:
        """Run objective benchmark tests and blend the result into the eval score.

        If BENCHMARK_ENABLED is False, Docker is unavailable, or generation fails,
        falls back to the LLM-only score transparently (soft degradation).

        Returns a dict with keys to be merged into eval_data:
            score              -- blended final score (or original LLM score on fallback)
            pass_rate          -- 0.0-1.0 (None on fallback)
            benchmark_available -- True when real benchmark ran
            benchmark_detail   -- raw BenchmarkRunner output
        """
        llm_score = eval_data.get("score", 0.0)

        if not BENCHMARK_ENABLED:
            print("[BENCHMARK] Disabled via BENCHMARK_ENABLED=False -- using LLM score")
            return {"score": llm_score, "pass_rate": None, "benchmark_available": False}

        self.progress.set_phase("BENCHMARK", 0.0)
        print(f"[BENCHMARK] Generating tests for '{topic}'...")

        try:
            benchmark = await self.benchmark_generator.generate(
                topic=topic,
                synthesized_code=synthesized_code or "",
            )
        except Exception as e:
            print(f"[BENCHMARK] ❌ Generator exception -- falling back to LLM score: {e}")
            self.progress.complete_phase("BENCHMARK")
            return {"score": llm_score, "pass_rate": None, "benchmark_available": False}

        if not benchmark.get("available"):
            reason = benchmark.get("reason", "no tests generated")
            print(f"[BENCHMARK] Unavailable ({reason}) -- falling back to LLM score")
            self.progress.complete_phase("BENCHMARK")
            return {"score": llm_score, "pass_rate": None, "benchmark_available": False}

        self.progress.set_phase("BENCHMARK", 0.4)
        print(
            f"[BENCHMARK] {benchmark['n_valid']} tests generated -- "
            f"requesting implementation attempt from LLM..."
        )

        # Ask the LLM to implement the scaffold, knowing what it just studied
        scaffold = benchmark.get("scaffold", "def solve(input_data):\n    pass")
        causal_impl_block = ""
        try:
            from graph_rag import query_causal_context
            causal = query_causal_context(topic)
            if causal:
                causal_impl_block = f"\n=== CAUSAL KNOWLEDGE (known pitfalls) ===\n{causal}\nAvoid these pitfalls in your implementation.\n"
                print(f"[BENCHMARK] GraphRAG injected {causal.count(chr(10)) + 1} causal warnings into impl prompt")
        except Exception:
            pass

        # MEMORY: inject FACT memories as implementation hints
        memory_impl_block = self._memory_context_block(
            topic, memory_types=["FACT", "RELATION"],
            label="KNOWN FACTS (apply in implementation)", limit=4,
        )
        if memory_impl_block:
            print(f"[BENCHMARK] Memory injected {memory_impl_block.count(chr(10))} fact memories into impl prompt")

        # Show the LLM the actual test cases so it knows exactly what input_data looks like
        tests = benchmark.get("tests", [])
        tests_preview = ""
        if tests:
            examples = "\n".join(
                f"  # Test {i+1}: {t.get('setup', '')}"
                for i, t in enumerate(tests[:3])
            )
            tests_preview = f"\nThese are the EXACT tests your function must pass:\n{examples}\n"

        impl_prompt = (
            f"You just studied: {topic}\n"
            f"{causal_impl_block}"
            f"{memory_impl_block}"
            f"{tests_preview}\n"
            f"Implement this Python function to satisfy ALL the tests above:\n\n"
            f"{scaffold}\n\n"
            f"CRITICAL: study the test setup lines carefully — they show you exactly what type "
            f"and structure input_data has. Match it precisely.\n"
            f"Return ONLY the complete Python function. No explanation, no markdown."
        )
        try:
            impl_code = await self._think_fast(impl_prompt)
            # Strip markdown fences if present
            impl_code = re.sub(r"```(?:python)?|```", "", impl_code or "").strip()
        except Exception as e:
            print(f"[BENCHMARK] ❌ Implementation LLM call failed -- falling back: {e}")
            self.progress.complete_phase("BENCHMARK")
            return {"score": llm_score, "pass_rate": None, "benchmark_available": False}

        self.progress.set_phase("BENCHMARK", 0.7)
        print("[BENCHMARK] Running tests in sandbox...")

        try:
            bench_result = await self.benchmark_runner.run_benchmark(
                benchmark=benchmark,
                implementation_code=impl_code,
                topic=topic,
            )
        except Exception as e:
            print(f"[BENCHMARK] ❌ Runner exception -- falling back to LLM score: {e}")
            self.progress.complete_phase("BENCHMARK")
            return {"score": llm_score, "pass_rate": None, "benchmark_available": False}

        if not bench_result.get("available") or bench_result.get("total", 0) == 0:
            print("[BENCHMARK] No tests ran -- falling back to LLM score")
            self.progress.complete_phase("BENCHMARK")
            return {"score": llm_score, "pass_rate": None, "benchmark_available": False}

        # ── Blend scores ────────────────────────────────────────────────────
        pass_rate       = bench_result["pass_rate"]
        benchmark_score = pass_rate * 10
        final_score     = round(
            (1 - BENCHMARK_WEIGHT) * llm_score + BENCHMARK_WEIGHT * benchmark_score,
            2
        )
        final_score = max(0.0, min(10.0, final_score))

        print(
            f"[BENCHMARK] LLM={llm_score} × {1-BENCHMARK_WEIGHT:.0%}  +  "
            f"bench={benchmark_score:.1f} × {BENCHMARK_WEIGHT:.0%}  =  "
            f"final={final_score}  (pass_rate={pass_rate:.0%})"
        )

        self.progress.complete_phase("BENCHMARK")
        return {
            "score":               final_score,
            "pass_rate":           pass_rate,
            "benchmark_available": True,
            "benchmark_detail":    bench_result,
        }

    # ── TIER 3: SANDBOX ───────────────────────────────────────────────────────

    async def run_sandbox(self, topic: str, code: str) -> Dict:
        """Delegate to DockerSandboxRunner. Kept for internal compatibility."""
        return await self.sandbox_runner.run(topic, code, progress=self.progress)

    # ── KNOWLEDGE QUERY (for conversations) ───────────────────────────────────

    async def query_knowledge(self, query: str, max_results: int = 3) -> str:
        """Search the knowledge base and return a formatted context for SHARD."""
        try:
            results = self.kb.query(
                query_texts=[query],
                n_results=max_results
            )
            
            if not results["documents"] or not results["documents"][0]:
                return ""
            
            context = "\n--- SHARD KNOWLEDGE BASE ---\n"
            for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
                topic = meta.get("topic", "Unknown")
                timestamp = meta.get("timestamp", "")[:10]
                context += f"\n[{topic}] (studied {timestamp}):\n{doc}\n"
            context += "--- END KNOWLEDGE BASE ---\n"
            
            print(f"[KNOWLEDGE] Found {len(results['documents'][0])} results for: {query[:50]}")
            return context
            
        except Exception as e:
            print(f"[KNOWLEDGE] Query error: {e}")
            return ""

    def get_known_topics(self) -> List[str]:
        """Return list of all topics SHARD has studied."""
        try:
            all_data = self.kb.get()
            topics = set()
            for meta in all_data.get("metadatas", []):
                if meta and "topic" in meta:
                    topics.add(meta["topic"])
            return sorted(list(topics))
        except:
            return []        

    # ── CROSS-REFERENCING ─────────────────────────────────────────────────────

    async def _cross_reference(self, topic: str, data: Dict) -> List[str]:
        """Search connections with existing knowledge in ChromaDB."""
        query = topic + " " + " ".join([c["name"] for c in data.get("concepts", [])[:5]])

        # Guard: skip if collection is empty or unqueryable (avoids ChromaDB
        # "Error finding id" on stale HNSW index entries).
        try:
            n_docs = self.kb.count()
        except Exception:
            return []
        if n_docs < 1:
            return []
        n_results = min(3, n_docs)

        # Try with topic filter first, fall back to unfiltered if ChromaDB
        # chokes on metadata or has index inconsistencies.
        for attempt, kwargs in enumerate([
            {"where": {"topic": {"$ne": topic}}},
            {},
        ]):
            try:
                results = self.kb.query(query_texts=[query], n_results=n_results, **kwargs)
                connections = []
                if results["documents"]:
                    for doc_list in results["documents"]:
                        connections.extend(doc_list)
                if connections:
                    print(f"[CROSS-REF] Found {len(connections)} connections with existing knowledge")
                return connections
            except Exception as e:
                if attempt == 0:
                    print(f"[CROSS-REF] Filter query failed ({e}), retrying without filter...")
                else:
                    print(f"[CROSS-REF] Error: {e}")
        return []

    # ── MAIN STUDY LOOP ───────────────────────────────────────────────────────

    async def study_topic(
        self,
        topic: str,
        tier: int = 1,
        on_progress: Optional[Callable] = None,
        on_certify: Optional[Callable] = None,
        on_web_data: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        previous_score: float = None,
        task_context: str = "",
        predicted_score: Optional[float] = None,
        blind_spots: Optional[list] = None,
        previous_attempts: int = 0,
    ):
        """Complete study loop -- delegates to StudyPipeline.

        Phases are declared as a configurable list. Each phase reads from
        and writes to a shared StudyContext. Fatal phases abort on error;
        non-fatal phases log and continue.
        """
        from study_context import StudyContext
        from study_pipeline import StudyPipeline
        from study_phases import (
            InitPhase, MapPhase, AggregatePhase, SynthesizePhase,
            StorePhase, CrossPollinatePhase, MaterializePhase,
            SandboxPhase, CertifyRetryGroup, PostStudyPhase,
        )

        self.is_running = True
        self._topic_llm_calls = 0  # reset per-topic budget counter
        self.on_web_data = on_web_data
        self.progress = ProgressTracker()

        ctx = StudyContext(
            topic=topic,
            tier=tier,
            agent=self,
            progress=self.progress,
            previous_score=previous_score,
            on_progress=on_progress,
            on_certify=on_certify,
            on_error=on_error,
            on_web_data=on_web_data,
            task_context=task_context,
            predicted_score=predicted_score,
            blind_spots=blind_spots or [],
            previous_attempts=previous_attempts,
        )

        pipeline = StudyPipeline([
            InitPhase(),            # meta-learning hint + episodic memory
            MapPhase(),             # search sources
            AggregatePhase(),       # scrape web pages
            SynthesizePhase(),      # LLM synthesis + cross-reference
            StorePhase(),           # persist to ChromaDB
            CrossPollinatePhase(),  # integration report        (non-fatal)
            MaterializePhase(),     # cheat sheet to filesystem (non-fatal)
            SandboxPhase(),         # code gen + Docker exec    (non-fatal)
            CertifyRetryGroup(),    # VALIDATE->EVALUATE->BENCHMARK->CERTIFY × N
            PostStudyPhase(),       # meta-learning + episodic  (non-fatal)
        ])

        try:
            return await pipeline.execute(ctx)
        finally:
            await self.browser_scraper._close()
            self.is_running = False


# ── DEMO ─────────────────────────────────────────────────────────────────────

async def demo_progress(phase, topic, score, msg, percentage):
    bar = "█" * (percentage // 5) + "░" * (20 - percentage // 5)
    print(f"  [{bar}] {percentage:3d}% | {phase:12s} | {msg}")

async def demo_certify(topic, score, data):
    print(f"\n  ✅ CERTIFIED: {topic}")
    print(f"  Score: {score}/10")
    print(f"  Hypotheses: {data.get('hypotheses', [])}")
    print(f"  Stance: {data.get('shard_stance', '')[:200]}")

if __name__ == "__main__":
    agent = StudyAgent()
    asyncio.run(agent.study_topic(
        "Python async/await concurrency patterns",
        tier=2,
        on_progress=demo_progress,
        on_certify=demo_certify,
    ))
