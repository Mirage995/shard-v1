"""mock_injector.py -- Deterministic mock injection for external service dependencies.

Problem: sandbox has no Redis, Postgres, MongoDB, or live network — code that calls
these services crashes with ConnectionRefusedError before it can demonstrate logic.

Solution: detect which external libs the generated code imports, prepend minimal mocks
that satisfy the interface without requiring a real server.

Design principles:
- Static detection only (no LLM, zero cost)
- Mocks are minimal: cover the 80% common API surface, nothing else
- Idempotent: if mock already present, skip
- Fail-safe: any error returns original code unchanged
- Visible: always logs [MOCK] injected=...

Usage:
    from mock_injector import inject_mocks
    patched = inject_mocks(code, topic)

Supported:
    redis       → _MockRedis (set/get/delete/exists/hset/hget/hgetall/lpush/lrange/expire/ttl/keys/flushall)
    requests    → _MockRequests (get/post/put/delete → MockResponse)
    psycopg2    → _MockPsycopg2 (connect/cursor/execute/fetchall/fetchone/commit/close)
    pymongo     → _MockPyMongo (MongoClient → fake collection with insert/find/update/delete)
"""

import re
import logging
from typing import Set

logger = logging.getLogger("shard.mock_injector")

# ── Dependency detection map ──────────────────────────────────────────────────

_EXT_LIBS: dict[str, str] = {
    "redis":    "redis",
    "psycopg2": "postgres",
    "pymongo":  "mongodb",
    "requests": "http",
}

# ── Mock patches ──────────────────────────────────────────────────────────────

_REDIS_PATCH = '''\
class _MockRedis:
    """In-memory Redis mock for sandbox execution."""
    def __init__(self, *a, **k):
        self._store: dict = {}
        self._expiry: dict = {}
    def set(self, k, v, ex=None, px=None, **kw): self._store[str(k)] = v; return True
    def get(self, k): return self._store.get(str(k))
    def delete(self, *keys):
        for k in keys: self._store.pop(str(k), None)
        return len(keys)
    def exists(self, *keys): return sum(1 for k in keys if str(k) in self._store)
    def hset(self, name, key=None, value=None, mapping=None, **kw):
        d = self._store.setdefault(str(name), {})
        if mapping: d.update({str(k): v for k, v in mapping.items()})
        if key is not None: d[str(key)] = value
        return 1
    def hget(self, name, key): return self._store.get(str(name), {}).get(str(key))
    def hgetall(self, name): return dict(self._store.get(str(name), {}))
    def lpush(self, name, *values):
        lst = self._store.setdefault(str(name), [])
        for v in reversed(values): lst.insert(0, v)
        return len(lst)
    def lrange(self, name, start, end):
        lst = self._store.get(str(name), [])
        end = None if end == -1 else end + 1
        return lst[start:end]
    def expire(self, k, seconds): return 1
    def ttl(self, k): return -1
    def keys(self, pattern="*"): return list(self._store.keys())
    def flushall(self): self._store.clear(); return True
    def ping(self): return True
    def from_url(self, url, **kw): return self

try:
    import redis as _redis_mod
    _redis_mod.Redis = _MockRedis
    _redis_mod.StrictRedis = _MockRedis
except Exception:
    pass
'''

_REQUESTS_PATCH = '''\
class _MockResponse:
    """Minimal requests.Response mock."""
    def __init__(self, data=None, status_code=200):
        self._data = data or {}
        self.status_code = status_code
        self.text = str(data)
        self.content = str(data).encode()
        self.ok = status_code < 400
    def json(self): return self._data
    def raise_for_status(self):
        if not self.ok: raise Exception(f"HTTP {self.status_code}")

class _MockRequests:
    """Stub for requests module — returns empty 200 responses."""
    @staticmethod
    def get(url, **kw): return _MockResponse()
    @staticmethod
    def post(url, **kw): return _MockResponse()
    @staticmethod
    def put(url, **kw): return _MockResponse()
    @staticmethod
    def delete(url, **kw): return _MockResponse()

try:
    import requests as _req_mod
    _req_mod.get    = _MockRequests.get
    _req_mod.post   = _MockRequests.post
    _req_mod.put    = _MockRequests.put
    _req_mod.delete = _MockRequests.delete
except Exception:
    pass
'''

_PSYCOPG2_PATCH = '''\
class _MockCursor:
    """Minimal psycopg2 cursor mock."""
    def __init__(self): self._rows = []
    def execute(self, sql, params=None): pass
    def executemany(self, sql, seq): pass
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

class _MockPsycopg2Conn:
    def cursor(self): return _MockCursor()
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

try:
    import psycopg2 as _pg
    _pg.connect = lambda *a, **k: _MockPsycopg2Conn()
except Exception:
    pass
'''

_PYMONGO_PATCH = '''\
class _MockMongoCollection:
    def __init__(self): self._docs = []
    def insert_one(self, doc): self._docs.append(doc); return type("R",(),{"inserted_id":id(doc)})()
    def insert_many(self, docs):
        for d in docs: self._docs.append(d)
        return type("R",(),{"inserted_ids":[id(d) for d in docs]})()
    def find(self, q=None, **kw): return iter(self._docs)
    def find_one(self, q=None, **kw): return self._docs[0] if self._docs else None
    def update_one(self, q, upd, **kw): return type("R",(),{"modified_count":0})()
    def update_many(self, q, upd, **kw): return type("R",(),{"modified_count":0})()
    def delete_one(self, q, **kw): return type("R",(),{"deleted_count":0})()
    def delete_many(self, q, **kw): return type("R",(),{"deleted_count":0})()
    def count_documents(self, q=None): return len(self._docs)

class _MockMongoDB:
    def __getattr__(self, name): return _MockMongoCollection()
    def __getitem__(self, name): return _MockMongoCollection()

class _MockMongoClient:
    def __init__(self, *a, **k): pass
    def __getattr__(self, name): return _MockMongoDB()
    def __getitem__(self, name): return _MockMongoDB()
    def close(self): pass

try:
    import pymongo as _pm
    _pm.MongoClient = _MockMongoClient
except Exception:
    pass
'''

_PATCHES: dict[str, str] = {
    "redis":    _REDIS_PATCH,
    "http":     _REQUESTS_PATCH,
    "postgres": _PSYCOPG2_PATCH,
    "mongodb":  _PYMONGO_PATCH,
}

# Sentinel strings to detect already-injected mocks (idempotency guard)
_SENTINELS: dict[str, str] = {
    "redis":    "class _MockRedis",
    "http":     "class _MockRequests",
    "postgres": "class _MockPsycopg2Conn",
    "mongodb":  "class _MockMongoClient",
}

# ── Public API ────────────────────────────────────────────────────────────────

def detect_deps(code: str) -> Set[str]:
    """Return set of external service names detected in code.

    Scans for import statements and direct usage patterns.
    Returns values from _EXT_LIBS (e.g. 'redis', 'http', 'postgres', 'mongodb').
    """
    deps: Set[str] = set()
    code_lower = code.lower()
    for lib, service in _EXT_LIBS.items():
        # Match: import redis / from redis import / redis.Redis(
        if re.search(rf"\b{re.escape(lib)}\b", code_lower):
            deps.add(service)
    return deps


def inject_mocks(code: str, topic: str = "") -> str:
    """Prepend service mocks for any external dependencies detected in code.

    Args:
        code:  Generated Python code to patch.
        topic: Topic name (used only for logging).

    Returns:
        Patched code with mock stubs prepended, or original code if no deps found
        or if an error occurs.
    """
    if not code or not code.strip():
        return code

    try:
        deps = detect_deps(code)
        if not deps:
            return code

        patches = []
        injected = []

        for service in sorted(deps):
            patch = _PATCHES.get(service)
            if not patch:
                continue
            sentinel = _SENTINELS.get(service, "")
            if sentinel and sentinel in code:
                logger.debug("[MOCK] Already present, skipping: %s", service)
                continue
            patches.append(patch.strip())
            injected.append(service)

        if not patches:
            return code

        patched = "\n\n".join(patches) + "\n\n" + code
        logger.info("[MOCK] injected=%s topic='%s'", injected, topic[:60])
        return patched

    except Exception as exc:
        logger.warning("[MOCK] inject_mocks failed (returning original): %s", exc)
        return code
