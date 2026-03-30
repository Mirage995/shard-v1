"""
VoiceBroadcaster -- file-based queue for proactive SHARD voice events.

NightRunner (standalone process) writes to the queue.
server.py polls and emits via Socket.IO -> frontend Web Speech API or Gemini Live.

Queue file: shard_memory/voice_queue.json
"""

import json
import os
import time
import tempfile
from pathlib import Path
from typing import Literal

Priority = Literal["low", "medium", "high"]

# Minimum seconds between broadcasts per priority level
_THROTTLE = {
    "high":   0,    # immediate
    "medium": 15,
    "low":    45,
}

_QUEUE_FILE = Path(__file__).resolve().parent.parent / "shard_memory" / "voice_queue.json"
_LAST_EMIT_FILE = Path(__file__).resolve().parent.parent / "shard_memory" / "voice_last_emit.json"


def _read_queue() -> list:
    try:
        if _QUEUE_FILE.exists():
            return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _write_queue(queue: list) -> None:
    tmp = _QUEUE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _QUEUE_FILE)
    except Exception as e:
        print(f"[VOICE BROADCASTER] Queue write error: {e}")


def _read_last_emit() -> dict:
    try:
        if _LAST_EMIT_FILE.exists():
            return json.loads(_LAST_EMIT_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_last_emit(data: dict) -> None:
    tmp = _LAST_EMIT_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, _LAST_EMIT_FILE)
    except Exception:
        pass


def broadcast(text: str, priority: Priority = "low", event_type: str = "info") -> None:
    """
    Enqueue a voice message. Called by NightRunner, StudyAgent, or any backend module.
    Respects per-priority throttle to avoid spam.
    """
    now = time.time()
    last_emit = _read_last_emit()
    last_ts = last_emit.get(priority, 0)

    if now - last_ts < _THROTTLE[priority]:
        print(f"[VOICE BROADCASTER] Throttled ({priority}): '{text[:60]}'")
        return

    queue = _read_queue()
    queue.append({
        "text": text,
        "priority": priority,
        "event_type": event_type,
        "timestamp": now,
    })
    _write_queue(queue)

    # Update throttle timestamp
    last_emit[priority] = now
    _write_last_emit(last_emit)

    print(f"[VOICE BROADCASTER] Enqueued ({priority}): '{text[:80]}'")


def pop_all() -> list:
    """
    Read and clear the queue. Called by server.py poller.
    Returns list of pending events sorted by priority (high first).
    """
    queue = _read_queue()
    if not queue:
        return []
    _write_queue([])
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(queue, key=lambda e: priority_order.get(e.get("priority", "low"), 2))
