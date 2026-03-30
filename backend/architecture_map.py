"""architecture_map.py -- SHARD self-model of codebase.

Loads shard_memory/architecture_map.json and exposes query methods so that
any module (SelfModel, ProactiveRefactor, future CapabilityMapper) can reason
about system structure without hardcoding module relationships.

Key methods:
    get_module(name)                  -- full module descriptor
    get_modules_by_tag(tag)           -- modules that have a capability_tag
    get_dependents(name)              -- modules that depend on a given module
    modules_for_capability(cap_tag)   -- alias for get_modules_by_tag (semantic name)
    summary()                         -- human-readable overview
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("shard.architecture_map")

_ROOT     = Path(__file__).resolve().parent.parent
_MAP_FILE = _ROOT / "shard_memory" / "architecture_map.json"


class ArchitectureMap:

    def __init__(self, map_path: Path = _MAP_FILE):
        self._path = map_path
        self._data: Dict = {}
        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self):
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
            logger.debug("[ARCH MAP] Loaded %d modules", len(self._data.get("modules", {})))
        except Exception as exc:
            logger.warning("[ARCH MAP] Could not load architecture_map.json: %s", exc)
            self._data = {"modules": {}}

    @property
    def modules(self) -> Dict:
        return self._data.get("modules", {})

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_module(self, name: str) -> Optional[Dict]:
        """Return full descriptor for a module, or None if not found."""
        return self.modules.get(name)

    def get_modules_by_tag(self, tag: str) -> List[str]:
        """Return names of all modules that have *tag* in their capability_tags."""
        tag_lower = tag.lower()
        return [
            name for name, info in self.modules.items()
            if tag_lower in [t.lower() for t in info.get("capability_tags", [])]
        ]

    def modules_for_capability(self, capability_tag: str) -> List[str]:
        """Semantic alias -- 'which modules handle this capability?'"""
        return self.get_modules_by_tag(capability_tag)

    def get_dependents(self, module_name: str) -> List[str]:
        """Return names of all modules that list *module_name* in depends_on."""
        return [
            name for name, info in self.modules.items()
            if module_name in info.get("depends_on", [])
        ]

    def get_layer(self, layer: str) -> List[str]:
        """Return all module names in a given architectural layer.

        Layers: learning, orchestration, interface, memory,
                infrastructure, self_improvement, cognition
        """
        return [
            name for name, info in self.modules.items()
            if info.get("layer") == layer
        ]

    def files_written_by(self, module_name: str) -> List[str]:
        info = self.modules.get(module_name, {})
        return info.get("writes", [])

    def files_read_by(self, module_name: str) -> List[str]:
        info = self.modules.get(module_name, {})
        return info.get("reads", [])

    # ── Self-description ──────────────────────────────────────────────────────

    def summary(self) -> str:
        """Human-readable overview for SHARD's describe() or logs."""
        layers: Dict[str, List[str]] = {}
        for name, info in self.modules.items():
            layer = info.get("layer", "unknown")
            layers.setdefault(layer, []).append(name)

        lines = [f"Architecture Map -- {len(self.modules)} modules\n"]
        for layer, names in sorted(layers.items()):
            lines.append(f"  [{layer}]  {', '.join(sorted(names))}")
        return "\n".join(lines)

    def capability_coverage(self) -> Dict[str, List[str]]:
        """Return mapping: capability_tag -> [module_names].

        Useful for debugging: shows which capabilities are covered by multiple
        modules vs single points of failure.
        """
        coverage: Dict[str, List[str]] = {}
        for name, info in self.modules.items():
            for tag in info.get("capability_tags", []):
                coverage.setdefault(tag, []).append(name)
        return coverage
