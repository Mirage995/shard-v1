"""semantic_memory.py — SemanticMemory: ChromaDB-backed long-term memory for SHARD.

This is the foundation of SHARD's path toward AGI-level scaffolding.
Instead of static keyword lookups, SHARD can now ask:
  "Have I seen something SIMILAR to this error before?"
and get semantically relevant episodes, knowledge, and patterns back.

Three collections:
  - episodes:   past benchmark runs (success/failure, what worked, what didn't)
  - knowledge:  NightRunner cheat sheets and study notes
  - errors:     recurring error patterns and their fixes

Usage:
    mem = SemanticMemory()
    mem.index_all()                          # build index from existing data
    results = mem.query("numpy truth value array ambiguous", top_k=3)
    mem.add_episode(task_key, code, error, success)
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# -- Paths ---------------------------------------------------------------------
_HERE   = Path(__file__).resolve().parent
_ROOT   = _HERE.parent
_MEMORY = _ROOT / "shard_memory"
_KB     = _ROOT / "shard_workspace" / "knowledge_base"
_DB_DIR = _MEMORY / "chromadb"

# -- ChromaDB + embeddings (lazy init) -----------------------------------------
_client     = None
_embedder   = None
_EMBED_MODEL = "all-MiniLM-L6-v2"   # 80MB, fast, good for code+text


def _get_client():
    global _client
    if _client is None:
        import chromadb
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(_DB_DIR))
    return _client


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(_EMBED_MODEL)
    return _embedder


def _embed(texts: list[str]) -> list[list[float]]:
    return _get_embedder().encode(texts, show_progress_bar=False).tolist()


# -- SemanticMemory ------------------------------------------------------------

class SemanticMemory:
    """ChromaDB-backed semantic memory for SHARD.

    Collections:
        episodes  — benchmark run history (indexed by error patterns + task)
        knowledge — NightRunner knowledge base (cheat sheets, study notes)
        errors    — recurring error fingerprints and their fixes
    """

    def __init__(self):
        c = _get_client()
        self._episodes  = c.get_or_create_collection("episodes")
        self._knowledge = c.get_or_create_collection("knowledge")
        self._errors    = c.get_or_create_collection("errors")

    # -- Query -----------------------------------------------------------------

    def query(self, text: str, top_k: int = 3,
              collections: list[str] = None) -> list[dict]:
        """Semantic search across memory collections.

        Returns list of {source, content, score, metadata} sorted by relevance.
        """
        if not text or not text.strip():
            return []

        target_cols = []
        names = collections or ["episodes", "knowledge", "errors"]
        for name in names:
            col = getattr(self, f"_{name}", None)
            if col is not None:
                target_cols.append((name, col))

        embedding = _embed([text])[0]
        results = []

        for name, col in target_cols:
            try:
                count = col.count()
                if count == 0:
                    continue
                k = min(top_k, count)
                res = col.query(query_embeddings=[embedding], n_results=k)
                for i, doc in enumerate(res["documents"][0]):
                    score = 1.0 - res["distances"][0][i]   # cosine: higher = more similar
                    meta  = res["metadatas"][0][i] if res["metadatas"] else {}
                    results.append({
                        "source":   name,
                        "content":  doc,
                        "score":    round(score, 4),
                        "metadata": meta,
                    })
            except Exception:
                continue

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def query_for_prompt(self, text: str, top_k: int = 3,
                         min_score: float = 0.35) -> str:
        """Return a formatted string ready to inject into an LLM prompt."""
        results = self.query(text, top_k=top_k)
        relevant = [r for r in results if r["score"] >= min_score]
        if not relevant:
            return ""

        parts = ["=== SEMANTIC MEMORY (similar past experience) ==="]
        for r in relevant:
            source = r["source"].upper()
            score  = r["score"]
            content = r["content"][:400]
            parts.append(f"[{source} | similarity={score}]\n{content}")

        return "\n\n".join(parts)

    # -- Indexing --------------------------------------------------------------

    def add_episode(self, task_key: str, error_summary: str, code_snippet: str,
                    success: bool, attempt: int = 1, lang: str = "python"):
        """Index a single benchmark attempt into semantic memory."""
        if not error_summary and not code_snippet:
            return

        doc_id = f"ep_{task_key}_{attempt}_{int(time.time())}"
        text = (
            f"Task: {task_key}\n"
            f"Lang: {lang}\n"
            f"Success: {success}\n"
            f"Error: {error_summary[:300]}\n"
            f"Code fragment: {code_snippet[:300]}"
        )
        meta = {
            "task":    task_key,
            "success": str(success),
            "attempt": attempt,
            "lang":    lang,
        }
        try:
            self._episodes.upsert(
                ids=[doc_id],
                embeddings=_embed([text]),
                documents=[text],
                metadatas=[meta],
            )
        except Exception:
            pass

    def add_knowledge(self, title: str, content: str, source: str = "nightrunner"):
        """Index a knowledge base entry."""
        if not content or not title:
            return
        doc_id = f"kb_{re.sub(r'[^a-z0-9]', '_', title.lower())[:60]}"
        text   = f"{title}\n\n{content[:800]}"
        meta   = {"title": title, "source": source}
        try:
            self._knowledge.upsert(
                ids=[doc_id],
                embeddings=_embed([text]),
                documents=[text],
                metadatas=[meta],
            )
        except Exception:
            pass

    def add_error_pattern(self, error_text: str, fix: str, lang: str = "python"):
        """Index a recurring error pattern and its fix."""
        if not error_text:
            return
        doc_id = f"err_{re.sub(r'[^a-z0-9]', '_', error_text[:40].lower())}"
        text   = f"Error: {error_text[:300]}\nFix: {fix[:300]}"
        meta   = {"lang": lang}
        try:
            self._errors.upsert(
                ids=[doc_id],
                embeddings=_embed([text]),
                documents=[text],
                metadatas=[meta],
            )
        except Exception:
            pass

    # -- Bulk indexing from existing SHARD data --------------------------------

    def index_all(self, verbose: bool = True) -> dict:
        """Index all existing SHARD data into semantic memory.

        Reads:
          - shard_memory/benchmark_episodes.json
          - shard_workspace/knowledge_base/*.md
        Returns counts of items indexed.
        """
        counts = {"episodes": 0, "knowledge": 0, "errors": 0}

        # 1. Benchmark episodes
        ep_path = _MEMORY / "benchmark_episodes.json"
        if ep_path.exists():
            try:
                data = json.loads(ep_path.read_text(encoding="utf-8"))
                for task_key, sessions in data.items():
                    if not isinstance(sessions, list):
                        continue
                    for session in sessions:
                        attempts = session.get("attempts", [])
                        for att in attempts:
                            err = att.get("error_summary", "")
                            code = att.get("code", "")[:300]
                            success = session.get("success", False)
                            attempt_num = att.get("attempt", 1)
                            if err or code:
                                self.add_episode(
                                    task_key=task_key,
                                    error_summary=err,
                                    code_snippet=code,
                                    success=success,
                                    attempt=attempt_num,
                                )
                                counts["episodes"] += 1
                if verbose:
                    print(f"  [semantic_memory] Indexed {counts['episodes']} episodes")
            except Exception as e:
                if verbose:
                    print(f"  [semantic_memory] Episodes index failed: {e}")

        # 2. Knowledge base markdown files
        if _KB.exists():
            for md_file in _KB.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    title   = md_file.stem.replace("_", " ")
                    self.add_knowledge(title=title, content=content)
                    counts["knowledge"] += 1
                except Exception:
                    continue
            if verbose:
                print(f"  [semantic_memory] Indexed {counts['knowledge']} knowledge files")

        # 3. Extract error patterns from episodes (errors that appear multiple times)
        ep_path2 = _MEMORY / "benchmark_episodes.json"
        if ep_path2.exists():
            try:
                data = json.loads(ep_path2.read_text(encoding="utf-8"))
                error_map: dict[str, list] = {}
                for task_key, sessions in data.items():
                    if not isinstance(sessions, list):
                        continue
                    for session in sessions:
                        for att in session.get("attempts", []):
                            err = att.get("error_summary", "").strip()
                            if len(err) > 20:
                                # Normalize to first 80 chars as fingerprint
                                fp = err[:80]
                                error_map.setdefault(fp, []).append(
                                    att.get("code", "")[:200]
                                )
                # Index errors that appeared at least twice
                for err_fp, codes in error_map.items():
                    if len(codes) >= 2:
                        fix_hint = codes[-1] if codes else ""
                        self.add_error_pattern(err_fp, fix_hint)
                        counts["errors"] += 1
                if verbose:
                    print(f"  [semantic_memory] Indexed {counts['errors']} recurring error patterns")
            except Exception as e:
                if verbose:
                    print(f"  [semantic_memory] Error patterns index failed: {e}")

        return counts

    # -- Stats -----------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "episodes":  self._episodes.count(),
            "knowledge": self._knowledge.count(),
            "errors":    self._errors.count(),
        }

    # ── Shared environment interface ───────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to environment events broadcast by CognitionCore.

        SemanticMemory is the memory layer — it indexes knowledge and errors
        as they are produced by other modules.
        """
        if event_type == "skill_certified":
            # Another module certified a skill — index it so future queries find it
            topic = data.get("topic", "")
            score = data.get("score", 0.0)
            if topic:
                try:
                    self.add_knowledge(
                        title=topic,
                        content=f"Skill certified with score {score:.1f}/10. Source: {source}.",
                        source="cognition_event",
                    )
                except Exception:
                    pass

        elif event_type == "frustration_peak":
            # A topic is chronically failing — query for similar past solutions
            # and store as an error pattern hint for future study cycles
            topic = data.get("topic", "")
            hits = data.get("hits", 0)
            if topic:
                try:
                    self.add_error_pattern(
                        error_text=f"Chronic failure on topic: {topic} ({hits} failed attempts)",
                        fix=f"Topic '{topic}' has failed {hits} times. Consider decomposing or changing approach.",
                        lang="python",
                    )
                except Exception:
                    pass


# -- Module-level singleton ----------------------------------------------------

_instance: Optional[SemanticMemory] = None

def get_semantic_memory() -> SemanticMemory:
    """Return the module-level singleton, initializing on first call."""
    global _instance
    if _instance is None:
        _instance = SemanticMemory()
    return _instance


def query_semantic_memory(text: str, top_k: int = 3,
                          min_score: float = 0.35) -> str:
    """Convenience function for prompt injection — safe to call from anywhere."""
    try:
        return get_semantic_memory().query_for_prompt(text, top_k=top_k, min_score=min_score)
    except Exception as e:
        return ""
