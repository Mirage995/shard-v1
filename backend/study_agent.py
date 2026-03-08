import os
import asyncio
import re
import json
import random
import subprocess
import uuid
import pathlib
from typing import List, Dict, Any, Optional, Callable
from openai import AsyncOpenAI
from datetime import datetime

from playwright.async_api import async_playwright, Page
from playwright_stealth import Stealth
from bs4 import BeautifulSoup
from groq import Groq, RateLimitError as GroqRateLimitError
import anthropic
from ddgs import DDGS
import chromadb
from chromadb.utils import embedding_functions
from filesystem_tools import write_file
from strategy_memory import StrategyMemory
from capability_graph import CapabilityGraph
from skill_discovery import SkillDiscovery
from experiment_replay import ExperimentReplay
from research_agenda import ResearchAgenda
from experiment_inventor import ExperimentInventor
from experiment_cache import SemanticExperimentCache
from dotenv import load_dotenv

def find_file(filename: str, start_path="."):
    for root, dirs, files in os.walk(start_path):
        if filename in files:
            return os.path.join(root, filename)
    return None

# ── CONFIG ────────────────────────────────────────────────────────────────────
load_dotenv()
import sys
sys.stdout.reconfigure(encoding='utf-8')

GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHROMA_DB_PATH   = os.path.join(os.getcwd(), "knowledge_db")
SANDBOX_DIR      = os.path.join(os.getcwd(), "sandbox")
WORKSPACE_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shard_workspace")
from constants import SUCCESS_SCORE_THRESHOLD
MAX_RETRY        = 3
GROQ_DELAY       = 1.2  # Seconds between Groq calls to avoid rate limiting
ANTHROPIC_DELAY  = 0.5  # Seconds between Anthropic calls

if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY must be set in .env")

# Groq is optional — used for fast/simple LLM tasks only
if not GROQ_API_KEY:
    print("[CONFIG] ⚠️  GROQ_API_KEY not set — all LLM calls will use Claude (slower but works)")

os.makedirs(SANDBOX_DIR, exist_ok=True)

# ── PROGRESS TRACKER ──────────────────────────────────────────────────────────

PHASES = [
    {"name": "MAP",              "weight": 10},
    {"name": "AGGREGATE",        "weight": 20},
    {"name": "SYNTHESIZE",       "weight": 15},
    {"name": "STORE",            "weight": 5},
    {"name": "CROSS_POLLINATE",  "weight": 10},
    {"name": "MATERIALIZE",      "weight": 10},
    {"name": "SANDBOX",          "weight": 10},
    {"name": "VALIDATE",         "weight": 10},
    {"name": "EVALUATE",         "weight": 5},
    {"name": "CERTIFY",          "weight": 5},
]

class ProgressTracker:
    """Tracks study progress as a percentage across all phases."""
    def __init__(self):
        self.current_phase = ""
        self.phase_progress = {}  # phase_name -> 0.0 to 1.0
        self.total_weight = sum(p["weight"] for p in PHASES)
    
    def set_phase(self, phase_name: str, progress: float = 0.0):
        self.current_phase = phase_name
        self.phase_progress[phase_name] = min(1.0, max(0.0, progress))
    
    def complete_phase(self, phase_name: str):
        self.phase_progress[phase_name] = 1.0
    
    @property
    def percentage(self) -> int:
        total = 0
        for p in PHASES:
            total += p["weight"] * self.phase_progress.get(p["name"], 0.0)
        return min(100, int(total / self.total_weight * 100))
    
    @property
    def status(self) -> Dict:
        return {
            "phase": self.current_phase,
            "percentage": self.percentage,
            "phases": {p["name"]: self.phase_progress.get(p["name"], 0.0) for p in PHASES}
        }


class StudyAgent:
    def __init__(self):
        # ── Anthropic Claude (Main Brain — complex reasoning) ──
        self.anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # ── Groq (Fast Brain — simple/quick tasks) ──
        if GROQ_API_KEY:
            self.groq_client = Groq(api_key=GROQ_API_KEY)
            print("[STUDY] ✅ Dual LLM: Claude (complex) + Groq (fast)")
        else:
            self.groq_client = None
            print("[STUDY] ⚠️  Groq disabled — using Claude for all tasks")
        self.chroma      = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        self.emb_fn      = embedding_functions.DefaultEmbeddingFunction()
        self.kb          = self.chroma.get_or_create_collection(
            name="shard_knowledge_base",
            embedding_function=self.emb_fn
        )
        self.is_running  = False
        self.browser     = None
        self.playwright  = None
        self.bctx        = None
        self.progress    = ProgressTracker()
        
        # Ollama local client (OpenAI-compatible API on port 11434)
        self.local_client = AsyncOpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"
        )
        
        # Callback for sending browser screenshots to frontend
        self.on_web_data = None
        
        # ── Strategy Memory & Capability Graph ──
        self.capability_graph = CapabilityGraph()
        
        # Sandbox lazy check flag
        self._sandbox_image_checked = False
        self.strategy_memory = StrategyMemory()
        self.skill_discovery = SkillDiscovery(self.capability_graph)
        self.replay_engine = ExperimentReplay()
        self.experiment_inventor = ExperimentInventor(self.capability_graph)
        self.experiment_cache = SemanticExperimentCache()
        self.research_agenda = ResearchAgenda(
            capability_graph=self.capability_graph,
            replay_engine=self.replay_engine
        )
        
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        ]

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
        # Step 1: try normal json load (after clean)
        cleaned = self._clean_json(raw_text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print("[SYNTHESIZE] JSON invalid — attempting recovery")

        # Step 2: attempt brute force extraction of { ... }
        start = raw_text.find("{")
        end = raw_text.rfind("}")

        if start != -1 and end != -1:
            try:
                recovered = raw_text[start:end+1]
                return json.loads(recovered)
            except Exception:
                pass

        print("[SYNTHESIZE] Recovery failed — returning empty structure")
        return {"concepts": []}

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
        """Core Anthropic Claude reasoning call — wrapped in to_thread to avoid blocking event loop.

        Uses claude-sonnet-4-5-20250929 with max_tokens=2000 hard limit for cost safety.
        Falls back to Ollama local on any Anthropic API error.
        """
        # Strengthen system prompt for JSON mode
        effective_system = system
        if json_mode:
            effective_system += "\nOUTPUT ONLY VALID JSON. Do not include markdown formatting, backticks, code fences, or any conversational text."

        # Rate limit protection
        await asyncio.sleep(ANTHROPIC_DELAY)

        try:
            # Anthropic Messages API — sync call in thread
            def _call_anthropic():
                return self.anthropic_client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=2000,  # Hard limit for cost safety
                    system=effective_system,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                )

            resp = await asyncio.to_thread(_call_anthropic)
            result = resp.content[0].text

            # Clean JSON output if in json_mode
            if json_mode:
                result = self._clean_json(result)
            return result

        except anthropic.RateLimitError:
            # ── FAILOVER: Anthropic 429 → Ollama locale ──
            print("\n" + "=" * 60)
            print("[ANTHROPIC] \u26a0\ufe0f  Rate Limit raggiunto! (429)")
            print("[ANTHROPIC] Fallback su Ollama locale...")
            print("=" * 60 + "\n")
            return await self._think_local(prompt, system, json_mode)

        except anthropic.APIError as e:
            # Handle API-level errors (overloaded, bad request, etc.)
            print(f"[ANTHROPIC] \u274c API Error: {e}")
            print("[ANTHROPIC] Fallback su Ollama locale...")
            return await self._think_local(prompt, system, json_mode)

        except Exception as e:
            print(f"[ANTHROPIC] \u274c Unexpected error: {e}")
            # Fallback to Ollama on any failure
            return await self._think_local(prompt, system, json_mode)

    async def _think_fast(self, prompt: str, system: str = "You are SHARD, an autonomous reasoning AI.", json_mode: bool = False) -> str:
        """Fast Groq reasoning call for simple tasks (query generation, gap analysis).

        Uses llama-3.3-70b-versatile via Groq for speed.
        Falls back to Claude (_think) if Groq is unavailable or rate-limited.
        """
        # If Groq is not configured, fall through to Claude
        if not self.groq_client:
            return await self._think(prompt, system, json_mode)

        effective_system = system
        if json_mode:
            effective_system += "\nOUTPUT ONLY VALID JSON. Do not include markdown formatting, backticks, code fences, or any conversational text."

        # Rate limit protection
        await asyncio.sleep(GROQ_DELAY)

        try:
            def _call_groq():
                return self.groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": effective_system},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2000,
                )

            resp = await asyncio.to_thread(_call_groq)
            result = resp.choices[0].message.content

            if json_mode:
                result = self._clean_json(result)

            print(f"[GROQ] ✅ Fast response ({len(result)} chars)")
            return result

        except GroqRateLimitError:
            print("\n" + "=" * 60)
            print("[GROQ] ⚠️  Rate Limit raggiunto! (429)")
            print("[GROQ] Fallback su Claude (Anthropic)...")
            print("=" * 60 + "\n")
            return await self._think(prompt, system, json_mode)

        except Exception as e:
            print(f"[GROQ] ❌ Error: {e}")
            print("[GROQ] Fallback su Claude (Anthropic)...")
            return await self._think(prompt, system, json_mode)

    async def _think_local(self, prompt: str, system: str = "You are SHARD, an autonomous reasoning AI.", json_mode: bool = False) -> str:
        """Local Ollama reasoning call via OpenAI-compatible API (model: phi3:mini)."""
        print("[EVALUATE] Using lightweight model: phi3:mini")
        effective_system = system
        if json_mode:
            effective_system += "\nOUTPUT ONLY VALID JSON. Do not include markdown formatting, backticks, code fences, or any conversational text."

        kwargs = {
            "model": "phi3:mini",
            "messages": [
                {"role": "system", "content": effective_system},
                {"role": "user",   "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens":  4096,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = await self.local_client.chat.completions.create(**kwargs)
            result = resp.choices[0].message.content
            if json_mode:
                result = self._clean_json(result)
            return result
        except ConnectionError as e:
            print("\n" + "=" * 60)
            print("[OLLAMA] ❌ Impossibile connettersi a Ollama!")
            print("[OLLAMA] Assicurati che Ollama sia in esecuzione: ollama serve")
            print("[OLLAMA] E che il modello phi3:mini sia disponibile: ollama pull phi3:mini")
            print("=" * 60 + "\n")
            raise
        except Exception as e:
            # Catch connection refused and similar network errors
            if "Connection" in type(e).__name__ or "connect" in str(e).lower():
                print("\n" + "=" * 60)
                print("[OLLAMA] ❌ Impossibile connettersi a Ollama!")
                print("[OLLAMA] Assicurati che Ollama sia in esecuzione: ollama serve")
                print("[OLLAMA] E che il modello phi3:mini sia disponibile: ollama pull phi3:mini")
                print("=" * 60 + "\n")
            raise

    # ── BROWSER (VISIBLE + ANTI-DETECTION) ───────────────────────────────────

    async def _init_browser(self, headless: bool = False):
        """Launch browser — headless=False so Boss can see it working."""
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ]
            )
            self.bctx = await self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=random.choice(self.user_agents),
                locale="it-IT",
                timezone_id="Europe/Rome",
            )
            # Anti-detection: stealth is applied per-page via stealth_async()

    async def _close_browser(self):
        if self.browser:
            try:
                await self.browser.close()
                await self.playwright.stop()
            except:
                pass
            self.browser = self.playwright = self.bctx = None

    async def _take_screenshot(self, page: Page, label: str = ""):
        """Capture screenshot and send to frontend if callback is set."""
        try:
            screenshot = await page.screenshot(type="jpeg", quality=60)
            import base64
            b64 = base64.b64encode(screenshot).decode("utf-8")
            if self.on_web_data:
                self.on_web_data({
                    "image": b64,
                    "log": f"[STUDY] {label}" if label else "[STUDY] Browsing..."
                })
        except:
            pass

    async def _handle_cookies(self, page: Page):
        """Try to dismiss common cookie consent banners."""
        cookie_selectors = [
            # Common cookie button selectors
            "button:has-text('Accept')",
            "button:has-text('Accetta')",
            "button:has-text('Accept all')",
            "button:has-text('Accetta tutto')",
            "button:has-text('Accetta tutti')",
            "button:has-text('Accept All Cookies')",
            "button:has-text('Allow all')",
            "button:has-text('Consenti tutti')",
            "button:has-text('Got it')",
            "button:has-text('OK')",
            "button:has-text('Agree')",
            "[id*='accept']",
            "[id*='consent']",
            "[class*='accept']",
            "[class*='consent'] button",
            "#onetrust-accept-btn-handler",
            ".cc-accept",
            ".cookie-accept",
            "#cookie-accept",
            "[data-testid='cookie-accept']",
        ]
        
        for selector in cookie_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    print(f"[COOKIES] Dismissed with: {selector}")
                    await asyncio.sleep(0.5)
                    return True
            except:
                continue
        return False

    async def _handle_captcha(self, page: Page) -> bool:
        """Detect captcha and wait for manual resolution if browser is visible."""
        captcha_indicators = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            "[class*='captcha']",
            "[id*='captcha']",
            "iframe[src*='challenge']",
            ".g-recaptcha",
            "#cf-challenge-running",  # Cloudflare
        ]
        
        for selector in captcha_indicators:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=500):
                    print(f"[CAPTCHA] ⚠️ Captcha detected! Waiting for manual resolution...")
                    await self._take_screenshot(page, "⚠️ CAPTCHA DETECTED - Solve manually!")
                    
                    # Wait up to 60 seconds for captcha to disappear
                    for _ in range(60):
                        await asyncio.sleep(1)
                        try:
                            if not await el.is_visible(timeout=300):
                                print("[CAPTCHA] ✅ Captcha resolved!")
                                return True
                        except:
                            print("[CAPTCHA] ✅ Captcha resolved!")
                            return True
                    
                    print("[CAPTCHA] ❌ Timeout waiting for captcha resolution")
                    return False
            except:
                continue
        return True  # No captcha found = OK

    async def _safe_goto(self, page: Page, url: str, label: str = "") -> bool:
        """Navigate to URL with cookie/captcha handling and screenshot."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(0.5)
            
            # Handle cookies
            await self._handle_cookies(page)
            
            # Check for captcha
            captcha_ok = await self._handle_captcha(page)
            if not captcha_ok:
                return False
            
            # Send screenshot to frontend
            await self._take_screenshot(page, label or f"Loaded: {url[:60]}")
            return True
            
        except Exception as e:
            print(f"[BROWSER] Navigation failed: {url} — {e}")
            return False

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

        # Blocked domains that return garbage
        blocked = [
            "zhihu.com", "quora.com", "pinterest.com", "facebook.com",
            "instagram.com", "tiktok.com", "reddit.com/user/",
            "youtube.com", "kela.fi",
        ]

        def _search():
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
                        print(f"[MAP] Query failed: {query} — {e}")

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

        # Score and sort by relevance
        topic_words = set(topic.lower().split())
        for s in sources:
            title_words = set(s["title"].lower().split())
            s["relevance"] = len(topic_words & title_words) + (1 if s["tier"] == 2 else 0)
        sources.sort(key=lambda x: x["relevance"], reverse=True)

        print(f"[MAP] Found {len(sources)} unique sources (sorted by relevance)")
        for s in sources[:8]:
            print(f"  [{s['relevance']}] {s['title'][:60]} — {s['url'][:50]}")

        self.progress.complete_phase("MAP")
        return sources

    # ── PHASE 2: AGGREGATE ────────────────────────────────────────────────────

    async def phase_aggregate(self, sources: List[Dict]) -> str:
        """Scrape and clean text from web pages with visible Playwright."""
        max_sources = min(len(sources), 6)
        print(f"[AGGREGATE] Scraping {max_sources} sources...")
        self.progress.set_phase("AGGREGATE", 0.0)
        
        await self._init_browser(headless=False)
        all_text = ""

        for idx, source in enumerate(sources[:max_sources]):
            url = source["url"]
            self.progress.set_phase("AGGREGATE", idx / max_sources)
            
            try:
                page = await self.bctx.new_page()
                await Stealth().apply_stealth_async(page)
                success = await self._safe_goto(page, url, f"Reading [{idx+1}/{max_sources}]: {source['title'][:50]}")
                
                if success:
                    content = await page.content()
                    
                    soup = BeautifulSoup(content, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"]):
                        tag.extract()

                    text = soup.get_text(separator="\n", strip=True)
                    # Filter short lines (likely menus, buttons)
                    text = "\n".join(line for line in text.splitlines() if len(line) > 40)
                    all_text += f"\n\n--- SOURCE: {source['title']} ({url}) ---\n{text[:3000]}"
                    print(f"[AGGREGATE] ✅ [{idx+1}/{max_sources}] {source['title'][:50]} ({len(text)} chars)")
                else:
                    print(f"[AGGREGATE] ❌ [{idx+1}/{max_sources}] Failed: {url}")
                
                await page.close()
                
                # Small delay between pages to be polite
                await asyncio.sleep(0.8)

            except Exception as e:
                print(f"[AGGREGATE] ❌ Failed {url}: {e}")
                try:
                    await page.close()
                except:
                    pass

        print(f"[AGGREGATE] Total raw text: {len(all_text)} chars")
        self.progress.complete_phase("AGGREGATE")
        return all_text

    # ── PHASE 3: SYNTHESIZE ───────────────────────────────────────────────────

    async def phase_synthesize(self, topic: str, raw: str) -> Dict:
        """SHARD processes, connects and reasons on raw content (Metodo Feynman)."""
        print(f"[SYNTHESIZE] Building structured knowledge (Metodo Feynman) for: {topic}")
        self.progress.set_phase("SYNTHESIZE", 0.0)

        prompt = f"""
You are SHARD. Study the following raw content about "{topic}" and synthesize it using the Feynman Method.

RAW CONTENT:
{raw[:8000]}

Your task:
1. Extract the 5-10 key concepts with clear explanations.
2. Identify relationships between concepts.
3. Form YOUR OWN OPINION on the topic based on evidence.
4. Generate 3 critical questions that reveal deep understanding.
5. Write a brief "teoria" summary of the key theoretical points.
6. Write a "spiegazione" that explains the topic in simple terms (Feynman-style).

Return ONLY a valid JSON object with this structure:
{{
    "concepts": [{{"name": "...", "explanation": "...", "importance": 1-10}}],
    "relationships": ["concept A relates to concept B because..."],
    "shard_opinion": "SHARD's reasoned stance on this topic...",
    "critical_questions": ["...", "...", "..."],
    "teoria": "Theoretical summary of core concepts...",
    "spiegazione": "Simple explanation in Feynman-style...",
    "codice_pratico": "A fully runnable Python 3 snippet testing the core concept."
}}

IMPORTANT EXECUTION CONSTRAINTS FOR `codice_pratico`:
The generated code MUST terminate by itself.
Do NOT start persistent servers (Flask, FastAPI, HTTPServer).
Do NOT start infinite loops.
Do NOT start blocking network listeners.

Instead:
- Demonstrate the concept using short simulations
- Use mock requests or simple function calls
- Use unit-test style examples when relevant
- If demonstrating a REST API, write a test script that simulates requests and prints responses, DO NOT start the server with app.run() or HTTPServer.serve_forever()

The script must finish execution in under 5 seconds.

Rules:
- JSON must be valid
- do not add explanations outside JSON
- return only JSON
"""
        self.progress.set_phase("SYNTHESIZE", 0.5)
        raw_json = await self._think(prompt, json_mode=True)

        result = self._safe_parse_json(raw_json)
        if result.get("concepts"):
            print(f"[SYNTHESIZE] JSON parsed successfully ({len(result['concepts'])} concepts)")
        else:
            print(f"[SYNTHESIZE] Warning: no concepts extracted")

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
                print("[CROSS-POLLINATE] No existing knowledge found — this is SHARD's first topic")
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
                documents=[f"Integration Report — {topic}:\n{report}"],
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

    async def phase_materialize(self, topic: str, structured: Dict) -> bool:
        """Generate a structured Cheat Sheet and write it to the filesystem."""
        print(f"[MATERIALIZE] Creating Cheat Sheet for: {topic}")
        self.progress.set_phase("MATERIALIZE", 0.0)

        # 1. Build LLM prompt for Cheat Sheet generation
        concepts_summary = json.dumps(structured.get("concepts", []), indent=2)[:3000]
        code_snippet = structured.get("code_snippet", "")

        prompt = f"""You are SHARD. Generate a structured Cheat Sheet in Markdown for the topic "{topic}".

Based on these synthesized concepts:
{concepts_summary}

SHARD's opinion: {structured.get('shard_opinion', 'N/A')}

The Cheat Sheet MUST follow this exact structure:

# {topic} — SHARD Cheat Sheet

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

        prompt = f"""
Sei SHARD. Hai appena studiato "{topic}".

TEORIA APPRESA:
{teoria[:2000]}
{sandbox_context}

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
            validation_qa = []

        # Also build backward-compatible answers dict
        answers = {}
        for qa in validation_qa:
            q = qa.get("domanda", "?")
            a = qa.get("risposta", "")
            answers[q] = a
            print(f"[VALIDATE] Q: {q[:60]}... → answered")

        self.progress.complete_phase("VALIDATE")
        return {"answers": answers, "validation_qa": validation_qa}

    # ── PHASE 6: EVALUATE ─────────────────────────────────────────────────────

    async def phase_evaluate(self, topic: str, validation_data: Dict, sandbox_result: Dict = None, gaps: List[str] = None) -> Dict:
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
                sandbox_score = 2.0
                sandbox_status = "SUCCESS"
                sandbox_failed = False
            elif sandbox_success and sandbox_stderr:
                sandbox_score = 1.0 # Esegue ma con warning (stdout ok ma stderr non vuoto p.es.)
                sandbox_status = "WARNING"
                sandbox_failed = False
            else:
                sandbox_score = 0.0 # Crash, timeout, ecc.
                sandbox_status = "FAILURE"
                sandbox_failed = True

        # Extract answers and validation_qa
        answers = validation_data.get("answers", validation_data)
        validation_qa = validation_data.get("validation_qa", [])

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
 "hypotheses": ["hypothesis 1", "hypothesis 2"]
}}

Important rules:
- Score 0 is a valid score. Use it when appropriate.
- A score of 3/3 means exceptional, not merely acceptable.
- If the topic is not a real technical concept, theory_score must be 0.
- Be strict. Avoid default middle scores.
- Penalize hallucinated concepts.

# SCORING RUBRIC

1 - THEORY UNDERSTANDING (0-3)
Evaluate: conceptual correctness, technical validity of topic, synthesis quality.
Rules: 0 = not real/invented, 1 = superficial, 2 = good, 3 = solid

2 - CODE QUALITY (0-3)
Evaluate: logic correctness, library usage, structure.
Rules: 0 = broken, 1 = minimal/fragile, 2 = working, 3 = robust.

3 - KNOWLEDGE SYNTHESIS (0-2)
Evaluate: integration with previous knowledge, capability graph connections.
Rules: 0 = none, 1 = weak, 2 = significant.

Sandbox context:
Sandbox result: {sandbox_status}
Sandbox stdout excerpt: {sandbox_stdout}
Sandbox stderr excerpt: {sandbox_stderr}

If the sandbox failed, code_score cannot be higher than 1.

AUTO-EXAM (Questions and Answers):
{json.dumps(validation_qa if validation_qa else answers, indent=2, ensure_ascii=False)}
"""

        print("[EVALUATE] Using local Ollama (mistral/phi3) for evaluation...")
        raw = await self._think_local(prompt, json_mode=True)
        
        try:
            cleaned = self._clean_json(raw)
            parsed = json.loads(cleaned)
            theory_score = float(parsed.get("theory_score", 0.0))
            code_score = float(parsed.get("code_score", 0.0))
            synthesis_score = float(parsed.get("synthesis_score", 0.0))
            explanation = parsed.get("explanation", "")
            gaps_out = parsed.get("gaps", [])
            hypotheses = parsed.get("hypotheses", [])
            
            # Enforce constraints
            if sandbox_failed:
                code_score = min(code_score, 1.0)
                
            total_score = theory_score + code_score + synthesis_score + sandbox_score
            
        except Exception as e:
            print(f"[EVALUATE WARNING] Invalid JSON from evaluator \u2014 fallback score applied ({e})")
            print(f"[EVALUATE] Raw response (first 300 chars): {raw[:300]}")
            theory_score = 0.0
            code_score = 0.0
            synthesis_score = 0.0
            total_score = 4.0
            explanation = "JSONDecodeError Fallback"
            gaps_out = ["Parse error"]
            hypotheses = []

        total_score = max(0.0, min(10.0, total_score))
        
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
        score = eval_data.get("score", 0)
        if score >= SUCCESS_SCORE_THRESHOLD:
            print(f"[CERTIFY] ✅ '{topic}' CERTIFIED — Score: {score}/10")
            self.progress.complete_phase("CERTIFY")
            return True
        else:
            print(f"[CERTIFY] ❌ '{topic}' FAILED — Score: {score}/10 (need {SUCCESS_SCORE_THRESHOLD})")
            return False

    # ── TIER 3: SANDBOX ───────────────────────────────────────────────────────

    # ── Docker Sandbox Configuration ───────────────────────────────────────────
    DOCKER_IMAGE = "shard-sandbox:latest"
    MAX_OUTPUT_CHARS = 50_000
    SANDBOX_TIMEOUT = 30

    def _validate_sandbox_path(self, sandbox_dir: str) -> pathlib.Path:
        """Validate and resolve sandbox directory path with security checks.

        Prevents symlink escape and directory traversal attacks.
        Returns the resolved absolute path as a pathlib.Path.
        Raises SecurityError (ValueError) on any violation.
        """
        sandbox_path = pathlib.Path(sandbox_dir).resolve()

        # 1. Must be absolute after resolution
        if not sandbox_path.is_absolute():
            raise ValueError(f"[SANDBOX SECURITY] Path is not absolute: {sandbox_path}")

        # 2. Walk every component — reject if any segment is a symlink
        check = sandbox_path
        while check != check.parent:  # Walk up to root
            if check.exists() and check.is_symlink():
                raise ValueError(
                    f"[SANDBOX SECURITY] Symlink detected in sandbox path: {check}"
                )
            check = check.parent

        # 3. Verify the resolved path hasn't escaped the expected parent
        #    (prevents crafted paths like sandbox/../../etc)
        expected_parent = pathlib.Path(SANDBOX_DIR).resolve().parent
        if not str(sandbox_path).startswith(str(expected_parent)):
            raise ValueError(
                f"[SANDBOX SECURITY] Path traversal detected: {sandbox_path} "
                f"is outside {expected_parent}"
            )

        return sandbox_path

    def _build_docker_command(self, sandbox_posix: str, filename: str, container_name: str) -> list:
        """Build the hardened Docker run command with all security flags.

        Returns a list of arguments for subprocess.run().
        """
        return [
            "docker", "run",
            "--rm",                                          # Auto-destroy container
            "--network", "none",                              # No network access
            "-m", "256m",                                     # RAM limit
            "--cpus=0.5",                                     # CPU limit
            "--pids-limit", "64",                              # Fork bomb prevention
            "--read-only",                                    # Read-only filesystem
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",      # Controlled temp area
            "--security-opt", "no-new-privileges",            # Block privilege escalation
            "--cap-drop", "ALL",                              # Drop all Linux capabilities
            "--ulimit", "nofile=64:64",                       # File descriptor limit
            "--user", "1000:1000",                            # Non-root execution
            "-v", f"{sandbox_posix}:/app:rw",                 # Mount only sandbox dir
            "-w", "/app",                                     # Working directory
            "--name", container_name,                         # Unique name for kill
            self.DOCKER_IMAGE,                                # Custom hardened image
            "python", filename,                               # Execute the script
        ]

    async def _ensure_sandbox_image(self):
        """Ensure the sandbox docker image exists, building it if necessary. Runs once per session."""
        if getattr(self, "_sandbox_image_checked", False):
            return

        try:
            # Check if image exists
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "image", "inspect", self.DOCKER_IMAGE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            self._sandbox_image_checked = True
        except subprocess.CalledProcessError:
            print(f"[SANDBOX] 🔨 Docker image '{self.DOCKER_IMAGE}' not found. Building it automatically...")
            build_cmd = [
                "docker", "build", "-t", self.DOCKER_IMAGE,
                "-f", "backend/Dockerfile.sandbox", "backend/"
            ]
            try:
                await asyncio.to_thread(
                    subprocess.run, build_cmd, check=True
                )
                print(f"[SANDBOX] ✅ Docker image built successfully.")
                self._sandbox_image_checked = True
            except subprocess.CalledProcessError as e:
                error_msg = f"Failed to automatically build docker image '{self.DOCKER_IMAGE}'."
                print(f"[SANDBOX] ❌ {error_msg} ({e})")
                raise RuntimeError(error_msg)

    async def run_sandbox(self, topic: str, code: str) -> Dict:
        """Execute LLM-generated code in a hardened Docker container.

        Security layers:
        - Docker container isolation (not host execution)
        - No network, no capabilities, no privilege escalation
        - Read-only filesystem with controlled /tmp
        - Resource limits (RAM, CPU, PIDs, file descriptors)
        - Non-root user (sandbox:1000)
        - Path validation (symlink + traversal prevention)
        - 30s timeout with explicit container kill
        - Output truncation (50k chars)
        """
        print(f"[SANDBOX] Executing code in Docker container for: {topic}")
        self.progress.set_phase("SANDBOX", 0.0)

        container_name = f"shard-sandbox-{uuid.uuid4().hex[:12]}"
        filename = f"study_{uuid.uuid4().hex[:8]}.py"

        try:
            # ── 1. Verify Docker image exists (once per session) ─────────
            try:
                await self._ensure_sandbox_image()
            except RuntimeError as e:
                error_msg = str(e)
                self.progress.complete_phase("SANDBOX")
                return {
                    "success": False, "stdout": "",
                    "stderr": error_msg,
                    "analysis": f"Sandbox unavailable: {error_msg}",
                    "code": code
                }

            # ── 2. Path security ─────────────────────────────────────────
            sandbox_path = self._validate_sandbox_path(SANDBOX_DIR)
            os.makedirs(sandbox_path, exist_ok=True)

            # Convert to POSIX format for Docker mount (Windows compat)
            sandbox_posix = sandbox_path.as_posix()

            # Write code to sandbox directory
            filepath = sandbox_path / filename
            # Verify the resolved file path stays inside sandbox
            resolved_filepath = filepath.resolve()
            if not str(resolved_filepath).startswith(str(sandbox_path)):
                raise ValueError(
                    f"[SANDBOX SECURITY] File path escapes sandbox: {resolved_filepath}"
                )

            filepath.write_text(code, encoding="utf-8")
            print(f"[SANDBOX] Code saved to: {filepath}")
            print(f"[SANDBOX] Code ({len(code)} chars):\n{code[:300]}...")
            sys.stdout.flush()

            self.progress.set_phase("SANDBOX", 0.3)

            # ── 3. Build Docker command ──────────────────────────────────
            docker_cmd = self._build_docker_command(sandbox_posix, filename, container_name)
            print(f"[SANDBOX] Docker command: {' '.join(docker_cmd[:10])}...")

            # ── 4. Execute with timeout ──────────────────────────────────
            try:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    docker_cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.SANDBOX_TIMEOUT
                )
                stdout = (proc.stdout or "").strip()[:self.MAX_OUTPUT_CHARS]
                stderr = (proc.stderr or "").strip()[:self.MAX_OUTPUT_CHARS]
                success = proc.returncode == 0

            except subprocess.TimeoutExpired:
                # ── 5. Timeout → explicit container kill ─────────────────
                print(f"[SANDBOX] ⚠️ Timeout ({self.SANDBOX_TIMEOUT}s) — killing container {container_name}")
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "kill", container_name],
                        capture_output=True, timeout=10
                    )
                    print(f"[SANDBOX] Container {container_name} killed successfully")
                except Exception as kill_err:
                    # Kill failure must never crash the agent
                    print(f"[SANDBOX] ⚠️ docker kill failed (non-fatal): {kill_err}")

                self.progress.complete_phase("SANDBOX")
                return {
                    "success": False, "stdout": "",
                    "stderr": f"Timeout ({self.SANDBOX_TIMEOUT}s)",
                    "analysis": f"Code execution exceeded {self.SANDBOX_TIMEOUT}-second timeout",
                    "code": code
                }

            self.progress.set_phase("SANDBOX", 0.7)

            print(f"[SANDBOX] {'✅' if success else '❌'} Exit code: {proc.returncode}")
            print(f"[SANDBOX] stdout: {stdout[:300]}")
            if stderr:
                print(f"[SANDBOX] stderr: {stderr[:300]}")

            # ── 6. Cleanup temp file ─────────────────────────────────────
            try:
                filepath.unlink(missing_ok=True)
            except Exception:
                pass

            # ── 7. LLM analysis ──────────────────────────────────────────
            analysis_prompt = f"""
Code eseguito per "{topic}":
{code[:1500]}

Risultato:
STDOUT: {stdout[:500] or '(vuoto)'}
STDERR: {stderr[:500] or '(nessuno)'}
Return code: {proc.returncode}

Analizza brevemente: Il codice funziona? Dimostra comprensione reale di {topic}?
"""
            analysis = await self._think(analysis_prompt)  # Claude: complex code analysis

            self.progress.complete_phase("SANDBOX")
            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "analysis": analysis,
                "code": code
            }

        except Exception as e:
            print(f"[SANDBOX] ❌ Exception: {e}")
            import traceback; traceback.print_exc()
            # Cleanup on error
            try:
                sandbox_path_cleanup = pathlib.Path(SANDBOX_DIR).resolve() / filename
                sandbox_path_cleanup.unlink(missing_ok=True)
            except Exception:
                pass
            self.progress.complete_phase("SANDBOX")
            return {
                "success": False, "stdout": "",
                "stderr": str(e), "analysis": f"Sandbox error: {e}",
                "code": code
            }

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
        try:
            query = topic + " " + " ".join([c["name"] for c in data.get("concepts", [])[:5]])
            results = self.kb.query(
                query_texts=[query],
                n_results=3,
                where={"topic": {"$ne": topic}}
            )
            connections = []
            if results["documents"]:
                for doc_list in results["documents"]:
                    connections.extend(doc_list)
            if connections:
                print(f"[CROSS-REF] Found {len(connections)} connections with existing knowledge")
            return connections
        except Exception as e:
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
    ):
        """Complete study loop with automatic retry up to MAX_RETRY attempts."""
        self.is_running = True
        self.on_web_data = on_web_data
        attempt = 0
        gaps = []
        current_phase = "INIT"

        # ── RESET PROGRESS (fix: second study starting at 100%) ──
        self.progress = ProgressTracker()

        async def progress(phase: str, score: float, msg: str):
            pct = self.progress.percentage
            print(f"[SHARD.STUDY] [{pct:3d}%] {phase} | {score}/10 | {msg}")
            sys.stdout.flush()
            if on_progress:
                await on_progress(phase, topic, score, msg, pct)

        # Emit INIT at 0% so frontend resets immediately
        await progress("INIT", 0, f"Starting study of '{topic}'...")

        async def report_crash(phase: str, error: Exception):
            """Report crash to logs, frontend UI, and on_error callback."""
            import traceback as tb
            error_msg = f"CRITICAL ERROR during phase {phase}: {type(error).__name__}: {error}"
            full_trace = tb.format_exc()
            
            # Detailed log to terminal
            print(f"\n{'='*60}")
            print(f"[CRITICAL] {error_msg}")
            print(f"[CRITICAL] Full traceback:")
            print(full_trace)
            print(f"{'='*60}\n")
            sys.stdout.flush()
            sys.stderr.flush()
            
            # Notify frontend UI (phase = ERROR)
            await progress("ERROR", 0, f"Crash in {phase}: {str(error)[:200]}")
            
            # Call on_error callback if provided (for vocal notification)
            if on_error:
                try:
                    await on_error(topic, phase, str(error))
                except Exception as cb_err:
                    print(f"[CRITICAL] on_error callback also failed: {cb_err}")

        try:
            # ── PHASE 1: MAP
            current_phase = "MAP"
            try:
                await progress("MAP", 0, f"Searching sources for '{topic}'...")
                sources = await self.phase_map(topic, tier)
                print(f"[MAP] ✅ Phase completed. {len(sources)} sources found.")
            except Exception as e:
                await report_crash("MAP", e)
                return

            # ── PHASE 2: AGGREGATE
            current_phase = "AGGREGATE"
            try:
                await progress("AGGREGATE", 0, f"Scraping {len(sources)} sources...")
                print(f"[AGGREGATE] Entering phase. Initializing browser...")
                sys.stdout.flush()
                raw_text = await self.phase_aggregate(sources)
                print(f"[AGGREGATE] ✅ Phase completed. {len(raw_text)} chars scraped.")
            except Exception as e:
                await report_crash("AGGREGATE", e)
                return

            if not raw_text.strip():
                await progress("ERROR", 0, "No content could be scraped from any source.")
                if on_error:
                    await on_error(topic, "AGGREGATE", "No content could be scraped from any source")
                return

            # ── PHASE 3: SYNTHESIZE
            current_phase = "SYNTHESIZE"
            try:
                await progress("SYNTHESIZE", 0, "Building structured knowledge...")
                structured = await self.phase_synthesize(topic, raw_text)
                print(f"[SYNTHESIZE] ✅ Phase completed. {len(structured.get('concepts', []))} concepts extracted.")
            except Exception as e:
                await report_crash("SYNTHESIZE", e)
                return

            # Cross-referencing with existing knowledge
            try:
                connections = await self._cross_reference(topic, structured)
                structured["connections"] = connections
                if connections:
                    await progress("SYNTHESIZE", 0, f"Found {len(connections)} connections with existing knowledge")
            except Exception as e:
                print(f"[CROSS-REF] Non-fatal error: {e}")
                connections = []
                structured["connections"] = []

            # ── PHASE 4: STORE
            current_phase = "STORE"
            try:
                await progress("STORE", 0, "Persisting to knowledge base...")
                await self.phase_store(topic, structured)
                print(f"[STORE] ✅ Phase completed.")
            except Exception as e:
                await report_crash("STORE", e)
                return

            # ── PHASE 4b: CROSS-POLLINATE
            current_phase = "CROSS_POLLINATE"
            try:
                await progress("CROSS_POLLINATE", 0, "Generating Integration Report...")
                integration_report = await self.phase_cross_pollinate(topic, raw_text, structured)
                if integration_report:
                    await progress("CROSS_POLLINATE", 0, f"Integration Report: {integration_report[:100]}...")
                print(f"[CROSS-POLLINATE] ✅ Phase completed.")
            except Exception as e:
                print(f"[CROSS-POLLINATE] Non-fatal error: {e}")
                import traceback; traceback.print_exc()
                self.progress.complete_phase("CROSS_POLLINATE")

            # ── PHASE 4c: MATERIALIZE
            current_phase = "MATERIALIZE"
            try:
                await progress("MATERIALIZE", 0, "Writing Cheat Sheet to filesystem...")
                mat_ok = await self.phase_materialize(topic, structured)
                if mat_ok:
                    await progress("MATERIALIZE", 0, f"Cheat Sheet saved to knowledge_base/")
                else:
                    await progress("MATERIALIZE", 0, "Cheat Sheet materialization failed")
                print(f"[MATERIALIZE] ✅ Phase completed.")
            except Exception as e:
                print(f"[MATERIALIZE] Non-fatal error: {e}")
                import traceback; traceback.print_exc()
                self.progress.complete_phase("MATERIALIZE")

            # --- SANDBOX PHASE (Decoupled from theory JSON) ---
            sandbox_result = None
            current_phase = "SANDBOX"
            
            strategy = await self.retrieve_strategy(topic)
            
            if strategy:
                await progress("SANDBOX", 0, "Using past strategy to guide code generation")
                print("[STUDY] Using past strategy")
                print("[SANDBOX] Generating code independently from theory phase")
                
                prompt_codice = f"""
Topic: {topic}

Previous successful strategy:
{strategy}

Write a minimal executable Python script demonstrating the topic.

Rules:
- valid Python code
- no markdown
- no explanations
- executable script only
"""
            else:
                await progress("SANDBOX", 0, "Generating code independently from theory phase")
                print("[SANDBOX] Generating code independently from theory phase")

                prompt_codice = f"""
Write a minimal executable Python script demonstrating: {topic}

Rules:
- valid Python code
- no markdown
- no explanations
"""

            codice_generato = None

            try:
                codice_generato = await self._think_fast(prompt_codice)
            except Exception as e:
                print(f"[SANDBOX] Code generation failed: {e}")

            # pulizia markdown se presenti
            if codice_generato:
                if "```" in codice_generato:
                    lines = codice_generato.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    codice_generato = "\n".join(lines).strip()
            else:
                print("[SANDBOX] No code generated by model")

            # esecuzione sandbox solo se codice esiste
            if codice_generato:
                try:
                    await progress("SANDBOX", 0, "Executing generated code")
                    print("[SANDBOX] Executing generated code")

                    sandbox_result = await self.run_sandbox(topic, codice_generato)
                    
                    status = "passed" if sandbox_result["success"] else "failed"
                    await progress("SANDBOX", 0, f"Sandbox {status}: {sandbox_result['analysis'][:100]}")
                    print("[SANDBOX] Execution completed")

                except Exception as e:
                    print(f"[SANDBOX] Execution error: {e}")
                    import traceback; traceback.print_exc()
                    sandbox_result = {"success": False, "stdout": "", "stderr": str(e), "analysis": f"Sandbox crash: {e}", "code": codice_generato}
            else:
                print("[SANDBOX] Skipping execution (no code produced)")
            
            self.progress.complete_phase("SANDBOX")

            # ── RETRY LOOP: VALIDATE → EVALUATE → CERTIFY
            certified = False
            score = 0
            while attempt < MAX_RETRY and not certified:
                attempt += 1
                current_phase = "VALIDATE"
                try:
                    await progress("VALIDATE", 0, f"Self-interrogation (attempt {attempt}/{MAX_RETRY})...")
                    validation_data = await self.phase_validate(topic, structured, sandbox_result=sandbox_result)
                except Exception as e:
                    await report_crash("VALIDATE", e)
                    return

                current_phase = "EVALUATE"
                try:
                    await progress("EVALUATE", 0, "Scoring with Test-Driven Protocol...")
                    eval_data = await self.phase_evaluate(
                        topic, validation_data,
                        sandbox_result=sandbox_result,
                        gaps=gaps if attempt > 1 else None
                    )
                    score = eval_data.get("score", 0)

                    # ── Strategy Memory: extract and store strategy ──
                    try:
                        experiment = {
                            "topic": topic,
                            "sandbox_result": sandbox_result,
                            "eval_data": eval_data,
                            "structured": structured,
                        }
                        strategy_info = self.strategy_memory.extract_strategy(experiment)
                        if strategy_info:
                            self.strategy_memory.store_strategy(
                                topic,
                                strategy_info["strategy"],
                                strategy_info["outcome"],
                                score=strategy_info.get("score", 0),
                            )
                            # Update capability graph only on success
                            if strategy_info["outcome"] == "success":
                                self.capability_graph.update_from_strategy(
                                    topic,
                                    strategy_info["strategy"]
                                )
                                # Discover implicit skills from strategy
                                self.skill_discovery.discover_from_experiment(
                                    topic,
                                    strategy_info["strategy"]
                                )
                    except Exception as strat_err:
                        print(f"[STRATEGY] Error extracting/storing strategy: {strat_err}")

                    # ── Experiment Replay & Cache: log this experiment ──
                    
                    if eval_data and eval_data.get("score", 0) < SUCCESS_SCORE_THRESHOLD:
                        current_skills = len(self.capability_graph.capabilities) if self.capability_graph else 0
                        self.experiment_cache.register_failure(topic, current_skills)

                    self.replay_engine.log_experiment(
                        topic,
                        score=eval_data.get("score", 0),
                        success=eval_data.get("score", 0) >= SUCCESS_SCORE_THRESHOLD
                    )

                except Exception as e:
                    await report_crash("EVALUATE", e)
                    return

                current_phase = "CERTIFY"
                certified = await self.phase_certify(topic, eval_data)

                if certified:
                    await progress("CERTIFY", score, f"Topic certified! Score: {score}/10")
                    await progress("CERTIFY", score, f"SHARD stance: {eval_data.get('shard_stance', '')[:120]}")
                    if on_certify:
                        await on_certify(topic, score, {
                            **eval_data,
                            "sandbox": sandbox_result,
                            "concepts": structured.get("concepts", []),
                            "shard_opinion": structured.get("shard_opinion", ""),
                            "connections": connections,
                            "validation_qa": validation_data.get("validation_qa", [])
                        })
                else:
                    gaps = eval_data.get("gaps", [])
                    focus = eval_data.get("improvement_focus", "")
                    await progress("VALIDATE", score, f"Score {score}/10 — Retrying. Focus: {focus[:80]}")

                    if attempt < MAX_RETRY:
                        # Reset validation/evaluation progress for retry
                        self.progress.phase_progress["VALIDATE"] = 0
                        self.progress.phase_progress["EVALUATE"] = 0
                        self.progress.phase_progress["CERTIFY"] = 0
                        
                        gap_prompt = f"""
Previous study of "{topic}" had these gaps: {gaps}
Focus area: {focus}

Re-synthesize with emphasis on filling these specific gaps.
Use the same JSON format as before.
"""
                        raw_gap = await self._think_fast(gap_prompt, json_mode=True)  # Groq: fast retry
                        try:
                            gap_structured = json.loads(raw_gap)
                            structured["concepts"].extend(gap_structured.get("concepts", []))
                            structured["critical_questions"] = gap_structured.get("critical_questions", structured["critical_questions"])
                        except:
                            pass

            if not certified:
                await progress("FAILED", score, f"Could not certify '{topic}' after {MAX_RETRY} attempts. Best: {score}/10")

        except Exception as e:
            # Catch-all for any unexpected errors not caught by per-phase handlers
            await report_crash(current_phase, e)
        finally:
            await self._close_browser()
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