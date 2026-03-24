import importlib
import sys
from pathlib import Path

import pytest

TASK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK_DIR))

COORDS = {"lat": 40.7128, "lon": -74.0060}
EXPECTED = round(40.7128 + (-74.0060), 6)  # -33.2932


@pytest.fixture(scope="session", autouse=True)
def _setup():
    # Reset state once at session start — state accumulates across all 10 tests
    import state_manager
    state_manager.reset()
    yield


def _proc():
    # Reload only fixed_processor; keep state_manager alive so _n accumulates
    sys.modules.pop("fixed_processor", None)
    spec = TASK_DIR / "fixed_processor.py"
    if not spec.exists():
        pytest.fail("fixed_processor.py not found")
    return importlib.import_module("fixed_processor")


class TestSequential:
    def test_c01(self): assert _proc().process(COORDS) == EXPECTED
    def test_c02(self): assert _proc().process(COORDS) == EXPECTED
    def test_c03(self): assert _proc().process(COORDS) == EXPECTED
    def test_c04(self): assert _proc().process(COORDS) == EXPECTED
    def test_c05(self): assert _proc().process(COORDS) == EXPECTED
    def test_c06(self): assert _proc().process(COORDS) == EXPECTED
    def test_c07(self): assert _proc().process(COORDS) == EXPECTED
    def test_c08(self): assert _proc().process(COORDS) == EXPECTED
    def test_c09(self): assert _proc().process(COORDS) == EXPECTED
    def test_c10(self): assert _proc().process(COORDS) == EXPECTED


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
