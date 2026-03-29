"""knowledge_bridge.py — Bridge between NightRunner's ChromaDB and Benchmarks.

Provides safely-wrapped access to the knowledge base for injecting context
into benchmark prompts or external analysis.

Two-tier lookup:
  1. Direct file scan of shard_workspace/knowledge_base/*.md using keyword
     matching against the query text. These are high-quality hand-crafted
     cheat sheets that contain actionable guidance. Always preferred.
  2. ChromaDB fallback for NightRunner opinions (lower quality, vague).
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger("shard.knowledge_bridge")

_ROOT = Path(__file__).resolve().parent.parent
_KB_DIR = _ROOT / "shard_workspace" / "knowledge_base"


_STOPWORDS = {
    "the", "a", "an", "in", "of", "for", "to", "and", "is", "it", "be",
    "by", "on", "at", "from", "with", "as", "or", "are", "was", "this",
    # Italian stopwords (READMEs are in Italian)
    "un", "una", "il", "la", "le", "lo", "di", "da", "del", "della",
    "non", "che", "con", "per", "ha", "sua", "suo", "dei", "gli", "ne",
    "si", "ma", "se", "ho", "ci", "al", "nel", "sul", "tra", "ogni",
    # Numbers and generic programming words
    "task", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "py", "python", "def", "class", "import", "return",
}

# ASCII-only words are English; non-ASCII are likely Italian/noise
def _is_english_word(w: str) -> bool:
    return bool(w) and w.isascii() and len(w) > 2


def _score_md_file(content: str, filename: str, task_key_words: set, full_words: set) -> float:
    """Score a markdown file by keyword overlap.

    task_key_words: high-signal English words from the task key (weight 10x)
    full_words: all query words (weight 1x for content matching)
    """
    fname_words = set(re.split(r'[\W_]+', filename.lower()))

    # Task key overlap against filename — very high weight
    task_fname_overlap = len(task_key_words & fname_words)

    # Full query overlap against filename — medium weight
    full_fname_overlap = len(full_words & fname_words)

    # Content word overlap — lower weight, only English content words
    content_words = set(w for w in re.split(r'\W+', content[:600].lower()) if _is_english_word(w))
    content_overlap = len(task_key_words & content_words)

    return task_fname_overlap * 10.0 + full_fname_overlap * 2.0 + content_overlap * 1.0


def _extract_task_key_words(query: str) -> set:
    """Extract high-signal English words from the task_key part of the query.

    Handles: "task_04_race_condition ..." → {"race", "condition"}
    """
    # First token is likely the task_key ("task_02_ghost_bug")
    first_token = query.split()[0] if query.split() else ""
    parts = re.split(r'[\W_]+', first_token.lower())
    # Remove generic prefix parts: "task", digits
    return {p for p in parts if p and not p.isdigit() and p not in _STOPWORDS and len(p) > 2}


def _query_md_files(query: str, n_results: int = 2) -> list[tuple[str, str]]:
    """Return up to n_results (filename, content) pairs ranked by relevance."""
    if not _KB_DIR.exists():
        return []

    task_key_words = _extract_task_key_words(query)
    # All English non-stopword words from the full query
    full_words = {w for w in re.split(r'\W+', query.lower())
                  if _is_english_word(w) and w not in _STOPWORDS}

    if not task_key_words and not full_words:
        return []

    scored = []
    for md_file in _KB_DIR.glob("*.md"):
        # Skip task-named files (generated from benchmark README titles — always garbage)
        if md_file.stem.startswith("task_"):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            score = _score_md_file(content, md_file.stem, task_key_words, full_words)
            if score > 0:
                scored.append((score, md_file.stem, content))
        except Exception:
            continue

    scored.sort(reverse=True)
    return [(name, content) for _, name, content in scored[:n_results]]


def query_knowledge_base(topic: str, n_results: int = 3) -> str:
    """
    Query the knowledge base for relevant concepts.

    Priority:
      1. Markdown cheat sheets in shard_workspace/knowledge_base/ (keyword match)
      2. ChromaDB NightRunner opinions (semantic similarity, fallback)

    Returns a formatted string or "" if nothing useful found.
    """
    if not topic:
        return ""

    parts: list[str] = []

    # ── Tier 1: Direct .md file lookup ────────────────────────────────────────
    try:
        md_results = _query_md_files(topic, n_results=2)
        if md_results:
            parts.append("╔═══ KNOWLEDGE BASE — Cheat Sheets ═══╗")
            parts.append("")
            for name, content in md_results:
                parts.append(f"--- {name.replace('_', ' ')} ---")
                # Include full content (these files are concise by design)
                parts.append(content.strip())
                parts.append("")
            parts.append("═" * 72)
    except Exception as e:
        logger.debug("[KnowledgeBridge] MD lookup failed: %s", e)

    # ── Tier 2: ChromaDB opinions (only if no MD matches) ─────────────────────
    if not parts:
        try:
            from db_manager import get_collection, DB_PATH_KNOWLEDGE_DB
            collection = get_collection(DB_PATH_KNOWLEDGE_DB, "shard_knowledge_base")

            count = 0
            try:
                count = collection.count()
            except Exception:
                pass

            if count > 0:
                query_text = topic.replace('\n', ' ').strip()[:500]
                actual_n = min(n_results, count)
                results = collection.query(query_texts=[query_text], n_results=actual_n)

                if results and results.get('documents') and results['documents'][0]:
                    documents = results['documents'][0]
                    parts.append("╔═══ KNOWLEDGE BASE — NightRunner Concepts ═══╗")
                    parts.append("")
                    for i, doc in enumerate(documents, 1):
                        parts.append(f"--- Concept {i} ---")
                        parts.append(doc.strip())
                        parts.append("")
                    parts.append("═" * 72)
        except Exception as e:
            logger.warning("[KnowledgeBridge] ChromaDB fallback failed: %s", e)

    return "\n".join(parts) if parts else ""
