"""Capability Graph — Runtime representation of SHARD's operational capabilities.

Tracks what SHARD has learned to DO (not just know). Each capability has a name
and optional prerequisites. Updated automatically when strategies succeed.
Storage is in-memory (dict), not persistent — capabilities are re-derived from
strategy memory on restart if needed.
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Set

# Persist capability graph to disk for survival across restarts
CAPABILITY_FILE = os.path.join(os.path.dirname(__file__), '..', 'shard_memory', 'capability_graph.json')


class CapabilityGraph:
    def __init__(self):
        self.capabilities: Dict[str, Dict] = {}  # name -> {requires: [], acquired: timestamp, source_topic: str}
        self._load()
        print(f"[CAPABILITY] Graph initialized ({len(self.capabilities)} capabilities)")

    def _load(self):
        """Load capabilities from disk if available."""
        try:
            if os.path.exists(CAPABILITY_FILE):
                with open(CAPABILITY_FILE, 'r', encoding='utf-8') as f:
                    self.capabilities = json.load(f)
                print(f"[CAPABILITY] Loaded {len(self.capabilities)} capabilities from disk")
        except Exception as e:
            print(f"[CAPABILITY] Could not load graph: {e}")
            self.capabilities = {}

    def _save(self):
        """Persist capabilities to disk."""
        try:
            os.makedirs(os.path.dirname(CAPABILITY_FILE), exist_ok=True)
            with open(CAPABILITY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.capabilities, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CAPABILITY] Could not save graph: {e}")

    def add_capability(self, name: str, requires: Optional[List[str]] = None, source_topic: str = ""):
        """Register a new capability with optional prerequisites."""
        key = name.lower().strip()
        if key in self.capabilities:
            return  # Already known

        self.capabilities[key] = {
            "requires": requires or [],
            "acquired": datetime.now().isoformat(),
            "source_topic": source_topic,
        }
        print(f"[CAPABILITY] Added: '{name}' (requires: {requires or 'none'})")
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

    def get_all(self) -> Dict[str, Dict]:
        """Return all capabilities."""
        return dict(self.capabilities)

    def update_from_strategy(self, topic: str, strategy: str):
        """Derive and register capabilities from a successful strategy.

        Extracts capability names from the topic and strategy text.
        A successful study = SHARD can now "do" something related to that topic.
        """
        # The topic itself becomes a capability
        self.add_capability(topic, source_topic=topic)

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

        print(f"[CAPABILITY] Updated from strategy on '{topic}' — total: {len(self.capabilities)}")
