"""Shared session lock for SHARD.

SHARD_SESSION_LOCK (asyncio.Semaphore) prevents NightRunner from starting
an autonomous study cycle while a live Gemini audio session is active --
and vice versa.

Dual-layer coordination:
  - In-process:      asyncio.Semaphore(1) -- works when both run in same event loop
  - Cross-process:   SESSION_LOCK_FILE    -- works when NightRunner is a separate process
"""
import asyncio
from pathlib import Path

# ── In-process lock ───────────────────────────────────────────────────────────
SHARD_SESSION_LOCK: asyncio.Semaphore = asyncio.Semaphore(1)

# ── Cross-process lock file ───────────────────────────────────────────────────
# Presence of this file means a session is active.
# Content = reason string ("audio_session" | "night_runner")
SESSION_LOCK_FILE: Path = Path(__file__).parent.parent / "shard_memory" / "session.lock"


def acquire_file_lock(reason: str = "audio_session") -> None:
    """Write lock file to signal an active session (cross-process)."""
    SESSION_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_LOCK_FILE.write_text(reason, encoding="utf-8")


def release_file_lock() -> None:
    """Remove lock file to signal session ended."""
    try:
        SESSION_LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def is_file_locked() -> bool:
    """Return True if a session lock file exists."""
    return SESSION_LOCK_FILE.exists()


def get_lock_reason() -> str:
    """Return the reason string from the lock file, or empty string if not locked."""
    try:
        return SESSION_LOCK_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def is_audio_active() -> bool:
    """Return True if the lock is held by an active audio session."""
    return get_lock_reason() == "audio_session"
