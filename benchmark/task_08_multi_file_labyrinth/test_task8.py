import importlib
import json
import sys
from pathlib import Path

import pytest

TASK_DIR = Path(__file__).resolve().parent
CFG = TASK_DIR / "config.json"
sys.path.insert(0, str(TASK_DIR))


def _cfg(raw_mode: bool, value: int = 42):
    CFG.write_text(json.dumps({"raw_mode": raw_mode, "value": value}))


def _proc():
    for m in ("database", "fixed_processor"):
        sys.modules.pop(m, None)
    spec = TASK_DIR / "fixed_processor.py"
    if not spec.exists():
        pytest.fail("fixed_processor.py not found")
    return importlib.import_module("fixed_processor")


@pytest.fixture(autouse=True)
def _reset():
    yield
    _cfg(True)
    for m in ("database", "fixed_processor"):
        sys.modules.pop(m, None)


class TestModeA:
    def test_a1(self):
        _cfg(False, 42)
        assert _proc().process() == 84

    def test_a2(self):
        _cfg(False, 10)
        assert _proc().process() == 20

    def test_a3(self):
        _cfg(False, 0)
        assert _proc().process() == 0

    def test_a4(self):
        _cfg(False, 100)
        assert _proc().process() == 200

    def test_a5(self):
        _cfg(False, 7)
        assert _proc().process() == 14


class TestModeB:
    def test_b1(self):
        _cfg(True, 42)
        assert _proc().process() == 84

    def test_b2(self):
        _cfg(True, 10)
        assert _proc().process() == 20

    def test_b3(self):
        _cfg(True, 0)
        assert _proc().process() == 0

    def test_b4(self):
        _cfg(True, 100)
        assert _proc().process() == 200

    def test_b5(self):
        _cfg(True, 7)
        assert _proc().process() == 14


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
