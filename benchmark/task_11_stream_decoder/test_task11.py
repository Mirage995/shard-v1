"""Tests for stream decoder — based on psf/requests#3362"""
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


def chunks(data, size=16):
    for i in range(0, len(data), size):
        yield data[i:i+size]


def test_utf8_encoding_returns_str():
    data = "hello world".encode("utf-8")
    result = list(_proc().stream_decode_unicode(chunks(data), "utf-8"))
    assert all(isinstance(c, str) for c in result)
    assert "".join(result) == "hello world"


def test_latin1_encoding_returns_str():
    data = "café".encode("latin-1")
    result = list(_proc().stream_decode_unicode(chunks(data), "latin-1"))
    assert all(isinstance(c, str) for c in result)


def test_none_encoding_uses_apparent():
    """When encoding=None, should fall back to apparent_encoding, not yield raw bytes."""
    data = b"the content"
    result = list(_proc().stream_decode_unicode(chunks(data), None, apparent_encoding="utf-8"))
    assert all(isinstance(c, str) for c in result), \
        f"With encoding=None chunks must be str, got: {[type(c) for c in result]}"


def test_none_encoding_correct_content():
    data = "hello".encode("utf-8")
    result = list(_proc().stream_decode_unicode(chunks(data), None, apparent_encoding="utf-8"))
    assert "".join(result) == "hello"


def test_none_encoding_apparent_latin1():
    data = "naïve".encode("latin-1")
    result = list(_proc().stream_decode_unicode(chunks(data), None, apparent_encoding="latin-1"))
    assert all(isinstance(c, str) for c in result)


def test_explicit_encoding_multiline():
    text = "line1\nline2\nline3"
    data = text.encode("utf-8")
    result = "".join(_proc().stream_decode_unicode(chunks(data, 4), "utf-8"))
    assert result == text


def test_empty_iterator():
    result = list(_proc().stream_decode_unicode(iter([]), "utf-8"))
    assert result == []


def test_empty_iterator_none_encoding():
    result = list(_proc().stream_decode_unicode(iter([]), None, "utf-8"))
    assert result == []


def test_single_chunk():
    data = b"single"
    result = list(_proc().stream_decode_unicode(iter([data]), "utf-8"))
    assert "".join(result) == "single"


def test_unicode_chars_across_chunks():
    """Multi-byte char split across chunk boundary must decode correctly."""
    data = "日本語テスト".encode("utf-8")
    result = list(_proc().stream_decode_unicode(chunks(data, 3), "utf-8"))
    assert "".join(result) == "日本語テスト"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
