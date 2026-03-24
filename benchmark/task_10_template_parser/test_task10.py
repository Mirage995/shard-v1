"""Tests for template parser — based on pylint-dev/pylint#7993"""
import warnings
from pathlib import Path
import sys
import importlib
import pytest

TASK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK_DIR))


def _proc():
    sys.modules.pop("fixed_processor", None)
    spec = TASK_DIR / "fixed_processor.py"
    if not spec.exists():
        pytest.fail("fixed_processor.py not found")
    return importlib.import_module("fixed_processor")


def test_simple_field():
    assert _proc().parse_template("{category}") == ["category"]


def test_format_spec():
    assert _proc().parse_template("{line:03d}") == ["line"]


def test_multiple_fields():
    result = _proc().parse_template("{path}:{line}:{category}")
    assert result == ["path", "line", "category"]


def test_custom_braces_json_style():
    """{{ }} are escaped braces — should NOT be parsed as fields."""
    result = _proc().parse_template('{{ "Category": "{category}" }}')
    assert result == ["category"], f"Got {result} — escaped braces must not be parsed as fields"


def test_custom_braces_no_false_warnings():
    """No warnings should be emitted for escaped braces."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _proc().parse_template('{{ "Category": "{category}" }}')
    assert len(w) == 0, f"Unexpected warnings: {[str(x.message) for x in w]}"


def test_unknown_field_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _proc().parse_template("{nonexistent_field}")
    assert len(w) == 1


def test_mixed_known_unknown():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = _proc().parse_template("{category}:{bad_field}")
    assert result == ["category"]
    assert len(w) == 1


def test_empty_template():
    assert _proc().parse_template("no fields here") == []


def test_format_spec_with_custom_braces():
    """Real-world template: JSON wrapper around formatted field."""
    result = _proc().parse_template('{{ "line": {line:d}, "msg": "{msg}" }}')
    assert result == ["line", "msg"]


def test_all_message_fields():
    fields = ["category", "symbol", "msg", "C", "module", "obj", "line", "col_offset", "path", "abspath"]
    template = ":".join(f"{{{f}}}" for f in fields)
    result = _proc().parse_template(template)
    assert result == fields


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
