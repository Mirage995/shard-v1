"""
vision.py — SHARD Vision Layer.

Maintains a persistent narrative statement and focus domains that shape
autonomous goal generation. Updated by certified topics, momentum shifts,
and frustration patterns. Read by GoalEngine to bias topic selection.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VISION_PATH = _REPO_ROOT / "shard_memory" / "vision.json"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_VISION: dict = {
    "statement": (
        "SHARD seeks to become a reliable autonomous problem-solver — "
        "mastering software engineering fundamentals, building robust reasoning, "
        "and compounding knowledge session by session."
    ),
    "focus_domains": ["algorithms", "debugging", "code quality", "performance"],
    "avoid_domains": [],
    "certified_count": 0,
    "frustration_topics": [],
    "last_updated": "",
    "update_log": [],
}

_MAX_LOG = 30
_MAX_FRUSTRATION = 20
_MAX_AVOID = 10

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        Path(tmp).replace(path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _safe_load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "statement" in data:
            return data
    except Exception:
        pass
    return dict(_DEFAULT_VISION)


# ---------------------------------------------------------------------------
# VisionEngine
# ---------------------------------------------------------------------------


class VisionEngine:
    """
    Persistent narrative goal layer for SHARD.

    Stores a high-level mission statement and a list of focus domains.
    Other modules (GoalEngine, ImprovementEngine) read these to bias
    autonomous decision-making.
    """

    def __init__(self, vision_path: Path = _VISION_PATH) -> None:
        self._path = vision_path
        self._v: dict = dict(_DEFAULT_VISION)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, vision_path: Path = _VISION_PATH) -> "VisionEngine":
        ve = cls(vision_path=vision_path)
        ve._v = _safe_load(vision_path)
        return ve

    def save(self) -> bool:
        try:
            _atomic_write(self._path, self._v)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Read API (used by GoalEngine / NightRunner)
    # ------------------------------------------------------------------

    @property
    def statement(self) -> str:
        return self._v.get("statement", _DEFAULT_VISION["statement"])

    @property
    def focus_domains(self) -> list[str]:
        return list(self._v.get("focus_domains", _DEFAULT_VISION["focus_domains"]))

    @property
    def avoid_domains(self) -> list[str]:
        return list(self._v.get("avoid_domains", []))

    def get_prompt_block(self) -> str:
        """
        Return a compact string for injection into NightRunner's system prompt.

        Example output:
            [SHARD Vision]
            Mission: SHARD seeks to become ...
            Focus: algorithms, debugging, code quality, performance
            Avoid: recursion (chronic failure)
        """
        lines = [
            "[SHARD Vision]",
            f"Mission: {self.statement}",
        ]
        if self.focus_domains:
            lines.append(f"Focus: {', '.join(self.focus_domains)}")
        if self.avoid_domains:
            lines.append(f"Avoid (struggle areas): {', '.join(self.avoid_domains)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Write API (called from NightRunner / CognitionCore events)
    # ------------------------------------------------------------------

    def record_certified(self, topic: str, score: float) -> None:
        """Called when a skill is certified. Reinforces focus domains."""
        count = self._v.get("certified_count", 0) + 1
        self._v["certified_count"] = count

        # Every 5 certifications, refresh the statement to reflect growth
        if count % 5 == 0:
            self._refresh_statement(count)

        self._log(f"certified: {topic} (score={score:.1f})")
        self.save()

    def record_frustration(self, topic: str, hits: int) -> None:
        """
        Called when a topic triggers chronic failure.
        Moves the topic to avoid_domains so GoalEngine stops picking it blindly.
        """
        frust: list[str] = self._v.get("frustration_topics", [])
        if topic not in frust:
            frust.append(topic)
        self._v["frustration_topics"] = frust[-_MAX_FRUSTRATION:]

        avoid: list[str] = self._v.get("avoid_domains", [])
        if topic not in avoid:
            avoid.append(topic)
        self._v["avoid_domains"] = avoid[-_MAX_AVOID:]

        self._log(f"frustration: {topic} ({hits} hits) → avoid_domains")
        self.save()

    def record_momentum(self, old: str, new: str) -> None:
        """Called when NightRunner detects a momentum shift."""
        self._log(f"momentum: {old} → {new}")
        if new == "accelerating":
            # Expand focus slightly
            self._maybe_add_focus("advanced topics")
        elif new == "stagnating":
            # Tighten focus to fundamentals
            self._maybe_add_focus("fundamentals review")
        self.save()

    def update_focus(self, domains: list[str]) -> None:
        """Directly set focus domains (e.g. from external calibration)."""
        self._v["focus_domains"] = domains[:10]
        self._log(f"focus updated: {', '.join(domains[:5])}")
        self.save()

    def set_statement(self, new_statement: str) -> None:
        """Directly update the mission statement."""
        self._v["statement"] = new_statement.strip()
        self._log("statement updated")
        self.save()

    # ------------------------------------------------------------------
    # CognitionCore on_event
    # ------------------------------------------------------------------

    def on_event(self, event_type: str, data: Any, source: str = "") -> None:
        if event_type == "skill_certified":
            topic = data.get("topic", "")
            score = data.get("score", 0.0)
            if topic:
                self.record_certified(topic, score)
        elif event_type == "frustration_peak":
            topic = data.get("topic", "")
            hits = data.get("hits", 0)
            if topic:
                self.record_frustration(topic, hits)
        elif event_type == "momentum_changed":
            old = data.get("old", "")
            new = data.get("new", "")
            if old or new:
                self.record_momentum(old, new)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_statement(self, count: int) -> None:
        """Update the statement to reflect cumulative progress."""
        base = (
            "SHARD seeks to become a reliable autonomous problem-solver — "
            "mastering software engineering fundamentals, building robust reasoning, "
            "and compounding knowledge session by session."
        )
        milestone = f" ({count} skills certified so far)"
        self._v["statement"] = base + milestone

    def _maybe_add_focus(self, domain: str) -> None:
        focus: list[str] = self._v.get("focus_domains", [])
        if domain not in focus:
            focus.append(domain)
            self._v["focus_domains"] = focus[:10]

    def _log(self, msg: str) -> None:
        entry = {"ts": _utc_now_iso(), "msg": msg}
        log: list = self._v.get("update_log", [])
        log.append(entry)
        self._v["update_log"] = log[-_MAX_LOG:]
        self._v["last_updated"] = entry["ts"]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_vision_instance: Optional[VisionEngine] = None


def get_vision() -> VisionEngine:
    """Return the module-level singleton VisionEngine, loading from disk once."""
    global _vision_instance
    if _vision_instance is None:
        _vision_instance = VisionEngine.load()
    return _vision_instance
