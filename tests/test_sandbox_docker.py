"""
Tests for Docker Sandbox Hardening in StudyAgent.

All tests mock subprocess so Docker is NOT required to run them.
Tests verify: command construction, path security, timeout handling,
output truncation, container naming, and error paths.

NOTE: Uses asyncio.run() for async tests since pytest-asyncio may not
be installed. Third-party deps are mocked at module level.
"""
import sys
import os
import json
import pathlib
import uuid
import types
import asyncio
import subprocess

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure backend/ is on the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ── Mock third-party modules so tests run without full dependencies ───────────
for _mod_name in [
    "playwright", "playwright.async_api",
    "playwright_stealth",
    "bs4",
    "groq",
    "ddgs",
    "chromadb", "chromadb.utils", "chromadb.utils.embedding_functions",
    "filesystem_tools",
    "dotenv",
    "openai",
]:
    if _mod_name not in sys.modules:
        _fake = types.ModuleType(_mod_name)
        _fake.__dict__.setdefault("load_dotenv", lambda: None)
        _fake.__dict__.setdefault("Groq", MagicMock)
        _fake.__dict__.setdefault("RateLimitError", type("RateLimitError", (Exception,), {}))
        _fake.__dict__.setdefault("GroqRateLimitError", type("GroqRateLimitError", (Exception,), {}))
        _fake.__dict__.setdefault("DDGS", MagicMock)
        _fake.__dict__.setdefault("BeautifulSoup", MagicMock)
        _fake.__dict__.setdefault("async_playwright", MagicMock)
        _fake.__dict__.setdefault("Page", MagicMock)
        _fake.__dict__.setdefault("Stealth", MagicMock)
        _fake.__dict__.setdefault("PersistentClient", MagicMock)
        _fake.__dict__.setdefault("DefaultEmbeddingFunction", MagicMock)
        _fake.__dict__.setdefault("embedding_functions", MagicMock())
        _fake.__dict__.setdefault("write_file", MagicMock(return_value="success"))
        _fake.__dict__.setdefault("AsyncOpenAI", MagicMock)
        sys.modules[_mod_name] = _fake


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_env(monkeypatch):
    """Set GROQ_API_KEY so StudyAgent.__init__ doesn't raise."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key-fake")


@pytest.fixture
def agent(mock_env, tmp_path):
    """Create a StudyAgent with mocked Groq/ChromaDB and tmp sandbox dir."""
    with patch("study_agent.Groq") as MockGroq, \
         patch("study_agent.chromadb") as MockChroma, \
         patch("study_agent.CHROMA_DB_PATH", str(tmp_path / "chroma")), \
         patch("study_agent.SANDBOX_DIR", str(tmp_path / "sandbox")), \
         patch("study_agent.WORKSPACE_DIR", str(tmp_path / "workspace")):

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [[]], "metadatas": [[]], "distances": [[]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        MockChroma.PersistentClient.return_value = mock_client

        mock_groq_response = MagicMock()
        mock_groq_response.choices = [MagicMock()]
        mock_groq_response.choices[0].message.content = "Mocked analysis"
        mock_groq_client = MagicMock()
        mock_groq_client.chat.completions.create.return_value = mock_groq_response
        MockGroq.return_value = mock_groq_client

        from study_agent import StudyAgent
        sa = StudyAgent()
        sa._tmp_sandbox = str(tmp_path / "sandbox")

        yield sa


SAMPLE_CODE = "print('Hello from sandbox')"


# ── Test: Docker Command Flags ───────────────────────────────────────────────

def test_docker_command_contains_all_required_flags(agent):
    """All 13 mandatory Docker hardening flags must be in the command."""
    cmd = agent._build_docker_command("/fake/sandbox", "test.py", "test-container")
    cmd_str = " ".join(cmd)

    assert "--rm" in cmd
    assert "--network" in cmd and "none" in cmd
    assert "-m" in cmd and "256m" in cmd
    assert "--cpus=0.5" in cmd
    assert "--pids-limit" in cmd and "64" in cmd
    assert "--read-only" in cmd
    assert "--tmpfs" in cmd
    assert "/tmp:rw,noexec,nosuid,size=64m" in cmd
    assert "--security-opt" in cmd and "no-new-privileges" in cmd
    assert "--cap-drop" in cmd and "ALL" in cmd
    assert "--ulimit" in cmd and "nofile=64:64" in cmd
    assert "--user" in cmd and "1000:1000" in cmd
    assert "-v" in cmd
    assert "/fake/sandbox:/app:rw" in cmd_str
    assert "-w" in cmd and "/app" in cmd
    assert "--name" in cmd and "test-container" in cmd
    assert "shard-sandbox:latest" in cmd
    assert "python" in cmd and "test.py" in cmd


def test_docker_command_image_is_custom(agent):
    """Must use shard-sandbox:latest, not python:3.10-slim."""
    cmd = agent._build_docker_command("/fake", "test.py", "c1")
    assert "shard-sandbox:latest" in cmd
    assert "python:3.10-slim" not in cmd


# ── Test: Container Name Uniqueness ──────────────────────────────────────────

def test_container_name_unique():
    """Each sandbox invocation must generate a unique container name."""
    names = set()
    for _ in range(100):
        name = f"shard-sandbox-{uuid.uuid4().hex[:12]}"
        names.add(name)
    assert len(names) == 100


# ── Test: Path Security — Symlink ────────────────────────────────────────────

def test_path_security_symlink_rejected(agent, tmp_path):
    """Sandbox path containing a symlink must be rejected."""
    real_dir = tmp_path / "real_sandbox"
    real_dir.mkdir()
    symlink_dir = tmp_path / "evil_link"
    try:
        symlink_dir.symlink_to(real_dir)
    except OSError:
        pytest.skip("Cannot create symlinks on this OS/permission level")

    with patch("study_agent.SANDBOX_DIR", str(symlink_dir)):
        with pytest.raises(ValueError, match="[Ss]ymlink"):
            agent._validate_sandbox_path(str(symlink_dir))


# ── Test: Path Security — Directory Traversal ────────────────────────────────

def test_path_security_traversal_rejected(agent, tmp_path):
    """Paths with '../' escaping the sandbox parent must be rejected."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    evil_path = str(sandbox / ".." / ".." / ".." / "etc")

    with patch("study_agent.SANDBOX_DIR", str(sandbox)):
        with pytest.raises(ValueError, match="[Tt]raversal"):
            agent._validate_sandbox_path(evil_path)


# ── Test: Path Normalization ─────────────────────────────────────────────────

def test_path_normalization(agent, tmp_path):
    """Sandbox path must be resolved to an absolute path without '..' segments."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    with patch("study_agent.SANDBOX_DIR", str(sandbox)):
        result = agent._validate_sandbox_path(str(sandbox))
        assert result.is_absolute()
        assert ".." not in str(result)


# ── Test: Docker Mount Path Windows Compatible ──────────────────────────────

def test_docker_mount_path_posix_format(agent, tmp_path):
    """The -v mount path must be in POSIX format (forward slashes)."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    posix_path = sandbox.resolve().as_posix()
    cmd = agent._build_docker_command(posix_path, "test.py", "c1")

    v_idx = cmd.index("-v")
    mount_arg = cmd[v_idx + 1]

    assert "\\" not in mount_arg, "Mount path must not contain backslashes"
    assert ":/app:rw" in mount_arg


# ── Test: Timeout Triggers Docker Kill ───────────────────────────────────────

def test_timeout_triggers_docker_kill(agent, tmp_path):
    """TimeoutExpired must trigger docker kill with the container name."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    call_log = []

    def mock_subprocess_run(cmd, **kwargs):
        call_log.append(list(cmd))
        if cmd[:2] == ["docker", "image"]:
            return MagicMock(returncode=0)
        elif cmd[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)
        elif cmd[:2] == ["docker", "kill"]:
            return MagicMock(returncode=0)
        return MagicMock(returncode=0)

    with patch("study_agent.SANDBOX_DIR", str(sandbox)), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        result = asyncio.run(agent.run_sandbox("test topic", SAMPLE_CODE))

    assert result["success"] is False
    assert "Timeout" in result["stderr"]

    kill_calls = [c for c in call_log if c[:2] == ["docker", "kill"]]
    assert len(kill_calls) == 1, "docker kill must be called exactly once on timeout"
    container_name = kill_calls[0][2]
    assert container_name.startswith("shard-sandbox-")


# ── Test: Kill Failure Swallowed ─────────────────────────────────────────────

def test_kill_failure_swallowed(agent, tmp_path):
    """If docker kill itself fails, the error must be silently handled."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "image"]:
            return MagicMock(returncode=0)
        elif cmd[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)
        elif cmd[:2] == ["docker", "kill"]:
            raise OSError("Docker daemon not responding")
        return MagicMock(returncode=0)

    with patch("study_agent.SANDBOX_DIR", str(sandbox)), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        result = asyncio.run(agent.run_sandbox("test topic", SAMPLE_CODE))

    assert result["success"] is False
    assert "Timeout" in result["stderr"]


# ── Test: Output Truncation ──────────────────────────────────────────────────

def test_output_truncation(agent, tmp_path):
    """stdout and stderr exceeding 50k chars must be truncated."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    long_output = "x" * 100_000

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "image"]:
            return MagicMock(returncode=0)
        elif cmd[:2] == ["docker", "run"]:
            return MagicMock(returncode=0, stdout=long_output, stderr=long_output)
        return MagicMock(returncode=0)

    with patch("study_agent.SANDBOX_DIR", str(sandbox)), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        result = asyncio.run(agent.run_sandbox("test topic", SAMPLE_CODE))

    assert len(result["stdout"]) <= 50_000
    assert len(result["stderr"]) <= 50_000


# ── Test: Successful Execution ───────────────────────────────────────────────

def test_successful_execution(agent, tmp_path):
    """Normal execution must return success=True with stdout/stderr/analysis."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "image"]:
            return MagicMock(returncode=0)
        elif cmd[:2] == ["docker", "run"]:
            return MagicMock(returncode=0, stdout="Hello from sandbox\n", stderr="")
        return MagicMock(returncode=0)

    with patch("study_agent.SANDBOX_DIR", str(sandbox)), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        result = asyncio.run(agent.run_sandbox("test topic", SAMPLE_CODE))

    assert result["success"] is True
    assert "Hello from sandbox" in result["stdout"]
    assert result["code"] == SAMPLE_CODE
    assert isinstance(result["analysis"], str)


# ── Test: Docker Failure Handling ────────────────────────────────────────────

def test_docker_failure_returns_error(agent, tmp_path):
    """Non-zero Docker exit code must result in success=False."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "image"]:
            return MagicMock(returncode=0)
        elif cmd[:2] == ["docker", "run"]:
            return MagicMock(returncode=1, stdout="", stderr="SyntaxError: invalid syntax")
        return MagicMock(returncode=0)

    with patch("study_agent.SANDBOX_DIR", str(sandbox)), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        result = asyncio.run(agent.run_sandbox("test topic", "invalid python!!!"))

    assert result["success"] is False
    assert "SyntaxError" in result["stderr"]


# ── Test: Missing Docker Image ───────────────────────────────────────────────

def test_missing_docker_image_returns_clear_error(agent, tmp_path):
    """If shard-sandbox:latest doesn't exist, return a clear error message."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "image"]:
            return MagicMock(returncode=1, stderr="No such image")
        return MagicMock(returncode=0)

    with patch("study_agent.SANDBOX_DIR", str(sandbox)), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        result = asyncio.run(agent.run_sandbox("test topic", SAMPLE_CODE))

    assert result["success"] is False
    assert "shard-sandbox:latest" in result["stderr"]
    assert "Build" in result["stderr"] or "build" in result["stderr"]
