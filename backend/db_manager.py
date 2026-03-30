"""ChromaDB Singleton Manager -- Fase 1 SSJ3: Core Hardening.

Garantisce un solo PersistentClient per path database in tutto SHARD.
Elimina la lock contention su SQLite (critica su Windows) causata da
client multipli che aprono lo stesso file .sqlite3 simultaneamente.

Usage:
    from db_manager import get_client, get_collection, DB_PATH_SHARD_MEMORY

    # Ottieni il client singleton per un path
    client = get_client(DB_PATH_SHARD_MEMORY)

    # Oppure direttamente una collection (shortcut)
    col = get_collection(DB_PATH_SHARD_MEMORY, "conversations",
                         metadata={"description": "Chat history"})

Path constants (importa da qui -- non ridefinire altrove):
    DB_PATH_SHARD_MEMORY  -- shard_v1/shard_memory/
    DB_PATH_STRATEGY_DB   -- shard_v1/shard_memory/strategy_db/
    DB_PATH_KNOWLEDGE_DB  -- shard_v1/knowledge_db/
"""

import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional

import chromadb

logger = logging.getLogger("shard.db_manager")

# ── Canonical path constants ──────────────────────────────────────────────────
# Tutte le path ChromaDB di SHARD sono definite qui una sola volta.
# I moduli importano queste costanti invece di ricalcolare i path localmente.

_BACKEND_DIR = Path(__file__).parent.resolve()
_ROOT_DIR    = _BACKEND_DIR.parent.resolve()

DB_PATH_SHARD_MEMORY: str = str(_ROOT_DIR / "shard_memory")
DB_PATH_STRATEGY_DB:  str = str(_ROOT_DIR / "shard_memory" / "strategy_db")
DB_PATH_KNOWLEDGE_DB: str = str(_ROOT_DIR / "knowledge_db")


# ── Singleton registry ────────────────────────────────────────────────────────

_registry_lock: threading.Lock = threading.Lock()
_clients: Dict[str, chromadb.PersistentClient] = {}


def get_client(db_path: str) -> chromadb.PersistentClient:
    """Restituisce il PersistentClient singleton per il path dato.

    Alla prima chiamata crea il client e lo memorizza in cache.
    Chiamate successive restituiscono l'istanza già esistente.
    Thread-safe tramite double-checked locking.

    Args:
        db_path: Path assoluto o relativo alla directory del database.
                 Viene normalizzato a path assoluto prima del lookup.
    """
    normalized = str(Path(db_path).resolve())

    # Fast path: client già creato (no lock)
    if normalized in _clients:
        return _clients[normalized]

    # Slow path: creazione con lock
    with _registry_lock:
        if normalized not in _clients:
            os.makedirs(normalized, exist_ok=True)
            logger.info("[DB_MANAGER] Inizializzazione PersistentClient: %s", normalized)
            _clients[normalized] = chromadb.PersistentClient(path=normalized)
            logger.info("[DB_MANAGER] Client registrato. Totale client attivi: %d", len(_clients))
        return _clients[normalized]


def get_collection(
    db_path: str,
    name: str,
    metadata: Optional[dict] = None,
    embedding_function=None,
) -> chromadb.Collection:
    """Shortcut: get_or_create una collection dal client singleton.

    Args:
        db_path:            Path al database (usa le costanti DB_PATH_*).
        name:               Nome della collection.
        metadata:           Metadata opzionali per la collection.
        embedding_function: Embedding function opzionale (es. DefaultEmbeddingFunction).
    """
    client = get_client(db_path)
    kwargs: dict = {"name": name}
    if metadata:
        kwargs["metadata"] = metadata
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    return client.get_or_create_collection(**kwargs)


def get_registry_info() -> Dict[str, int]:
    """Diagnostica: restituisce i path registrati e il numero di collection per ognuno.

    Utile per health check e logging. Non blocca l'event loop.
    """
    info = {}
    for path, client in _clients.items():
        try:
            info[path] = len(client.list_collections())
        except Exception:
            info[path] = -1
    return info
