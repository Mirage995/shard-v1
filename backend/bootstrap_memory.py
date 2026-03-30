"""bootstrap_memory.py -- One-shot indexer for SHARD's semantic memory.

Indexes all existing benchmark episodes and knowledge base files into
ChromaDB so semantic queries return useful results from the first run.

Usage:
    python backend/bootstrap_memory.py
    python backend/bootstrap_memory.py --verbose
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    print("[BOOTSTRAP] Starting SemanticMemory indexing...")

    try:
        from semantic_memory import get_semantic_memory
    except ImportError as e:
        print(f"[BOOTSTRAP] ERROR: cannot import semantic_memory: {e}")
        print("  Make sure sentence-transformers and chromadb are installed.")
        sys.exit(1)

    mem = get_semantic_memory()

    # Show current state before indexing
    before = mem.stats()
    print(f"[BOOTSTRAP] Before: episodes={before['episodes']}  knowledge={before['knowledge']}  errors={before['errors']}")

    # Run full index
    counts = mem.index_all(verbose=True)

    after = mem.stats()
    print(f"\n[BOOTSTRAP] After:  episodes={after['episodes']}  knowledge={after['knowledge']}  errors={after['errors']}")
    print(f"[BOOTSTRAP] Indexed this run: +{counts['episodes']} episodes  +{counts['knowledge']} knowledge  +{counts['errors']} error patterns")
    print("[BOOTSTRAP] Done.")


if __name__ == "__main__":
    main()
