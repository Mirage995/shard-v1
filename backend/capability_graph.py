"""Capability Graph -- Runtime representation of SHARD's operational capabilities.

Tracks what SHARD has learned to DO (not just know). Each capability has a name
and optional prerequisites. Updated automatically when strategies succeed.
Storage is in-memory (dict), not persistent -- capabilities are re-derived from
strategy memory on restart if needed.
"""
import asyncio
import json
import logging
import os
import re
import heapq
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Callable, Set, Any, Tuple

logger = logging.getLogger("shard.capability_graph")

# Persist capability graph to disk for survival across restarts
CAPABILITY_FILE = os.path.join(os.path.dirname(__file__), '..', 'shard_memory', 'capability_graph.json')


def _get_db():
    """Lazy import to avoid circular deps at module load time."""
    from shard_db import get_db
    return get_db()

# ── Capability Normalization ──────────────────────────────────────────────────
# Composite topic templates that should be split into atomic skill names.
# "Integration of asyncio and Playwright" -> ["asyncio", "playwright"]
# "X applied to Y" -> ["X", "Y"]
_NORMALIZE_PATTERNS = [
    (r'^integration of (.+?) and (.+)$',  2),
    (r'^(.+?) applied to (.+)$',          2),
    (r'^combining (.+?) and (.+)$',       2),
    (r'^using (.+?) with (.+)$',          2),
    (r'^integration of (.+)$',            1),
]

def normalize_capability(topic: str) -> List[str]:
    """Extract atomic capability names from composite topic strings.

    Returns a list with 1+ names:
      - If the topic matches a template (e.g. "Integration of X and Y"),
        returns the atomic parts ["x", "y"].
      - Otherwise returns [topic] unchanged.

    This prevents capability graph entropy from template-generated topics.
    """
    t = topic.strip()
    t_lower = t.lower()
    for pattern, ngroups in _NORMALIZE_PATTERNS:
        m = re.match(pattern, t_lower, re.IGNORECASE)
        if m:
            parts = [m.group(i + 1).strip() for i in range(ngroups)]
            # Keep only parts with enough substance
            valid = [p for p in parts if len(p) >= 4]
            if valid:
                logger.debug("[CAPABILITY] Normalized '%s' -> %s", topic, valid)
                return valid
    return [t]


# ── Capability Contamination Filter ───────────────────────────────────────────
BAD_CAPABILITY_TOKENS = {
    "chiedo", "facendo", "presente", "present", "silenzio",
    "integrazione", "dispositivo", "alleanza", "alliance",
    "esempio", "example", "cosa", "thing", "which", "come"
}

def valid_capability(name: str) -> bool:
    """Filter out non-technical garbage capabilities that contaminate recombination."""
    words = name.lower().split()
    
    # Check for bad tokens in any word
    for w in words:
        if w in BAD_CAPABILITY_TOKENS:
            return False
    
    return True

_GENERIC_SKILLS = {
    "ai", "quantum", "cryptography", "security", "algorithm", "data",
}


class CapabilityGraph:
    def __init__(self):
        # listeners called when a new capability is registered
        self._capability_listeners: List[Callable[[Dict[str, Any]], None]] = []
        # key -> {requires: [...], acquired: timestamp, source_topic: str}
        self.capabilities: Dict[str, Dict[str, object]] = {}
        # Concurrency: one writer at a time (NightRunner vs audio session)
        self._lock = asyncio.Lock()
        # Dirty-flag: batch disk writes instead of one per add_capability
        self._dirty = False
        self._load()
        logger.info("[CAPABILITY] Graph initialized (%d capabilities)", len(self.capabilities))

    # ------------------------------------------------------------------
    # Listener API
    # ------------------------------------------------------------------

    def register_capability_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callable that will be invoked with an event dict
        when a new capability is added.
        """
        if listener not in self._capability_listeners:
            self._capability_listeners.append(listener)

    def _load(self):
        """Load capabilities from SQLite, fallback to JSON."""
        try:
            conn = _get_db()
            rows = conn.execute(
                "SELECT id, name, source_topic, acquired_at FROM capabilities"
            ).fetchall()
            if rows:
                caps = {}
                for r in rows:
                    # Load dependencies for this capability
                    deps = conn.execute(
                        "SELECT requires_name FROM capability_deps WHERE capability_id = ?",
                        (r["id"],)
                    ).fetchall()
                    caps[r["name"]] = {
                        "requires": [d["requires_name"] for d in deps],
                        "acquired": r["acquired_at"],
                        "source_topic": r["source_topic"] or "",
                    }
                # Apply contamination filter
                filtered = {k: v for k, v in caps.items() if valid_capability(k)}
                filtered_count = len(caps) - len(filtered)
                if filtered_count > 0:
                    print(f"[CAPABILITY] Filtered out {filtered_count} contaminated capabilities")
                self.capabilities = filtered
                print(f"[DB] Loaded {len(self.capabilities)} capabilities from SQLite")
                return
        except Exception as e:
            logger.warning("[DB] Capability SQLite load failed (%s), falling back to JSON", e)

        # Fallback: legacy JSON
        try:
            if os.path.exists(CAPABILITY_FILE):
                with open(CAPABILITY_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                filtered = {k: v for k, v in loaded.items() if valid_capability(k)}
                filtered_count = len(loaded) - len(filtered)
                if filtered_count > 0:
                    print(f"[CAPABILITY] Filtered out {filtered_count} contaminated capabilities")
                self.capabilities = filtered
                print(f"[CAPABILITY] Loaded {len(self.capabilities)} capabilities from JSON fallback")
        except Exception as e:
            print(f"[CAPABILITY] Could not load graph: {e}")
            self.capabilities = {}

    def _save(self):
        """Persist capability to SQLite (INSERT OR IGNORE).

        Also writes to JSON as backup for now.
        """
        # Write to SQLite
        try:
            conn = _get_db()
            for name, meta in self.capabilities.items():
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO capabilities (name, source_topic, acquired_at) VALUES (?, ?, ?)",
                    (name, meta.get("source_topic", ""), meta.get("acquired", datetime.now().isoformat())),
                )
                if cursor.rowcount > 0:
                    # New capability -- insert deps too
                    cap_id = cursor.lastrowid
                    for req in meta.get("requires", []):
                        conn.execute(
                            "INSERT OR IGNORE INTO capability_deps (capability_id, requires_name) VALUES (?, ?)",
                            (cap_id, req.lower().strip()),
                        )
            conn.commit()
            self._dirty = False
            logger.info("[DB] Capabilities saved to SQLite (%d total)", len(self.capabilities))
        except Exception as e:
            logger.error("[DB] Capability SQLite save failed: %s", e)

        # Also write JSON backup (will be removed in future)
        try:
            target = os.path.realpath(CAPABILITY_FILE)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            dir_ = os.path.dirname(target)
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8',
                dir=dir_, suffix='.tmp', delete=False
            ) as tf:
                json.dump(self.capabilities, tf, indent=2, ensure_ascii=False)
                tmp_path = tf.name
            os.replace(tmp_path, target)
        except Exception as e:
            logger.warning("[CAPABILITY] JSON backup write failed: %s", e)

    def add_capability(self, name: str, requires: Optional[List[str]] = None, source_topic: str = ""):
        """Register a new capability with optional prerequisites.

        Thread-safe via asyncio.Lock.  Disk write is deferred: the in-memory
        dict is updated immediately; _save() is marked dirty and the caller
        should flush via flush() or the background save task.
        """
        key = name.lower().strip()
        if key in self.capabilities:
            return  # Already known

        # Contamination filter
        if not valid_capability(key):
            logger.debug("[CAPABILITY] Rejected contaminated capability: '%s'", name)
            return

        if len(key) < 3 or key in _GENERIC_SKILLS:
            logger.debug("[CAPABILITY] Skipped generic/short skill: '%s'", name)
            return

        # Single-word check (no underscore = not a compound snake_case skill)
        words = key.split()
        if len(words) == 1 and '_' not in key:
            logger.debug("[CAPABILITY] Rejected bare single-word capability: '%s'", name)
            return

        # Reject degenerate recursive compounds (e.g. "X applied to Y applied to Z")
        if key.count(' applied to ') >= 2:
            logger.debug("[CAPABILITY] Rejected recursive compound capability: '%s'", name)
            return

        reqs = [r.lower().strip() for r in (requires or [])]
        self.capabilities[key] = {
            "requires": reqs,
            "acquired": datetime.now().isoformat(),
            "source_topic": source_topic,
        }
        self._dirty = True
        logger.info("[CAPABILITY] Added: '%s' (requires: %s)", name, reqs or 'none')

        # Flush to disk immediately after each add so crashes lose at most one entry
        self._save()

        # Notify listeners -- iterate over snapshot to avoid mutation during iteration
        event = {
            "name": key,
            "source_topic": source_topic,
            "timestamp": self.capabilities[key]["acquired"],
        }
        for listener in list(self._capability_listeners):
            try:
                listener(event)
            except TypeError as e:
                if "positional argument" in str(e):
                    try:
                        listener(event["name"])
                    except Exception as inner:
                        logger.warning("[CAPABILITY] Listener fallback error: %s", inner)
                else:
                    logger.warning("[CAPABILITY] Listener error: %s", e)
            except Exception as e:
                logger.warning("[CAPABILITY] Listener error: %s", e)

    async def add_capability_async(self, name: str, requires: Optional[List[str]] = None, source_topic: str = ""):
        """Async-safe wrapper: acquires the lock before mutating shared state.

        Use this from coroutines (NightRunner, SessionOrchestrator) to prevent
        concurrent writes from NightRunner and the audio session overwriting each other.
        """
        async with self._lock:
            self.add_capability(name, requires=requires, source_topic=source_topic)

    def flush(self):
        """Force a disk write if the graph has been modified since the last save."""
        if self._dirty:
            self._save()

    def has_capability(self, name: str) -> bool:
        """Check if SHARD has a specific capability."""
        return name.lower().strip() in self.capabilities

    def missing_requirements(self, name: str) -> List[str]:
        """Return list of unmet prerequisites for a capability."""
        key = name.lower().strip()
        if key not in self.capabilities:
            return [name]  # The capability itself is missing

        requires = self.capabilities[key].get("requires", [])
        return [r for r in requires if r.lower().strip() not in self.capabilities]

    def get_all(self) -> Dict[str, Dict[str, object]]:
        """Return all capabilities."""
        return dict(self.capabilities)

    def get_all_skills(self) -> List[str]:
        """Return all skill names for self-model aggregation."""
        return sorted(list(self.capabilities.keys()))

    def get_certified_skills(self) -> List[str]:
        """Return skills considered certified (currently all acquired capabilities)."""
        return self.get_all_skills()

    def get_recent_capabilities(self, n: int = 10) -> List[str]:
        """Return the n most recently added capability names.

        Uses the stored timestamp rather than relying on dict order.
        """
        items = sorted(
            self.capabilities.items(),
            key=lambda x: datetime.fromisoformat(x[1].get("acquired", ""))
        )
        return [k for k, _ in items[-n:]]

    def get_capabilities_summary(self) -> Dict:
        """Return a summary of total and recent capabilities."""
        print("[CAPABILITY] Summary requested")
        return {
            "total_capabilities": len(self.capabilities),
            "recent": self.get_recent_capabilities(),
        }

    def update_from_strategy(self, topic: str, strategy: str):
        """Derive and register capabilities from a successful strategy.

        Extracts capability names from the topic and strategy text.
        A successful study = SHARD can now "do" something related to that topic.
        NOTE: use update_from_strategy_async from coroutines to stay lock-safe.
        """
        # Normalize composite topics into atomic capabilities before storing
        for atomic in normalize_capability(topic):
            self.add_capability(atomic, source_topic=topic)

        # Extract sub-capabilities from strategy text
        # Look for "Concepts: x, y, z" pattern
        if "Concepts:" in strategy:
            try:
                concepts_part = strategy.split("Concepts:")[1].split("|")[0].strip()
                concepts = [c.strip() for c in concepts_part.split(",") if c.strip()]
                for concept in concepts[:5]:  # Cap to avoid noise
                    self.add_capability(concept, requires=[topic], source_topic=topic)
            except (IndexError, ValueError):
                pass

        print(f"[CAPABILITY] Updated from strategy on '{topic}' -- total: {len(self.capabilities)}")

    async def update_from_strategy_async(self, topic: str, strategy: str):
        """Async-safe version of update_from_strategy.

        Each add_capability_async call acquires/releases the lock independently,
        keeping concurrent NightRunner and SessionOrchestrator writes serialised.
        """
        for atomic in normalize_capability(topic):
            await self.add_capability_async(atomic, source_topic=topic)

        if "Concepts:" in strategy:
            try:
                concepts_part = strategy.split("Concepts:")[1].split("|")[0].strip()
                concepts = [c.strip() for c in concepts_part.split(",") if c.strip()]
                for concept in concepts[:5]:
                    await self.add_capability_async(concept, requires=[topic], source_topic=topic)
            except (IndexError, ValueError):
                pass

        logger.info("[CAPABILITY] Updated from strategy on '%s' -- total: %d", topic, len(self.capabilities))

    def resolve_dependencies(self, capability_name: str) -> List[str]:
        """Return all recursive dependencies for a capability, avoiding cycles."""
        key = capability_name.lower().strip()
        visited = set()
        dependencies = []
        
        def _resolve(cap):
            if cap in visited:
                return  # Avoid cycles
            visited.add(cap)
            if cap in self.capabilities:
                requires = self.capabilities[cap].get("requires", [])
                for req in requires:
                    _resolve(req.lower().strip())
                    if req.lower().strip() not in dependencies:
                        dependencies.append(req.lower().strip())
        
        _resolve(key)
        return dependencies

    def suggest_learning_path(self, capability_name: str) -> List[str]:
        """Return the correct learning order for a capability, excluding already acquired ones.
        
        Uses topological sort with heapq for deterministic ordering.
        """
        key = capability_name.lower().strip()
        all_deps = self.resolve_dependencies(key)
        
        # Include the target capability if not acquired
        if key not in self.capabilities:
            all_deps.append(key)
        
        # Filter out already acquired capabilities
        to_learn = [cap for cap in all_deps if cap not in self.capabilities]
        
        if not to_learn:
            return []
        
        # Build graph: cap -> list of capabilities that require it (reverse dependencies)
        graph = {cap: [] for cap in to_learn}
        indegree = {cap: 0 for cap in to_learn}
        
        # For each cap, find what requires it among to_learn
        for cap in to_learn:
            if cap in self.capabilities:
                requires = self.capabilities[cap].get("requires", [])
                for req in requires:
                    req_key = req.lower().strip()
                    if req_key in to_learn:
                        graph[req_key].append(cap)
                        indegree[cap] += 1
        
        # Topological sort using Kahn's algorithm with heapq for deterministic ordering
        heap = []
        for cap in to_learn:
            if indegree[cap] == 0:
                heapq.heappush(heap, cap)  # heappush sorts lexicographically
        
        result = []
        
        while heap:
            current = heapq.heappop(heap)
            result.append(current)
            
            for dependent in graph[current]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(heap, dependent)
        
        # Check for cycles (if not all nodes processed)
        if len(result) != len(to_learn):
            # Fallback to simple sort if cycle detected
            return sorted(to_learn, key=lambda x: len(self.capabilities.get(x, {}).get("requires", [])))
        
        return result

    def get_frontier_capabilities(self) -> List[str]:
        """Return capabilities that are not yet acquired but have at least one satisfied prerequisite."""
        frontier = set()
        
        # Find all potential capabilities (prerequisites of acquired ones)
        for cap_data in self.capabilities.values():
            for req in cap_data.get("requires", []):
                req_key = req.lower().strip()
                if req_key not in self.capabilities:
                    frontier.add(req_key)
        
        # Filter to those with at least one satisfied prerequisite
        result = []
        for cap in frontier:
            # Check if any of its prerequisites are satisfied
            # Since we don't have the requires for non-acquired caps, 
            # we assume they are frontier if they are prerequisites of acquired caps
            # For a more sophisticated check, we'd need to know their requires
            # For now, return all potential frontier capabilities
            result.append(cap)
        
        return result

    def get_learning_path_with_difficulty(self, capability_name: str) -> List[Tuple[str, int]]:
        """Return learning path with depth/difficulty for each capability.
        
        Returns list of (capability, difficulty) tuples where difficulty is the
        depth in the dependency graph (0 = foundational, higher = more advanced).
        """
        key = capability_name.lower().strip()
        learning_path = self.suggest_learning_path(key)
        
        if not learning_path:
            return []
        
        # Build graph to compute depths
        graph = {cap: [] for cap in learning_path}
        indegree = {cap: 0 for cap in learning_path}
        depth_map = {cap: 0 for cap in learning_path}
        
        for cap in learning_path:
            if cap in self.capabilities:
                requires = self.capabilities[cap].get("requires", [])
                for req in requires:
                    req_key = req.lower().strip()
                    if req_key in learning_path:
                        graph[req_key].append(cap)
                        indegree[cap] += 1
        
        # Compute depths using topological traversal
        heap = [cap for cap in learning_path if indegree[cap] == 0]
        heapq.heapify(heap)
        processed = 0
        
        while heap:
            current = heapq.heappop(heap)
            processed += 1
            
            for dependent in graph[current]:
                depth_map[dependent] = max(depth_map[dependent], depth_map[current] + 1)
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(heap, dependent)
        
        # Return as list of (capability, difficulty) tuples
        return [(cap, depth_map[cap]) for cap in learning_path]

    def get_frontier_by_difficulty(self, max_depth: Optional[int] = None) -> List[str]:
        """Return unacquired capabilities at difficulty ≤ max_depth + 1."""
        if max_depth is None:
            max_depth = self.get_max_acquired_depth()
        
        frontier = self.get_frontier_capabilities()
        return frontier

    def get_difficulty_map(self) -> Dict[int, List[str]]:
        """Return capabilities grouped by difficulty level for UI rendering."""
        difficulty_groups: Dict[int, List[str]] = {}
        
        for cap in self.capabilities.keys():
            max_level = 0
            requires = self.capabilities[cap].get("requires", [])
            if requires:
                for req in requires:
                    req_key = req.lower().strip()
                    if req_key in self.capabilities:
                        req_deps = self.resolve_dependencies(req_key)
                        max_level = max(max_level, len(req_deps) + 1)
            
            if max_level not in difficulty_groups:
                difficulty_groups[max_level] = []
            difficulty_groups[max_level].append(cap)
        
        return difficulty_groups

    def get_max_acquired_depth(self) -> int:
        """Return the maximum depth/difficulty of acquired capabilities."""
        if not self.capabilities:
            return 0
        
        max_depth = 0
        for cap in self.capabilities.keys():
            deps = self.resolve_dependencies(cap)
            max_depth = max(max_depth, len(deps))
        
        return max_depth

    # ── Shared environment interface ───────────────────────────────────────────

    def on_event(self, event_type: str, data: dict, source: str = "") -> None:
        """React to CognitionCore environment events.

        CapabilityGraph is the skill ledger -- it registers new capabilities
        when skills are certified and marks progress for GoalEngine.
        """
        if event_type == "skill_certified":
            topic = data.get("topic", "")
            if topic:
                try:
                    for atomic in normalize_capability(topic):
                        self.add_capability(atomic, source_topic=topic)
                    self.flush()
                except Exception:
                    pass
