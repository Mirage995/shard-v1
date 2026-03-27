"""
benchmark_tracker.py — SHARD benchmark performance tracker across sessions.

Tracks per-task success/failure across sessions, computes deltas, streaks,
and provides prompt-injectable summaries for CognitionCore integration.
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
_HISTORY_PATH = _REPO_ROOT / "shard_memory" / "benchmark_history.json"
_MAX_SESSIONS = 20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON to *path* atomically using a sibling temp file."""
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
    """Load JSON from *path*, returning an empty sessions structure on any error."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict) and "sessions" in data:
            return data
    except Exception:
        pass
    return {"sessions": []}


# ---------------------------------------------------------------------------
# BenchmarkTracker
# ---------------------------------------------------------------------------

class BenchmarkTracker:
    """Tracks SHARD benchmark results across sessions and computes deltas."""

    def __init__(self, history_path: Path = _HISTORY_PATH) -> None:
        self._path = history_path
        self._data: dict = {"sessions": []}
        self._last_delta: Optional[dict] = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, history_path: Path = _HISTORY_PATH) -> "BenchmarkTracker":
        """Create a BenchmarkTracker and load existing history from disk."""
        tracker = cls(history_path=history_path)
        tracker._data = _safe_load(history_path)
        return tracker

    def save(self) -> bool:
        """Persist current history to disk atomically. Returns True on success."""
        try:
            _atomic_write(self._path, self._data)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def record_session(self, results: list[dict]) -> dict:
        """
        Save a session built from *results* and return a delta vs the previous session.

        Each element in *results* must contain:
            task_dir        (str)   — task identifier
            success         (bool)
            total_attempts  (int)
            elapsed_total   (float)

        Returns a delta dict with keys:
            improved, regressed, stable_pass, stable_fail, first_seen
        each mapping to a list of task_id strings.
        """
        try:
            session_results: dict[str, dict] = {}
            for r in results:
                task_id = str(r.get("task_dir", "unknown"))
                session_results[task_id] = {
                    "success": bool(r.get("success", False)),
                    "attempts": int(r.get("total_attempts", 1)),
                    "elapsed": float(r.get("elapsed_total", 0.0)),
                }

            passed = sum(1 for v in session_results.values() if v["success"])
            failed = len(session_results) - passed

            session: dict[str, Any] = {
                "date": _utc_now_iso(),
                "results": session_results,
                "summary": {
                    "passed": passed,
                    "failed": failed,
                    "total": len(session_results),
                },
            }

            delta = self._compute_delta(session_results)
            self._last_delta = delta

            sessions: list = self._data.get("sessions", [])
            sessions.append(session)
            # Keep only the most recent N sessions
            self._data["sessions"] = sessions[-_MAX_SESSIONS:]

            self.save()
            return delta

        except Exception:
            return {
                "improved": [],
                "regressed": [],
                "stable_pass": [],
                "stable_fail": [],
                "first_seen": [],
            }

    def _compute_delta(self, current: dict[str, dict]) -> dict:
        """Compare *current* results against the most recent stored session."""
        improved: list[str] = []
        regressed: list[str] = []
        stable_pass: list[str] = []
        stable_fail: list[str] = []
        first_seen: list[str] = []

        sessions = self._data.get("sessions", [])
        if not sessions:
            first_seen = list(current.keys())
            return {
                "improved": improved,
                "regressed": regressed,
                "stable_pass": stable_pass,
                "stable_fail": stable_fail,
                "first_seen": first_seen,
            }

        previous: dict[str, dict] = sessions[-1].get("results", {})

        for task_id, info in current.items():
            now_pass = info["success"]
            if task_id not in previous:
                first_seen.append(task_id)
                continue
            prev_pass = previous[task_id].get("success", False)
            if not prev_pass and now_pass:
                improved.append(task_id)
            elif prev_pass and not now_pass:
                regressed.append(task_id)
            elif prev_pass and now_pass:
                stable_pass.append(task_id)
            else:
                stable_fail.append(task_id)

        return {
            "improved": improved,
            "regressed": regressed,
            "stable_pass": stable_pass,
            "stable_fail": stable_fail,
            "first_seen": first_seen,
        }

    def get_delta_summary(self) -> str:
        """
        Return a human-readable delta string suitable for prompt injection.

        Uses the delta from the most recently recorded session, or computes
        a fresh one from the last two stored sessions if available.
        """
        try:
            delta = self._last_delta
            if delta is None:
                sessions = self._data.get("sessions", [])
                if len(sessions) < 2:
                    if len(sessions) == 1:
                        s = sessions[0]["summary"]
                        return (
                            f"Benchmark (single session): "
                            f"{s['passed']}/{s['total']} passing."
                        )
                    return "No benchmark history available."
                # Recompute from last two sessions
                current = sessions[-1].get("results", {})
                prev_session = sessions[-2]
                self._data["sessions"] = sessions[:-1]
                delta = self._compute_delta(current)
                self._data["sessions"] = sessions

            parts: list[str] = []
            if delta["improved"]:
                tasks = ", ".join(delta["improved"])
                parts.append(f"{tasks} now passing (+{len(delta['improved'])})")
            if delta["regressed"]:
                tasks = ", ".join(delta["regressed"])
                parts.append(f"{tasks} regressed (-{len(delta['regressed'])})")
            if delta["first_seen"]:
                tasks = ", ".join(delta["first_seen"])
                parts.append(f"{tasks} first seen ({len(delta['first_seen'])} new)")

            n_stable_pass = len(delta.get("stable_pass", []))
            n_stable_fail = len(delta.get("stable_fail", []))

            if parts:
                changes = "; ".join(parts)
                summary = f"Benchmark delta vs last session: {changes}."
            else:
                summary = "Benchmark delta vs last session: no changes."

            summary += f" Stable: {n_stable_pass} passing, {n_stable_fail} failing."
            return summary

        except Exception:
            return "Benchmark summary unavailable."

    def get_streak(self, task_id: str) -> int:
        """
        Return the streak length for *task_id*.

        Positive  → number of consecutive sessions the task has been passing.
        Negative  → number of consecutive sessions the task has been failing.
        0         → task not found in any session.
        """
        try:
            sessions = self._data.get("sessions", [])
            if not sessions:
                return 0

            # Walk backwards through sessions
            streak = 0
            reference: Optional[bool] = None

            for session in reversed(sessions):
                results = session.get("results", {})
                if task_id not in results:
                    break
                success = bool(results[task_id].get("success", False))
                if reference is None:
                    reference = success
                if success != reference:
                    break
                streak += 1

            if streak == 0:
                return 0
            return streak if reference else -streak

        except Exception:
            return 0

    # ------------------------------------------------------------------
    # CognitionCore stub
    # ------------------------------------------------------------------

    def on_event(self, event_type: str, data: Any, source: str) -> None:
        """
        Event handler stub for CognitionCore registration.

        Recognised event_type values (for future use):
            "benchmark_complete"  — data should be a list of result dicts,
                                    same format as record_session expects.
        """
        pass


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracker_instance: Optional[BenchmarkTracker] = None


def get_benchmark_tracker() -> BenchmarkTracker:
    """Return the module-level singleton BenchmarkTracker, loading from disk once."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = BenchmarkTracker.load()
    return _tracker_instance
