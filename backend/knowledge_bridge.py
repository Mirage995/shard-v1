"""knowledge_bridge.py — Bridge between NightRunner's ChromaDB and Benchmarks.

Provides safely-wrapped access to the knowledge base for injecting context
into benchmark prompts or external analysis.
"""
import logging
import os
from pathlib import Path

# Dual import path support common in this repo
try:
    from db_manager import get_collection, DB_PATH_KNOWLEDGE_DB
except ImportError:
    from backend.db_manager import get_collection, DB_PATH_KNOWLEDGE_DB

logger = logging.getLogger("shard.knowledge_bridge")


def query_knowledge_base(topic: str, n_results: int = 3) -> str:
    """
    Query NightRunner's ChromaDB knowledge base for relevant concepts.
    
    Args:
        topic: The search query text (e.g., from README or task description).
        n_results: Max number of documents to return.
        
    Returns:
        A formatted string starting with ╔═══ KNOWLEDGE BASE ═══╗
        Returns an empty string ("") if the collection is empty, missing, or on error.
    """
    if not topic:
        return ""
        
    try:
        # get_collection returns get_or_create_collection, preventing immediate crash
        collection = get_collection(DB_PATH_KNOWLEDGE_DB, "shard_knowledge_base")
        
        # Safe count check — ChromaDB client usually supports count()
        try:
            if collection.count() == 0:
                # empty
                return ""
        except Exception:
            # If count fails, we can still try to query, or it might mean it's empty/uninitialized
            pass

        # Clean query text
        query_text = topic.replace('\n', ' ').strip()
        if len(query_text) > 500:
            query_text = query_text[:500]  # Avoid overly long query text bloating RAM or API limits

        # Cap n_results to actual collection size (ChromaDB throws if n > count)
        actual_n = min(n_results, max(1, collection.count()))
        results = collection.query(
            query_texts=[query_text],
            n_results=actual_n
        )
        
        if not results or not results.get('documents') or not results['documents'][0]:
            return ""
            
        documents = results['documents'][0]
        
        formatted = [
            "╔═══ KNOWLEDGE BASE — Relevant Concepts from NightRunner ═══╗",
            "║  NightRunner has studied similar topics. Review this context. ║",
            "╚═════════════════════════════════════════════════════════════╝",
            ""
        ]
        
        for i, doc in enumerate(documents, 1):
            formatted.append(f"--- Document {i} ---")
            formatted.append(doc.strip())
            formatted.append("")
            
        formatted.append("═" * 72)
        return "\n".join(formatted)
        
    except Exception as e:
        # Strictly safe fallback — never crash the caller
        logger.warning(f"[KnowledgeBridge] Error querying KB: {e}")
        return ""
