"""generate_architecture_map.py — Auto-update architecture_map.json from real imports.

Usage:
    python backend/generate_architecture_map.py

What it does:
  1. Scans all .py files in backend/ and extracts their imports.
  2. Resolves which imports are internal SHARD modules (other .py files in backend/).
  3. Merges with the existing architecture_map.json:
     - Preserves all manually written fields (responsibility, layer, capability_tags, notes).
     - Overwrites `depends_on` with the live import-derived list.
     - Adds new modules not yet in the map (with placeholder fields).
  4. Writes the updated map back to shard_memory/architecture_map.json.
  5. Prints a diff summary: modules added, depends_on changes.

Run after every large refactor or new module addition.
"""
import ast
import json
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR  = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
MAP_PATH     = PROJECT_ROOT / "shard_memory" / "architecture_map.json"

# Modules to skip (not real SHARD modules)
_SKIP = {
    "__init__", "generate_architecture_map",
    "conftest", "setup", "migrate_to_sqlite",
}

# Stem prefixes that indicate generated/temp files — excluded from the map
_SKIP_PREFIXES = ("study_", "temp_", "test_", "verify_", "simulate_")

# Directories inside backend/ that contain sub-modules
_SUBPACKAGES = {"cognition"}


def _all_module_names() -> set[str]:
    """Return set of module names (stems) for all .py files in backend/."""
    names = set()
    for p in BACKEND_DIR.rglob("*.py"):
        if p.stem.startswith("_") and p.stem != "__init__":
            continue
        stem = p.stem
        if stem in _SKIP:
            continue
        if any(stem.startswith(pfx) for pfx in _SKIP_PREFIXES):
            continue
        names.add(stem)
        # Also add as subpackage.stem (e.g. cognition.self_model)
        if p.parent != BACKEND_DIR:
            rel = p.relative_to(BACKEND_DIR)
            pkg = ".".join(rel.with_suffix("").parts)
            names.add(pkg)
    return names


def _extract_imports(path: Path, known_modules: set[str]) -> list[str]:
    """Parse a .py file and return list of internal module names it imports."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []

    deps = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                stem = alias.name.split(".")[0]
                if stem in known_modules:
                    deps.add(stem)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # e.g. "from graph_rag import ..."  or "from cognition.self_model import ..."
                root = node.module.split(".")[0]
                full = node.module
                if root in known_modules:
                    deps.add(root)
                if full in known_modules:
                    deps.add(full)
    # Remove self-reference
    own = path.stem
    deps.discard(own)
    return sorted(deps)


def _load_map() -> dict:
    if MAP_PATH.exists():
        return json.loads(MAP_PATH.read_text(encoding="utf-8"))
    return {"_meta": {}, "modules": {}}


def _save_map(data: dict) -> None:
    MAP_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    known = _all_module_names()
    existing = _load_map()
    modules_map: dict = existing.get("modules", {})

    # ── Cleanup: remove auto-added entries that match skip prefixes ───────────
    removed = []
    for mod_id in list(modules_map.keys()):
        if any(mod_id.startswith(pfx.rstrip("_")) or mod_id.startswith(pfx) for pfx in _SKIP_PREFIXES):
            note = modules_map[mod_id].get("notes", "")
            if "Auto-added" in note:
                del modules_map[mod_id]
                removed.append(mod_id)

    added = []
    updated_deps = []

    for py_file in sorted(BACKEND_DIR.rglob("*.py")):
        if py_file.stem.startswith("_") or py_file.stem in _SKIP:
            continue
        if any(py_file.stem.startswith(pfx) for pfx in _SKIP_PREFIXES):
            continue
        module_id = py_file.stem
        deps = _extract_imports(py_file, known)

        if module_id not in modules_map:
            # New module — add with placeholders
            modules_map[module_id] = {
                "responsibility": f"TODO: describe {module_id}",
                "layer": "unknown",
                "depends_on": deps,
                "reads": [],
                "writes": [],
                "capability_tags": [],
                "notes": "Auto-added by generate_architecture_map.py — fill manually.",
            }
            added.append(module_id)
        else:
            # Existing module — update depends_on only
            old_deps = modules_map[module_id].get("depends_on", [])
            if sorted(old_deps) != sorted(deps):
                updated_deps.append(
                    f"  {module_id}: {sorted(old_deps)} -> {deps}"
                )
            modules_map[module_id]["depends_on"] = deps

    # Update _meta
    existing["_meta"]["generated"] = str(date.today())
    existing["_meta"]["generator"] = "generate_architecture_map.py"
    existing["_meta"]["total_modules"] = len(modules_map)
    existing["modules"] = modules_map

    _save_map(existing)

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"\n[ARCH MAP] Updated {MAP_PATH.relative_to(PROJECT_ROOT)}")
    print(f"  Total modules: {len(modules_map)}")
    if removed:
        print(f"  Cleaned up {len(removed)} auto-added generated/temp entries.")

    if added:
        print(f"\n  NEW modules added ({len(added)}) — fill manually:")
        for m in added:
            print(f"    + {m}")
    else:
        print("\n  No new modules found.")

    if updated_deps:
        print(f"\n  depends_on updated ({len(updated_deps)} modules):")
        for line in updated_deps:
            print(line)
    else:
        print("  All depends_on already up to date.")


if __name__ == "__main__":
    main()
