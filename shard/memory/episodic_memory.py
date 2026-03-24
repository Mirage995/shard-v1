"""Proxy to the real EpisodicMemory in backend/episodic_memory.py.

study_agent.py loads this file dynamically via _load_reliability_module().
We proxy store_episode to the real implementation instead of a no-op stub.
"""
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parents[2] / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from episodic_memory import store_episode, get_episodic_memory  # noqa: F401
