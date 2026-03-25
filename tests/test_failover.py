"""
Tests for StudyAgent LLM routing — _think() and _think_fast().

Both methods now route through llm_router.llm_complete.
Tests verify provider priority, json_mode flag, and result passthrough.
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from unittest.mock import patch, MagicMock, AsyncMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


@pytest.fixture
def agent(mock_env, tmp_path):
    """StudyAgent with mocked get_collection and llm_complete."""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    mock_collection.upsert.return_value = None

    with patch("study_agent.get_collection", return_value=mock_collection), \
         patch("study_agent.CHROMA_DB_PATH", str(tmp_path / "chroma")), \
         patch("study_agent.SANDBOX_DIR", str(tmp_path / "sandbox")), \
         patch("study_agent.WORKSPACE_DIR", str(tmp_path / "workspace")):
        from study_agent import StudyAgent
        sa = StudyAgent()
    return sa


# ── _think ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_think_calls_llm_complete(agent):
    """_think delegates to llm_complete."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="Claude answer") as mock_lc:
        result = await agent._think("complex task")
    assert result == "Claude answer"
    mock_lc.assert_awaited_once()


@pytest.mark.asyncio
async def test_think_prefers_gemini_provider(agent):
    """_think passes Gemini (free) as first provider."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="ok") as mock_lc:
        await agent._think("task")
    providers = mock_lc.call_args.kwargs["providers"]
    assert providers[0] == "Gemini"


@pytest.mark.asyncio
async def test_think_json_mode_adds_instruction(agent):
    """json_mode=True appends JSON instruction to system prompt."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="{}") as mock_lc:
        await agent._think("task", json_mode=True)
    system = mock_lc.call_args.kwargs["system"]
    assert "VALID JSON" in system


@pytest.mark.asyncio
async def test_think_no_json_mode_no_instruction(agent):
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="text") as mock_lc:
        await agent._think("task", json_mode=False)
    system = mock_lc.call_args.kwargs["system"]
    assert "VALID JSON" not in system


# ── _think_fast ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_think_fast_calls_llm_complete(agent):
    """_think_fast delegates to llm_complete."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="fast answer") as mock_lc:
        result = await agent._think_fast("quick task")
    assert result == "fast answer"
    mock_lc.assert_awaited_once()


@pytest.mark.asyncio
async def test_think_fast_prefers_gemini_provider(agent):
    """_think_fast passes Gemini (free) as first provider."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="ok") as mock_lc:
        await agent._think_fast("task")
    providers = mock_lc.call_args.kwargs["providers"]
    assert providers[0] == "Gemini"


@pytest.mark.asyncio
async def test_think_fast_json_mode(agent):
    """json_mode=True also adds JSON instruction to _think_fast."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="[]") as mock_lc:
        await agent._think_fast("task", json_mode=True)
    system = mock_lc.call_args.kwargs["system"]
    assert "VALID JSON" in system


@pytest.mark.asyncio
async def test_think_and_think_fast_both_prefer_gemini(agent):
    """Both _think and _think_fast use Gemini-first provider chain."""
    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="ok") as mock_lc:
        await agent._think("complex")
        think_providers = mock_lc.call_args.kwargs["providers"]

    with patch("study_agent.llm_complete", new_callable=AsyncMock, return_value="ok") as mock_lc:
        await agent._think_fast("quick")
        fast_providers = mock_lc.call_args.kwargs["providers"]

    assert think_providers[0] == "Gemini"
    assert fast_providers[0] == "Gemini"


if __name__ == "__main__":
    import pytest as _pt
    _pt.main([__file__, "-v"])
