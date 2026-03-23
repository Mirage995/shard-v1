"""proactive_refactor.py — SHARD Proactive Self-Optimization Engine.

Analyzes one source file per NightRunner session using a Staff Engineer
LLM prompt, proposes patches (refactors, cleanups, token savings),
and stores them for human approval.

Gate protocol:
  1. analyze_next_file()  →  writes shard_memory/pending_patch.json if a patch found
  2. NightRunner prints [PATCH_READY] → server.py detects it, emits patch_approval_required
  3. Boss approves → POST /api/patch/approve → apply_pending_patch()
  4. Boss rejects  → POST /api/patch/reject  → discard_pending_patch()
"""
import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("shard.proactive_refactor")

# ── Project root (shard_v1/) ───────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent

# ── File rotation — one file analyzed per session, round-robin ─────────────────
REFACTOR_TARGETS: List[str] = [
    "backend/study_agent.py",
    "backend/night_runner.py",
    "backend/server.py",
    "backend/sandbox_runner.py",
    "backend/meta_learning.py",
    "backend/strategy_memory.py",
    "backend/capability_graph.py",
    "backend/consciousness.py",
    "backend/experiment_inventor.py",
    "backend/research_agenda.py",
]

# ── Persistence ────────────────────────────────────────────────────────────────
SHARD_MEMORY         = _ROOT / "shard_memory"
REFACTOR_STATE_PATH  = SHARD_MEMORY / "refactor_state.json"
PENDING_PATCH_PATH   = SHARD_MEMORY / "pending_patch.json"

# ── Hard limits ────────────────────────────────────────────────────────────────
MAX_CHANGES_PER_PATCH = 5        # No megapatches
MAX_OLD_STR_CHARS     = 2_000   # Sanity cap on each replacement string
MAX_FILE_CHARS        = 80_000  # Skip enormous files to control LLM cost


class ProactiveRefactor:
    """Picks the next file in the rotation, asks the LLM for optimizations,
    and writes a pending patch to disk for human approval.

    Args:
        think_fn: async callable(prompt: str) -> str
                  Should be a fast LLM call (e.g. study_agent._think_fast / Groq).
    """

    def __init__(self, think_fn: Callable):
        self.think_fn = think_fn
        self._state = self._load_state()

    # ── State persistence ──────────────────────────────────────────────────────

    def _load_state(self) -> Dict:
        try:
            if REFACTOR_STATE_PATH.exists():
                return json.loads(REFACTOR_STATE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[PROACTIVE] Could not load refactor_state.json: %s", exc)
        return {"current_index": 0, "history": []}

    def _save_state(self) -> None:
        try:
            SHARD_MEMORY.mkdir(parents=True, exist_ok=True)
            tmp = REFACTOR_STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(REFACTOR_STATE_PATH))
        except Exception as exc:
            logger.error("[PROACTIVE] Failed to save state: %s", exc)

    # ── Core analysis ──────────────────────────────────────────────────────────

    async def analyze_next_file(self) -> Optional[Dict]:
        """Analyze the next file in the rotation.

        Returns the validated patch dict if an optimization is found, else None.
        Side-effect: writes pending_patch.json and prints [PATCH_READY] to stdout.
        """
        n = len(REFACTOR_TARGETS)
        idx = self._state.get("current_index", 0) % n
        relative_path = REFACTOR_TARGETS[idx]
        file_path = _ROOT / relative_path

        # Advance index regardless of outcome so next session picks a fresh file
        self._state["current_index"] = (idx + 1) % n
        self._save_state()

        if not file_path.exists():
            logger.warning("[PROACTIVE] Target not found: %s — skipping.", relative_path)
            return None

        source = file_path.read_text(encoding="utf-8")
        if len(source) > MAX_FILE_CHARS:
            logger.info(
                "[PROACTIVE] %s is %d chars — too large, skipping.", relative_path, len(source)
            )
            return None

        logger.info("[PROACTIVE] Analyzing: %s", relative_path)
        raw_patch = await self._ask_llm(relative_path, source)

        if not raw_patch:
            logger.info("[PROACTIVE] No optimization found for %s.", relative_path)
            return None

        patch = self._validate_patch(raw_patch, source)
        if not patch:
            logger.info("[PROACTIVE] Patch validation failed for %s — discarding.", relative_path)
            return None

        self._store_patch(patch, relative_path)
        logger.info(
            "[PROACTIVE] Patch stored. category=%s file=%s changes=%d",
            patch.get("category"), relative_path, len(patch.get("changes", [])),
        )

        # Signal to _monitor_night_process() in server.py
        print("[PATCH_READY]", flush=True)
        return patch

    # ── LLM prompt ────────────────────────────────────────────────────────────

    async def _ask_llm(self, relative_path: str, source: str) -> Optional[Dict]:
        """Call the LLM with a Staff Engineer prompt and parse the response."""
        prompt = f"""You are a Staff Engineer doing a proactive code review on SHARD, an autonomous AI learning system.

File: {relative_path}
Language: Python

Your task: find ONE concrete optimization. Focus on:
- **performance**: algorithmic complexity (Big-O), repeated computations, expensive lookups
- **clean_code**: dead code, over-engineered logic, duplicated patterns, unnecessary abstraction
- **token_savings**: LLM prompt strings that can be shortened without losing meaning

Rules:
- If you find NOTHING meaningful, respond with exactly: null
- If you find something, respond with ONLY a JSON object — zero markdown, zero prose outside the JSON.
- Propose at most {MAX_CHANGES_PER_PATCH} changes.
- Each "old" MUST be a verbatim copy-paste substring from the file (whitespace included, must be unique).
- Keep changes surgical: replace only what truly needs changing.

Required JSON format (no markdown fences):
{{
  "description": "One sentence describing the optimization",
  "category": "performance|clean_code|token_savings",
  "rationale": "Why this matters (1 sentence, Big-O / code smell / token count)",
  "changes": [
    {{
      "old": "verbatim substring to replace",
      "new": "replacement text"
    }}
  ]
}}

SOURCE CODE:
{source[:MAX_FILE_CHARS]}"""

        try:
            raw = await self.think_fn(prompt)
        except Exception as exc:
            logger.error("[PROACTIVE] LLM call failed: %s", exc)
            return None

        raw = (raw or "").strip()

        # Strip markdown fences if the model wrapped the output
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines if not l.startswith("```")).strip()

        if raw.lower() in ("null", "none", ""):
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try to salvage a JSON object from a noisy response
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass

        logger.warning("[PROACTIVE] Could not parse LLM response as JSON.")
        return None

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_patch(self, patch: Dict, source: str) -> Optional[Dict]:
        """Validate that every 'old' string exists exactly once in the file.

        Drops ambiguous/missing/no-op changes.
        Returns None if no valid change survives.
        """
        if not isinstance(patch, dict):
            return None

        valid = []
        for change in patch.get("changes", [])[:MAX_CHANGES_PER_PATCH]:
            old = change.get("old", "")
            new = change.get("new", "")

            if not old or not isinstance(old, str) or not isinstance(new, str):
                logger.debug("[PROACTIVE] Skipping change: empty or wrong type.")
                continue
            if len(old) > MAX_OLD_STR_CHARS:
                logger.debug("[PROACTIVE] Skipping change: old string too long (%d).", len(old))
                continue
            if old == new:
                logger.debug("[PROACTIVE] Skipping no-op change.")
                continue

            count = source.count(old)
            if count == 0:
                logger.warning("[PROACTIVE] Skipping change: old string not found in file.")
                continue
            if count > 1:
                logger.warning(
                    "[PROACTIVE] Skipping change: old string appears %d times (ambiguous).", count
                )
                continue

            valid.append({"old": old, "new": new})

        if not valid:
            return None

        patch["changes"] = valid
        return patch

    # ── Patch storage ──────────────────────────────────────────────────────────

    def _store_patch(self, patch: Dict, relative_path: str) -> None:
        record = {
            "id":          str(uuid.uuid4()),
            "timestamp":   datetime.now().isoformat(),
            "type":        "refactor",
            "file":        relative_path,
            "description": patch.get("description", ""),
            "category":    patch.get("category", "clean_code"),
            "rationale":   patch.get("rationale", ""),
            "changes":     patch.get("changes", []),
            "status":      "pending",
        }
        SHARD_MEMORY.mkdir(parents=True, exist_ok=True)
        tmp = PENDING_PATCH_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(PENDING_PATCH_PATH))

    # ── Apply / Discard (called by server.py endpoints) ────────────────────────

    def apply_pending_patch(self) -> Dict:
        """Apply the stored patch to the target file. Returns {success, message}."""
        if not PENDING_PATCH_PATH.exists():
            return {"success": False, "message": "No pending patch found."}

        try:
            record = json.loads(PENDING_PATCH_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"success": False, "message": f"Cannot read patch: {exc}"}

        relative_path = record.get("file", "")
        file_path = _ROOT / relative_path

        if not file_path.exists():
            return {"success": False, "message": f"Target file not found: {relative_path}"}

        source = file_path.read_text(encoding="utf-8")

        # Create backup before touching anything
        backup = file_path.with_suffix(
            f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy2(file_path, backup)
        logger.info("[PROACTIVE] Backup: %s", backup.name)

        applied = 0
        for change in record.get("changes", []):
            old = change.get("old", "")
            new = change.get("new", "")
            if not old:
                continue
            if source.count(old) != 1:
                # Target has changed since the patch was generated → abort, restore
                shutil.copy2(backup, file_path)
                logger.error("[PROACTIVE] Apply aborted — old string no longer unique. Backup restored.")
                return {
                    "success": False,
                    "message": (
                        f"Patch no longer applies cleanly to {relative_path} "
                        "(file may have changed). Backup restored."
                    ),
                }
            source = source.replace(old, new, 1)
            applied += 1

        file_path.write_text(source, encoding="utf-8")
        logger.info("[PROACTIVE] ✅ Applied %d change(s) to %s", applied, relative_path)

        # Archive in history
        record.update({"status": "applied", "applied_at": datetime.now().isoformat(),
                        "backup": str(backup)})
        self._state.setdefault("history", []).append(record)
        self._save_state()
        PENDING_PATCH_PATH.unlink(missing_ok=True)

        return {"success": True, "message": f"Applied {applied} change(s) to {relative_path}."}

    def discard_pending_patch(self) -> Dict:
        """Discard the pending patch without applying it."""
        if not PENDING_PATCH_PATH.exists():
            return {"success": False, "message": "No pending patch found."}

        try:
            record = json.loads(PENDING_PATCH_PATH.read_text(encoding="utf-8"))
        except Exception:
            record = {}

        record.update({"status": "rejected", "rejected_at": datetime.now().isoformat()})
        self._state.setdefault("history", []).append(record)
        self._save_state()
        PENDING_PATCH_PATH.unlink(missing_ok=True)

        logger.info("[PROACTIVE] Patch rejected and discarded.")
        return {"success": True, "message": "Patch rejected."}

    # ── Static helper ──────────────────────────────────────────────────────────

    @staticmethod
    def get_pending_patch() -> Optional[Dict]:
        """Return the pending patch dict if one exists, else None."""
        if not PENDING_PATCH_PATH.exists():
            return None
        try:
            return json.loads(PENDING_PATCH_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None
