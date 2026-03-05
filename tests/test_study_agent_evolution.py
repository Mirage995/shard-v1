"""
Tests for Study Agent Evolution: Cross-Pollination & Materialization.

Uses unittest.mock to patch Groq and ChromaDB so tests run fully offline
without API keys or network access.
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
    with patch("study_agent.Groq") as MockGroq, \
         patch("study_agent.chromadb") as MockChroma, \
         patch("study_agent.CHROMA_DB_PATH", str(tmp_path / "chroma")), \
         patch("study_agent.SANDBOX_DIR", str(tmp_path / "sandbox")), \
         patch("study_agent.WORKSPACE_DIR", str(tmp_path / "workspace")):

        # Mock ChromaDB client and collection
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

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        MockChroma.PersistentClient.return_value = mock_client

        # Mock Groq client
        mock_groq_response = MagicMock()
        mock_groq_response.choices = [MagicMock()]
        mock_groq_response.choices[0].message.content = "Mocked LLM response"

        mock_groq_client = MagicMock()
        mock_groq_client.chat.completions.create.return_value = mock_groq_response
        MockGroq.return_value = mock_groq_client

        from study_agent import StudyAgent
        sa = StudyAgent()

        # Store refs for assertions
        sa._mock_collection = mock_collection
        sa._mock_groq_client = mock_groq_client
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
    """Cross-pollinate should call Groq LLM to generate the report."""
    await agent.phase_cross_pollinate("Advanced Python", "raw text", SAMPLE_STRUCTURED)

    # Groq was called
    agent._mock_groq_client.chat.completions.create.assert_called()


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
    """Materialize should write a .md file to shard_workspace/knowledge_base/."""
    # Patch WORKSPACE_DIR for this agent
    with patch("study_agent.WORKSPACE_DIR", agent._tmp_workspace):
        result = await agent.phase_materialize("Advanced Python", SAMPLE_STRUCTURED)

    assert result is True

    # Check the file was created
    expected_file = os.path.join(agent._tmp_workspace, "knowledge_base", "advanced_python.md")
    assert os.path.exists(expected_file), f"File not found: {expected_file}"

    # Check it has content
    with open(expected_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert len(content) > 0


@pytest.mark.asyncio
async def test_materialize_llm_called(agent):
    """Materialize should call Groq LLM to generate the cheat sheet."""
    with patch("study_agent.WORKSPACE_DIR", agent._tmp_workspace):
        await agent.phase_materialize("Advanced Python", SAMPLE_STRUCTURED)

    agent._mock_groq_client.chat.completions.create.assert_called()


@pytest.mark.asyncio
async def test_materialize_filename_sanitization(agent):
    """Topic names with special chars should be sanitized to safe filenames."""
    with patch("study_agent.WORKSPACE_DIR", agent._tmp_workspace):
        result = await agent.phase_materialize("C++ vs Rust: A Deep Dive!", SAMPLE_STRUCTURED)

    assert result is True

    # The file should exist with sanitized name
    kb_dir = os.path.join(agent._tmp_workspace, "knowledge_base")
    files = os.listdir(kb_dir)
    assert len(files) == 1
    assert files[0].endswith(".md")
    # No special characters in filename
    assert "!" not in files[0]
    assert ":" not in files[0]
    assert "+" not in files[0]


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
