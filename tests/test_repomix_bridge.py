"""
Tests for backend/repomix_bridge.py
"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess
import os

from backend.repomix_bridge import ingest_repo, RepomixError


# --- Helpers ---

def _make_run_result(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# --- npx not installed ---

def test_no_npx_raises(tmp_path):
    with patch("shutil.which", return_value=None):
        with pytest.raises(RepomixError, match="npx not found"):
            ingest_repo("https://github.com/foo/bar")


# --- Remote URL happy path ---

def test_remote_url_returns_content(tmp_path):
    fake_content = "<repo>hello world</repo>"

    def fake_run(cmd, **kwargs):
        # Write fake output file
        output_flag_idx = cmd.index("--output")
        output_path = cmd[output_flag_idx + 1]
        with open(output_path, "w") as f:
            f.write(fake_content)
        return _make_run_result(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/npx"):
        with patch("subprocess.run", side_effect=fake_run):
            result = ingest_repo("https://github.com/foo/bar")

    assert result == fake_content


# --- Remote URL: --remote flag present ---

def test_remote_url_uses_remote_flag():
    captured_cmd = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        output_flag_idx = cmd.index("--output")
        output_path = cmd[output_flag_idx + 1]
        with open(output_path, "w") as f:
            f.write("content")
        return _make_run_result(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/npx"):
        with patch("subprocess.run", side_effect=fake_run):
            ingest_repo("https://github.com/foo/bar")

    assert "--remote" in captured_cmd
    assert "https://github.com/foo/bar" in captured_cmd


# --- Local path happy path ---

def test_local_path_returns_content(tmp_path):
    fake_content = "# local repo packed"
    local_repo = tmp_path / "myrepo"
    local_repo.mkdir()

    def fake_run(cmd, **kwargs):
        output_flag_idx = cmd.index("--output")
        output_path = cmd[output_flag_idx + 1]
        with open(output_path, "w") as f:
            f.write(fake_content)
        return _make_run_result(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/npx"):
        with patch("subprocess.run", side_effect=fake_run):
            result = ingest_repo(str(local_repo))

    assert result == fake_content


# --- Local path: does not use --remote flag ---

def test_local_path_no_remote_flag(tmp_path):
    local_repo = tmp_path / "myrepo"
    local_repo.mkdir()
    captured_cmd = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        output_flag_idx = cmd.index("--output")
        output_path = cmd[output_flag_idx + 1]
        with open(output_path, "w") as f:
            f.write("x")
        return _make_run_result(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/npx"):
        with patch("subprocess.run", side_effect=fake_run):
            ingest_repo(str(local_repo))

    assert "--remote" not in captured_cmd


# --- Local path not found ---

def test_local_path_not_found():
    with patch("shutil.which", return_value="/usr/bin/npx"):
        with pytest.raises(RepomixError, match="Local path not found"):
            ingest_repo("/nonexistent/path/that/does/not/exist")


# --- Repomix exits with error ---

def test_repomix_nonzero_exit_raises():
    def fake_run(cmd, **kwargs):
        return _make_run_result(returncode=1, stderr="repo not found")

    with patch("shutil.which", return_value="/usr/bin/npx"):
        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(RepomixError, match="Repomix failed"):
                ingest_repo("https://github.com/foo/bar")


# --- Timeout ---

def test_timeout_raises():
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 120)

    with patch("shutil.which", return_value="/usr/bin/npx"):
        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(RepomixError, match="timed out"):
                ingest_repo("https://github.com/foo/bar")


# --- No output file produced ---

def test_no_output_file_raises():
    def fake_run(cmd, **kwargs):
        # Don't write the output file
        return _make_run_result(returncode=0, stdout="done")

    with patch("shutil.which", return_value="/usr/bin/npx"):
        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(RepomixError, match="no output file"):
                ingest_repo("https://github.com/foo/bar")


# --- Output format forwarded ---

def test_output_format_forwarded():
    captured_cmd = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        output_flag_idx = cmd.index("--output")
        output_path = cmd[output_flag_idx + 1]
        with open(output_path, "w") as f:
            f.write("content")
        return _make_run_result(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/npx"):
        with patch("subprocess.run", side_effect=fake_run):
            ingest_repo("https://github.com/foo/bar", output_format="markdown")

    assert "--style" in captured_cmd
    assert "markdown" in captured_cmd
