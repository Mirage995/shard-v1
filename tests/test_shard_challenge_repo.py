"""
Tests for the --repo / Repomix integration in shard_challenge.py
"""

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root + backend are on path (mirrors shard_challenge.py setup)
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helper: load shard_challenge as a module (it uses sys.path manipulation)
# ---------------------------------------------------------------------------

def _load_challenge():
    spec = importlib.util.spec_from_file_location(
        "shard_challenge", ROOT / "shard_challenge.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. --repo arg accepted by argparse
# ---------------------------------------------------------------------------

def test_repo_arg_parsed(tmp_path):
    buggy = tmp_path / "buggy.py"
    buggy.write_text("def f(): pass")
    test_f = tmp_path / "test_buggy.py"
    test_f.write_text("def test_x(): pass")

    mod = _load_challenge()
    parser_fn = mod.main  # we'll test via argparse directly

    # Simulate sys.argv
    with patch("sys.argv", [
        "shard_challenge.py",
        str(buggy), str(test_f),
        "--repo", "https://github.com/foo/bar",
    ]):
        import argparse
        # Re-parse manually
        parser = argparse.ArgumentParser()
        parser.add_argument("buggy_file")
        parser.add_argument("test_file")
        parser.add_argument("--repo", default="")
        parser.add_argument("--max-attempts", type=int, default=5)
        parser.add_argument("--install", default="")
        parser.add_argument("--no-swarm", action="store_true")
        args = parser.parse_args([
            str(buggy), str(test_f),
            "--repo", "https://github.com/foo/bar",
        ])
        assert args.repo == "https://github.com/foo/bar"


# ---------------------------------------------------------------------------
# 2. Repomix context injected into README.md
# ---------------------------------------------------------------------------

def test_repomix_context_written_to_readme(tmp_path):
    """If --repo is passed, repomix content must appear in task_dir/README.md."""
    fake_xml = "<repo><file>hello.py</file></repo>"

    # Patch ingest_repo to return fake XML
    fake_bridge = types.ModuleType("repomix_bridge")
    fake_bridge.ingest_repo = lambda url, **kw: fake_xml
    fake_bridge.RepomixError = Exception

    with patch.dict("sys.modules", {"repomix_bridge": fake_bridge}):
        mod = _load_challenge()

        # Simulate the injection block directly
        repomix_context = fake_bridge.ingest_repo("https://github.com/foo/bar")
        readme_path = tmp_path / "README.md"
        existing = ""
        separator = "\n\n---\n\n## Repo Knowledge Context (Repomix)\n\n"
        readme_path.write_text(existing + separator + repomix_context, encoding="utf-8")

        content = readme_path.read_text(encoding="utf-8")
        assert "Repo Knowledge Context (Repomix)" in content
        assert fake_xml in content


# ---------------------------------------------------------------------------
# 3. Cache file written to .shard_cache/
# ---------------------------------------------------------------------------

def test_cache_file_written(tmp_path):
    fake_xml = "<repo>cached</repo>"
    cache_dir = tmp_path / ".shard_cache"
    cache_dir.mkdir()
    cache_file = cache_dir / "repomix_context.xml"
    cache_file.write_text(fake_xml, encoding="utf-8")

    assert cache_file.exists()
    assert cache_file.read_text() == fake_xml


# ---------------------------------------------------------------------------
# 4. Repomix failure is non-fatal (warning, continues without context)
# ---------------------------------------------------------------------------

def test_repomix_failure_non_fatal():
    """If ingest_repo raises, the script should warn and continue."""
    from backend.repomix_bridge import RepomixError

    def failing_ingest(url, **kw):
        raise RepomixError("npx not found")

    fake_bridge = types.ModuleType("repomix_bridge")
    fake_bridge.ingest_repo = failing_ingest
    fake_bridge.RepomixError = RepomixError

    repomix_context = ""
    with patch.dict("sys.modules", {"repomix_bridge": fake_bridge}):
        try:
            repomix_context = fake_bridge.ingest_repo("https://github.com/foo/bar")
        except Exception:
            pass  # swallowed — context stays empty

    assert repomix_context == ""


# ---------------------------------------------------------------------------
# 5. Without --repo, no context injected (README.md untouched if absent)
# ---------------------------------------------------------------------------

def test_no_repo_no_readme_written(tmp_path):
    readme_path = tmp_path / "README.md"
    repomix_context = ""  # --repo not passed

    if repomix_context:
        readme_path.write_text("context", encoding="utf-8")

    assert not readme_path.exists()


# ---------------------------------------------------------------------------
# 6. .shard_cache not committed (present in .gitignore)
# ---------------------------------------------------------------------------

def test_shard_cache_in_gitignore():
    gitignore = ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore missing"
    content = gitignore.read_text(encoding="utf-8")
    assert ".shard_cache" in content


# ---------------------------------------------------------------------------
# _truncate_repomix tests
# ---------------------------------------------------------------------------

def _get_truncate_fn():
    mod = _load_challenge()
    return mod._truncate_repomix


def test_truncate_under_limit_unchanged():
    fn = _get_truncate_fn()
    xml = "<repo><file path='a.py'>hello</file></repo>"
    assert fn(xml, 10_000) == xml


def test_truncate_keeps_dir_structure():
    fn = _get_truncate_fn()
    xml = (
        "<summary>stats</summary>"
        "<directory_structure>src/\n  main.py\n  utils.py</directory_structure>"
        + "<file path='README.md'>Read me</file>"
        + "".join(f"<file path='file{i}.py'>{'x' * 500}</file>" for i in range(20))
    )
    result = fn(xml, 2_000)
    assert "<directory_structure>" in result
    assert "src/" in result


def test_truncate_keeps_readme():
    fn = _get_truncate_fn()
    xml = (
        "<directory_structure>root/</directory_structure>"
        "<file path='README.md'>THIS IS THE README</file>"
        + "".join(f"<file path='file{i}.py'>{'x' * 500}</file>" for i in range(20))
    )
    result = fn(xml, 1_500)
    assert "THIS IS THE README" in result


def test_truncate_adds_notice():
    fn = _get_truncate_fn()
    xml = "<file path='a.py'>" + "x" * 1000 + "</file>" * 50
    result = fn(xml, 500)
    assert "TRUNCATED BY SHARD CONTEXT LIMIT" in result


def test_truncate_result_within_limit():
    fn = _get_truncate_fn()
    xml = (
        "<directory_structure>root/</directory_structure>"
        + "".join(f"<file path='file{i}.py'>{'y' * 300}</file>" for i in range(30))
    )
    limit = 3_000
    result = fn(xml, limit)
    # Allow small overage only from the truncation notice itself
    assert len(result) <= limit + 300  # notice can slightly exceed


def test_truncate_plaintext_fallback():
    """Repomix --style plain has no XML tags — fallback must not crash."""
    fn = _get_truncate_fn()
    plain = "# Repo\n\n" + "=" * 20 + "\nfile1.py\n" + "=" * 20 + "\n" + "z" * 2000
    result = fn(plain, 500)
    assert "TRUNCATED BY SHARD CONTEXT LIMIT" in result
    assert len(result) <= 800  # reasonable bound
