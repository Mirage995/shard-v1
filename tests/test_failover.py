"""
Tests for Study Agent Dual LLM Routing:
    - _think() → Claude (Anthropic) for complex reasoning
    - _think_fast() → Groq for fast/simple tasks  
    - _think_local() → Ollama for EVALUATE (independent judge)

Verifies:
    - _think_fast() uses Groq successfully
    - _think_fast() falls back to Claude on Groq RateLimit (429)
    - _think_fast() falls back to Claude when Groq is disabled (no API key)
    - _think() still falls back to Ollama on Anthropic errors
"""
import sys
import os
import json

import pytest

# Ensure backend/ is on the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from unittest.mock import patch, MagicMock, AsyncMock
import httpx


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_env(monkeypatch):
    """Set API keys so StudyAgent.__init__ doesn't raise."""
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


@pytest.fixture
def agent(mock_env, tmp_path):
    """Create a StudyAgent with mocked clients and in-memory ChromaDB."""
    with patch("study_agent.Groq") as MockGroq, \
         patch("study_agent.chromadb") as MockChroma, \
         patch("study_agent.CHROMA_DB_PATH", str(tmp_path / "chroma")), \
         patch("study_agent.SANDBOX_DIR", str(tmp_path / "sandbox")), \
         patch("study_agent.WORKSPACE_DIR", str(tmp_path / "workspace")):

        # Mock ChromaDB client and collection
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        mock_collection.upsert.return_value = None

        mock_chroma_client = MagicMock()
        mock_chroma_client.get_or_create_collection.return_value = mock_collection
        MockChroma.PersistentClient.return_value = mock_chroma_client

        # Mock Anthropic client (patch the class constructor, not the module)
        mock_anthropic_response = MagicMock()
        mock_anthropic_response.content = [MagicMock()]
        mock_anthropic_response.content[0].text = "Mocked Claude response"

        mock_anthropic_client = MagicMock()
        mock_anthropic_client.messages.create.return_value = mock_anthropic_response

        with patch("study_agent.anthropic.Anthropic", return_value=mock_anthropic_client):
            # Mock Groq client
            mock_groq_response = MagicMock()
            mock_groq_response.choices = [MagicMock()]
            mock_groq_response.choices[0].message.content = "Mocked Groq response"

            mock_groq_client = MagicMock()
            mock_groq_client.chat.completions.create.return_value = mock_groq_response
            MockGroq.return_value = mock_groq_client

            from study_agent import StudyAgent
            sa = StudyAgent()

            # Store refs for test assertions
            sa._mock_groq_client = mock_groq_client
            sa._mock_anthropic_client = mock_anthropic_client

            yield sa


# ── Test: _think_fast() uses Groq ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_think_fast_uses_groq(agent):
    """_think_fast should use Groq for fast tasks."""
    result = await agent._think_fast("Generate search queries")

    assert result == "Mocked Groq response"
    agent._mock_groq_client.chat.completions.create.assert_called_once()
    call_kwargs = agent._mock_groq_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "llama-3.3-70b-versatile"


# ── Test: _think_fast() falls back to Claude on RateLimit ─────────────────────

@pytest.mark.asyncio
async def test_think_fast_fallback_on_groq_rate_limit(agent):
    """When Groq returns 429, _think_fast should fallback to Claude."""
    from groq import RateLimitError as GroqRateLimitError

    mock_response = httpx.Response(
        status_code=429,
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    agent._mock_groq_client.chat.completions.create.side_effect = GroqRateLimitError(
        message="Rate limit exceeded",
        response=mock_response,
        body={"error": {"message": "Rate limit exceeded"}},
    )

    result = await agent._think_fast("test prompt")

    # Should have fallen back to Claude
    assert result == "Mocked Claude response"
    agent._mock_anthropic_client.messages.create.assert_called_once()


# ── Test: _think_fast() falls back when Groq disabled ─────────────────────────

@pytest.mark.asyncio
async def test_think_fast_fallback_when_groq_disabled(agent):
    """When groq_client is None (no API key), _think_fast should use Claude."""
    agent.groq_client = None

    result = await agent._think_fast("test prompt")

    # Should have used Claude directly
    assert result == "Mocked Claude response"
    agent._mock_anthropic_client.messages.create.assert_called_once()


# ── Test: _think() uses Claude normally ───────────────────────────────────────

@pytest.mark.asyncio
async def test_think_uses_claude(agent):
    """_think should use Anthropic Claude for complex reasoning."""
    result = await agent._think("Complex reasoning task")

    assert result == "Mocked Claude response"
    agent._mock_anthropic_client.messages.create.assert_called_once()
    call_kwargs = agent._mock_anthropic_client.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "claude-3-5-sonnet-20241022"


# ── Test: _think() falls back to Ollama on Anthropic RateLimit ────────────────

@pytest.mark.asyncio
async def test_think_fallback_on_anthropic_error(agent):
    """When Anthropic fails, _think should fallback to _think_local (Ollama)."""
    # Simulate an API error from Anthropic
    agent._mock_anthropic_client.messages.create.side_effect = Exception("API overloaded")

    # Mock _think_local
    agent._think_local = AsyncMock(return_value="Fallback to Ollama")

    result = await agent._think("test prompt")

    agent._think_local.assert_called_once()
    assert result == "Fallback to Ollama"


# ── Test: _think_fast() preserves json_mode ───────────────────────────────────

@pytest.mark.asyncio
async def test_think_fast_json_mode(agent):
    """_think_fast with json_mode=True should pass JSON instruction to Groq."""
    agent._mock_groq_client.chat.completions.create.return_value.choices[0].message.content = '["query1", "query2"]'

    result = await agent._think_fast("Generate queries", json_mode=True)

    # Verify JSON mode instruction was added to system prompt
    call_kwargs = agent._mock_groq_client.chat.completions.create.call_args
    messages = call_kwargs.kwargs["messages"]
    assert "VALID JSON" in messages[0]["content"]
    assert result == '["query1", "query2"]'


# ── Test: _think_local uses llama3.2 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_think_local_uses_llama32_model(agent):
    """_think_local should use model='llama3.2'."""
    mock_local_resp = MagicMock()
    mock_local_resp.choices = [MagicMock()]
    mock_local_resp.choices[0].message.content = "Local LLM response"

    agent.local_client = AsyncMock()
    agent.local_client.chat.completions.create.return_value = mock_local_resp

    result = await agent._think_local("test prompt")

    assert result == "Local LLM response"
    call_kwargs = agent.local_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "llama3.2"
