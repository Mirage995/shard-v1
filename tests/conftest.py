"""
Pytest configuration and shared fixtures for ada_v2 tests.
"""
import pytest
import sys
import os
import json
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# ── Grab the real shard_db NOW, before any test file can replace it with a mock ──
# test_graph_rag.py and test_llm_cache.py do sys.modules["shard_db"] = MagicMock()
# at module level, which would break any DB fixture that runs after collection.
import shard_db as _real_shard_db

# Settings file path
SETTINGS_FILE = BACKEND_DIR / "settings.json"


@pytest.fixture(scope="session")
def settings():
    """Load settings.json for device configurations."""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}


@pytest.fixture(scope="session")
def kasa_devices(settings):
    """Get Kasa devices from settings."""
    return settings.get("kasa_devices", [])


@pytest.fixture(scope="session")
def printers(settings):
    """Get printers from settings."""
    return settings.get("printers", [])


@pytest.fixture(autouse=True)
def reset_feedback_field_state():
    """Clear feedback_field_state before each test to prevent cross-test DB contamination.

    Uses the real shard_db (saved at conftest load time) and temporarily restores it
    in sys.modules so that tests that need persistence (and FeedbackField._load/._save)
    work correctly even after test_graph_rag.py / test_llm_cache.py replace it with a mock.
    """
    original_shard_db = sys.modules.get("shard_db")
    sys.modules["shard_db"] = _real_shard_db
    try:
        _real_shard_db.execute("DELETE FROM feedback_field_state")
    except Exception:
        pass
    yield
    # Restore whatever was in sys.modules before (may be a mock)
    if original_shard_db is not None:
        sys.modules["shard_db"] = original_shard_db
    else:
        sys.modules.pop("shard_db", None)


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for file operations."""
    return tmp_path


@pytest.fixture
def sample_stl_content():
    """Sample minimal STL file content for testing."""
    return """solid test
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0.5 1 0
    endloop
  endfacet
endsolid test"""
