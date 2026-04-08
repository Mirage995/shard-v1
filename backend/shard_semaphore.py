"""Shared session lock for SHARD.

SHARD_SESSION_LOCK (asyncio.Semaphore) prevents NightRunner from starting
an autonomous study cycle while a live Gemini audio session is active --
and vice versa.

Dual-layer coordination:
  - In-process:      asyncio.Semaphore(1) -- works when both run in same event loop
  - Cross-process:   SESSION_LOCK_FILE    -- works when NightRunner is a separate process

Stale lock recovery:
  Lock file stores "reason|PID|timestamp". On startup, if the PID is no longer
  alive (e.g. crash/reboot), the lock is considered stale and auto-released.
"""
import asyncio
import os
import time
from pathlib import Path

# ── In-process lock ───────────────────────────────────────────────────────────
SHARD_SESSION_LOCK: asyncio.Semaphore = asyncio.Semaphore(1)

# ── Cross-process lock file ───────────────────────────────────────────────────
SESSION_LOCK_FILE: Path = Path(__file__).parent.parent / "shard_memory" / "session.lock"

# A lock file older than this is considered stale even if PID is alive
_STALE_TTL_SECONDS = 3 * 3600  # 3 hours


def _is_pid_alive(pid: int) -> bool:
    """Return True if the process with given PID is still running."""
    try:
        os.kill(pid, 0)  # signal 0: check existence, no actual signal sent
        return True
    except (OSError, ProcessLookupError):
        return False


def _parse_lock_file() -> dict:
    """Parse lock file content. Returns dict with reason, pid, timestamp."""
    try:
        content = SESSION_LOCK_FILE.read_text(encoding="utf-8").strip()
        parts = content.split("|")
        reason = parts[0] if parts else content
        pid = int(parts[1]) if len(parts) > 1 else None
        ts = float(parts[2]) if len(parts) > 2 else None
        return {"reason": reason, "pid": pid, "timestamp": ts}
    except (OSError, ValueError):
        return {"reason": "", "pid": None, "timestamp": None}


def _is_stale() -> bool:
    """Return True if the lock file belongs to a dead process or is too old."""
    info = _parse_lock_file()
    pid = info.get("pid")
    ts = info.get("timestamp")

    # PID check: if we have a PID and it's dead, lock is stale
    if pid is not None and not _is_pid_alive(pid):
        return True

    # Age check: lock older than TTL is stale regardless of PID
    if ts is not None and (time.time() - ts) > _STALE_TTL_SECONDS:
        return True

    return False


def acquire_file_lock(reason: str = "audio_session") -> None:
    """Write lock file with reason, PID and timestamp."""
    SESSION_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = f"{reason}|{os.getpid()}|{time.time():.0f}"
    SESSION_LOCK_FILE.write_text(content, encoding="utf-8")


def release_file_lock() -> None:
    """Remove lock file to signal session ended."""
    try:
        SESSION_LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def is_file_locked() -> bool:
    """Return True if a valid (non-stale) session lock file exists."""
    if not SESSION_LOCK_FILE.exists():
        return False
    if _is_stale():
        # Auto-release stale lock from dead/crashed process
        release_file_lock()
        return False
    return True


def get_lock_reason() -> str:
    """Return the reason string from the lock file, or empty string if not locked."""
    return _parse_lock_file().get("reason", "")


def is_audio_active() -> bool:
    """Return True if the lock is held by an active audio session."""
    return get_lock_reason() == "audio_session"
