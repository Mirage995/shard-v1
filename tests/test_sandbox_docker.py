"""
Tests for DockerSandboxRunner — hardened Docker sandbox extracted into sandbox_runner.py.

Covers: _build_docker_command, _validate_sandbox_path, run(), _ensure_sandbox_image,
        banned pattern filter, container uniqueness.
"""
import asyncio
import os
import subprocess
import sys
import uuid

import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from sandbox_runner import DockerSandboxRunner


SAMPLE_CODE = "print('Hello from sandbox')"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def runner(tmp_path):
    """DockerSandboxRunner with tmp sandbox dir, image pre-marked as checked."""
    sandbox_dir = str(tmp_path / "sandbox")
    os.makedirs(sandbox_dir, exist_ok=True)
    r = DockerSandboxRunner(sandbox_dir=sandbox_dir, analysis_fn=None)
    r._image_checked = True  # skip docker image inspect in tests
    return r


# ── _build_docker_command ─────────────────────────────────────────────────────

class TestBuildDockerCommand:

    def test_contains_all_required_flags(self, runner):
        """All mandatory Docker hardening flags must be present."""
        cmd = runner._build_docker_command("/fake/sandbox", "test.py", "test-container")
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

    def test_image_is_custom(self, runner):
        """Must use shard-sandbox:latest, not a generic python image."""
        cmd = runner._build_docker_command("/fake", "test.py", "c1")
        assert "shard-sandbox:latest" in cmd
        assert "python:3.10-slim" not in cmd

    def test_mount_path_posix_format(self, runner, tmp_path):
        """The -v mount path must use forward slashes (Windows compat)."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir(exist_ok=True)
        posix_path = sandbox.resolve().as_posix()
        cmd = runner._build_docker_command(posix_path, "test.py", "c1")
        v_idx = cmd.index("-v")
        mount_arg = cmd[v_idx + 1]
        assert "\\" not in mount_arg, "Mount path must not contain backslashes"
        assert ":/app:rw" in mount_arg

    def test_container_name_in_command(self, runner):
        """Container name passed as argument must appear in the command."""
        cmd = runner._build_docker_command("/fake", "test.py", "my-unique-container")
        assert "my-unique-container" in cmd


# ── Container name uniqueness ─────────────────────────────────────────────────

def test_container_name_unique():
    """Each sandbox invocation must generate a unique container name."""
    names = {f"shard-sandbox-{uuid.uuid4().hex[:12]}" for _ in range(100)}
    assert len(names) == 100


# ── _validate_sandbox_path ────────────────────────────────────────────────────

class TestValidateSandboxPath:

    def test_returns_absolute_path(self, runner, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir(exist_ok=True)
        result = runner._validate_sandbox_path(str(sandbox))
        assert result.is_absolute()

    def test_no_dotdot_in_result(self, runner, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir(exist_ok=True)
        result = runner._validate_sandbox_path(str(sandbox))
        assert ".." not in str(result)

    def test_traversal_rejected(self, runner, tmp_path):
        """Paths escaping the sandbox parent via '../' must be rejected."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir(exist_ok=True)
        evil_path = str(sandbox / ".." / ".." / ".." / "etc")
        with pytest.raises(ValueError, match="[Tt]raversal"):
            runner._validate_sandbox_path(evil_path)


# ── run() ─────────────────────────────────────────────────────────────────────

class TestRun:

    def test_successful_execution(self, runner):
        """Normal execution returns success=True with stdout and code."""
        def mock_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="Hello from sandbox\n", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(runner.run("test topic", SAMPLE_CODE))

        assert result["success"] is True
        assert "Hello from sandbox" in result["stdout"]
        assert result["code"] == SAMPLE_CODE

    def test_docker_failure_returns_error(self, runner):
        """Non-zero Docker exit code must result in success=False."""
        def mock_run(cmd, **kwargs):
            return MagicMock(returncode=1, stdout="", stderr="SyntaxError: invalid syntax")

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(runner.run("test topic", "invalid python!!!"))

        assert result["success"] is False
        assert "SyntaxError" in result["stderr"]

    def test_timeout_triggers_docker_kill(self, runner):
        """TimeoutExpired must trigger docker kill with the correct container name."""
        call_log = []

        def mock_run(cmd, **kwargs):
            call_log.append(list(cmd))
            if cmd[:2] == ["docker", "run"]:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(runner.run("test topic", SAMPLE_CODE))

        assert result["success"] is False
        assert "Timeout" in result["stderr"]
        kill_calls = [c for c in call_log if c[:2] == ["docker", "kill"]]
        assert len(kill_calls) == 1, "docker kill must be called exactly once on timeout"
        assert kill_calls[0][2].startswith("shard-sandbox-")

    def test_kill_failure_swallowed(self, runner):
        """If docker kill itself fails, the error must be silently absorbed."""
        def mock_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "run"]:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)
            if cmd[:2] == ["docker", "kill"]:
                raise OSError("Docker daemon not responding")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(runner.run("test topic", SAMPLE_CODE))

        assert result["success"] is False
        assert "Timeout" in result["stderr"]

    def test_output_truncation(self, runner):
        """stdout and stderr exceeding MAX_OUTPUT_CHARS must be truncated."""
        long_output = "x" * 100_000

        def mock_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout=long_output, stderr=long_output)

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(runner.run("test topic", SAMPLE_CODE))

        assert len(result["stdout"]) <= DockerSandboxRunner.MAX_OUTPUT_CHARS
        assert len(result["stderr"]) <= DockerSandboxRunner.MAX_OUTPUT_CHARS

    def test_analysis_fn_called_on_success(self, tmp_path):
        """analysis_fn must be called and its result stored in 'analysis'."""
        sandbox_dir = str(tmp_path / "sandbox")
        os.makedirs(sandbox_dir, exist_ok=True)

        async def mock_analysis(prompt):
            return "mocked analysis"

        r = DockerSandboxRunner(sandbox_dir=sandbox_dir, analysis_fn=mock_analysis)
        r._image_checked = True

        def mock_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="ok", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(r.run("test topic", SAMPLE_CODE))

        assert result["analysis"] == "mocked analysis"

    def test_analysis_skipped_when_none(self, runner):
        """analysis_fn=None must produce 'Analysis skipped.' in result."""
        def mock_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="ok", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(runner.run("test topic", SAMPLE_CODE))

        assert result["analysis"] == "Analysis skipped."

    def test_result_contains_file_path(self, runner):
        """Successful run must include 'file_path' in result."""
        def mock_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="ok", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(runner.run("test topic", SAMPLE_CODE))

        assert "file_path" in result
        assert result["file_path"] is not None


# ── _ensure_sandbox_image ─────────────────────────────────────────────────────

class TestEnsureSandboxImage:

    def test_image_check_runs_once(self, tmp_path):
        """_ensure_sandbox_image must only call docker image inspect once per instance."""
        sandbox_dir = str(tmp_path / "sandbox2")
        os.makedirs(sandbox_dir, exist_ok=True)
        r = DockerSandboxRunner(sandbox_dir=sandbox_dir)

        call_count = [0]

        def mock_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "image"]:
                call_count[0] += 1
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            asyncio.run(r._ensure_sandbox_image())
            # Second call: _image_checked is True, must short-circuit
            asyncio.run(r._ensure_sandbox_image())

        assert call_count[0] == 1

    def test_missing_image_raises_runtime_error(self, tmp_path):
        """If docker build fails, RuntimeError must be raised."""
        sandbox_dir = str(tmp_path / "sandbox3")
        os.makedirs(sandbox_dir, exist_ok=True)
        r = DockerSandboxRunner(sandbox_dir=sandbox_dir)

        def mock_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd, stderr="build failed")

        with patch("subprocess.run", side_effect=mock_run):
            with pytest.raises(RuntimeError, match="Failed to automatically build"):
                asyncio.run(r._ensure_sandbox_image())

    def test_missing_image_propagates_to_run(self, tmp_path):
        """If image build fails, run() must return success=False with clear message."""
        sandbox_dir = str(tmp_path / "sandbox4")
        os.makedirs(sandbox_dir, exist_ok=True)
        r = DockerSandboxRunner(sandbox_dir=sandbox_dir)

        def mock_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd, stderr="Simulated build failure")

        with patch("subprocess.run", side_effect=mock_run):
            result = asyncio.run(r.run("test topic", SAMPLE_CODE))

        assert result["success"] is False
        assert result["stderr"] != ""


# ── Banned patterns ───────────────────────────────────────────────────────────

class TestBannedPatterns:

    @pytest.mark.parametrize("pattern", [
        "serve_forever",
        "HTTPServer(",
        "app.run(",
        "uvicorn.run(",
        "Flask(__name__)",
        ".listen(",
        "while True",
    ])
    def test_persistent_server_pattern_blocked(self, runner, pattern):
        """Code containing persistent server patterns must be blocked before execution."""
        code = f"import something\n{pattern}\nprint('done')"
        result = asyncio.run(runner.run("test", code))
        assert result["success"] is False
        assert result.get("error") == "persistent_server_detected"
        assert result.get("pattern") == pattern


if __name__ == "__main__":
    import pytest as _pt
    _pt.main([__file__, "-v"])
