"""
Tests for Study Agent Evolution: Cross-Pollination & Materialization.

Uses unittest.mock to patch Groq and ChromaDB so tests run fully offline
without API keys or network access.

NOTE: GoalStorage was removed from study_agent in the SSJ refactor.
Tests that depend on GoalStorage import are skipped pending rewrite.
"""
import sys
import os
import json
import tempfile

import pytest

# Ensure backend/ is on the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from unittest.mock import patch, MagicMock, AsyncMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_env(monkeypatch):
    """Set GROQ_API_KEY so StudyAgent.__init__ doesn't raise."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key-fake")


@pytest.fixture
def agent(mock_env, tmp_path):
    """Create a StudyAgent with mocked Groq client and in-memory ChromaDB."""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [["Doc about Python basics", "Doc about async patterns", "Doc about web frameworks"]],
        "metadatas": [[
            {"topic": "Python Basics", "type": "raw"},
            {"topic": "Async Patterns", "type": "raw"},
            {"topic": "Web Frameworks", "type": "raw"},
        ]],
        "distances": [[0.3, 0.5, 0.7]],
    }
    mock_collection.upsert.return_value = None

    with patch("study_agent.get_collection", return_value=mock_collection), \
         patch("study_agent.CHROMA_DB_PATH", str(tmp_path / "chroma")), \
         patch("study_agent.SANDBOX_DIR", str(tmp_path / "sandbox")), \
         patch("study_agent.WORKSPACE_DIR", str(tmp_path / "workspace")):

        from study_agent import StudyAgent
        sa = StudyAgent()

        # Store refs for assertions
        sa._mock_collection = mock_collection
        sa._tmp_workspace = str(tmp_path / "workspace")

        yield sa


# ── Structured data fixture ──────────────────────────────────────────────────

SAMPLE_STRUCTURED = {
    "concepts": [
        {"name": "Decorators", "explanation": "Functions wrapping functions", "importance": 9},
        {"name": "Generators", "explanation": "Lazy iterators using yield", "importance": 8},
        {"name": "Context Managers", "explanation": "With-statement protocol", "importance": 7},
    ],
    "relationships": ["Decorators can wrap generators"],
    "shard_opinion": "Python's metaprogramming is elegant and powerful.",
    "critical_questions": ["How do decorators affect generator state?"],
    "code_snippet": "def deco(f):\n    def wrapper(*a):\n        return f(*a)\n    return wrapper",
}


# ── Test: Cross-Pollination ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_pollinate_queries_chromadb(agent):
    """Cross-pollinate should query ChromaDB for top-3 related docs."""
    report = await agent.phase_cross_pollinate("Advanced Python", "raw text", SAMPLE_STRUCTURED)

    # ChromaDB was queried
    agent._mock_collection.query.assert_called_once()
    call_kwargs = agent._mock_collection.query.call_args
    assert call_kwargs.kwargs["n_results"] == 3
    assert call_kwargs.kwargs["where"] == {"topic": {"$ne": "Advanced Python"}}

    # Report is a non-empty string
    assert isinstance(report, str)
    assert len(report) > 0


@pytest.mark.asyncio
async def test_cross_pollinate_saves_deep_knowledge(agent):
    """Cross-pollinate should upsert the Integration Report with type: deep_knowledge."""
    await agent.phase_cross_pollinate("Advanced Python", "raw text", SAMPLE_STRUCTURED)

    # ChromaDB upsert was called
    agent._mock_collection.upsert.assert_called()

    # Check the metadata contains type: deep_knowledge
    upsert_call = agent._mock_collection.upsert.call_args
    meta = upsert_call.kwargs["metadatas"][0]
    assert meta["type"] == "deep_knowledge"
    assert meta["topic"] == "Advanced Python"
    assert meta["source"] == "cross_pollination"

    # Check the document contains the report
    doc = upsert_call.kwargs["documents"][0]
    assert "Integration Report" in doc


@pytest.mark.asyncio
async def test_cross_pollinate_llm_called(agent):
    """Cross-pollinate should call llm_complete to generate the report."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="Integration Report: test") as mock_lc:
        await agent.phase_cross_pollinate("Advanced Python", "raw text", SAMPLE_STRUCTURED)
    mock_lc.assert_awaited()


@pytest.mark.asyncio
async def test_cross_pollinate_no_existing_knowledge(agent):
    """When ChromaDB returns no results, cross-pollinate should still work."""
    # Override collection to return empty results
    agent._mock_collection.query.return_value = {
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }

    report = await agent.phase_cross_pollinate("Brand New Topic", "raw text", SAMPLE_STRUCTURED)
    assert isinstance(report, str)
    assert len(report) > 0


# ── Test: Materialization ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_materialize_creates_file(agent):
    """Materialize should call write_file with a .md path under knowledge_base/."""
    written = {}

    def capture_write(path, content, workspace_dir):
        written["path"] = path
        written["content"] = content
        return f"success: file '{path}' written ({len(content)} bytes)."

    with patch("study_agent.write_file", side_effect=capture_write), \
         patch("study_agent.WORKSPACE_DIR", agent._tmp_workspace):
        result = await agent.phase_materialize("Advanced Python", SAMPLE_STRUCTURED)

    assert "path" in written, "write_file was never called"
    assert written["path"].startswith("knowledge_base/")
    assert written["path"].endswith(".md")
    assert len(written["content"]) > 0


@pytest.mark.asyncio
async def test_materialize_llm_called(agent):
    """Materialize should call llm_complete to generate the cheat sheet."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="# Cheat Sheet\nContent") as mock_lc, \
         patch("study_agent.WORKSPACE_DIR", agent._tmp_workspace):
        await agent.phase_materialize("Advanced Python", SAMPLE_STRUCTURED)
    mock_lc.assert_awaited()


@pytest.mark.asyncio
async def test_materialize_filename_sanitization(agent):
    """Topic names with special chars should produce sanitized filenames."""
    written = {}

    def capture_write(path, content, workspace_dir):
        written["path"] = path
        return f"success: file '{path}' written ({len(content)} bytes)."

    with patch("study_agent.write_file", side_effect=capture_write), \
         patch("study_agent.WORKSPACE_DIR", agent._tmp_workspace):
        await agent.phase_materialize("C++ vs Rust: A Deep Dive!", SAMPLE_STRUCTURED)

    assert "path" in written, "write_file was never called"
    filename = os.path.basename(written["path"])
    assert filename.endswith(".md")
    assert "!" not in filename
    assert ":" not in filename
    assert "+" not in filename


# ── Test: Progress Tracking ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_progress_includes_new_phases(agent):
    """ProgressTracker should include CROSS_POLLINATE and MATERIALIZE phases."""
    phases = agent.progress.status["phases"]
    assert "CROSS_POLLINATE" in phases
    assert "MATERIALIZE" in phases


@pytest.mark.asyncio
async def test_progress_updates_during_cross_pollinate(agent):
    """Cross-pollinate should update progress tracker."""
    await agent.phase_cross_pollinate("Test Topic", "raw", SAMPLE_STRUCTURED)
    assert agent.progress.phase_progress.get("CROSS_POLLINATE") == 1.0


@pytest.mark.asyncio
async def test_progress_updates_during_materialize(agent):
    """Materialize should update progress tracker."""
    with patch("study_agent.WORKSPACE_DIR", agent._tmp_workspace):
        await agent.phase_materialize("Test Topic", SAMPLE_STRUCTURED)
    assert agent.progress.phase_progress.get("MATERIALIZE") == 1.0
