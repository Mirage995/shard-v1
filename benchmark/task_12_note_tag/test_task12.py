"""Tests for note tag detector — based on pylint-dev/pylint#5859"""
import importlib
import sys
from pathlib import Path
import pytest

TASK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK_DIR))


def _proc():
    sys.modules.pop("fixed_processor", None)
    spec = TASK_DIR / "fixed_processor.py"
    if not spec.exists():
        pytest.fail("fixed_processor.py not found")
    return importlib.import_module("fixed_processor")


def test_alphanumeric_tag_found():
    tags = _proc().find_tags("a = 1  # TODO: fix this", ["TODO"])
    assert tags == ["TODO"]


def test_alphanumeric_tag_no_space():
    tags = _proc().find_tags("a = 1  #TODO: fix this", ["TODO"])
    assert tags == ["TODO"]


def test_punctuation_tag_found():
    """Punctuation-only tags must be detected — \\b doesn't work after non-word chars."""
    tags = _proc().find_tags("a = 1  # ???: check this", ["???"])
    assert tags == ["???"], f"Punctuation tag '???' not found, got: {tags}"


def test_punctuation_tag_no_space():
    tags = _proc().find_tags("a = 1  #???: check this", ["???"])
    assert tags == ["???"]


def test_punctuation_tag_end_of_line():
    tags = _proc().find_tags("a = 1  # ???", ["???"])
    assert tags == ["???"]


def test_mixed_tags():
    source = "# YES: ok\n# ???: hmm\n# FIXME: broken"
    tags = _proc().find_tags(source, ["YES", "???", "FIXME"])
    assert set(tags) == {"YES", "???", "FIXME"}


def test_tag_not_matched_mid_word():
    """TODO inside a word should NOT match."""
    tags = _proc().find_tags("# TODOLIST: nope", ["TODO"])
    assert tags == []


def test_multiple_punctuation_tags():
    source = "# !!!: urgent\n# ???: unknown"
    tags = _proc().find_tags(source, ["!!!", "???"])
    assert len(tags) == 2


def test_no_match_empty_source():
    assert _proc().find_tags("", ["TODO"]) == []


def test_case_insensitive():
    tags = _proc().find_tags("# todo: something", ["TODO"])
    assert tags == ["todo"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
