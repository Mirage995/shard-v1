"""Tests for Werkzeug PIN auth race condition fix.

Based on pallets/werkzeug#2916: concurrent PIN attempts bypass the
11-attempt exhaustion limit due to unsynchronized counter access.

Run with: pytest test_task4.py -v
"""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Import the fixed version ──────────────────────────────────────────────────
spec_path = Path(__file__).parent / "fixed_pin_auth.py"
if not spec_path.exists():
    pytest.skip(f"fixed_pin_auth.py not found at {spec_path}", allow_module_level=True)

from fixed_pin_auth import PinAuth


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_auth(pin="12345"):
    return PinAuth(pin)


# Replace time.sleep with a tiny yield (1ms) — fast enough for tests,
# slow enough to keep the race window open (the sleep IS the vulnerability).
_real_sleep = time.sleep  # capture BEFORE any patching


@pytest.fixture(autouse=True)
def fast_sleep():
    def _short_sleep(duration):
        _real_sleep(0.001)

    with patch("fixed_pin_auth.time.sleep", side_effect=_short_sleep):
        yield


# ── Basic correctness (single-threaded) ──────────────────────────────────────

class TestBasicAuth:

    def test_correct_pin(self):
        auth = make_auth("12345")
        result = auth.verify_pin("12345")
        assert result["auth"] is True
        assert result["exhausted"] is False

    def test_correct_pin_with_dashes(self):
        auth = make_auth("123-45")
        result = auth.verify_pin("12345")
        assert result["auth"] is True

    def test_correct_pin_with_spaces(self):
        auth = make_auth("12345")
        result = auth.verify_pin("  12345  ")
        assert result["auth"] is True

    def test_wrong_pin(self):
        auth = make_auth("12345")
        result = auth.verify_pin("99999")
        assert result["auth"] is False
        assert result["exhausted"] is False

    def test_exhaustion_after_11_failures(self):
        """After 11 wrong attempts, system must report exhausted."""
        auth = make_auth("12345")
        for i in range(11):
            result = auth.verify_pin("wrong")
            assert result["auth"] is False, f"Attempt {i+1} should not auth"

        # The 12th attempt should be exhausted
        result = auth.verify_pin("wrong")
        assert result["exhausted"] is True, (
            "After 11 failures, exhausted should be True"
        )

    def test_correct_pin_resets_counter(self):
        auth = make_auth("12345")
        for _ in range(5):
            auth.verify_pin("wrong")
        result = auth.verify_pin("12345")
        assert result["auth"] is True
        # Counter should be reset, not exhausted after more failures
        for _ in range(5):
            auth.verify_pin("wrong")
        result = auth.verify_pin("12345")
        assert result["auth"] is True

    def test_exhausted_even_with_correct_pin(self):
        """Once exhausted, even the correct PIN should not authenticate."""
        auth = make_auth("12345")
        for _ in range(11):
            auth.verify_pin("wrong")
        result = auth.verify_pin("12345")
        assert result["exhausted"] is True


# ── Concurrency tests (the actual CVE) ──────────────────────────────────────

class TestConcurrencyRace:

    def test_concurrent_attempts_respect_limit(self):
        """CVE reproduction: 150 concurrent wrong PIN attempts.

        Without synchronization, all 150 threads read _failed_pin_auth < 10
        before any thread increments it, so all 150 get non-exhausted responses.

        With proper synchronization, at most 11 should get non-exhausted.
        """
        auth = make_auth("12345")
        results = []
        lock = threading.Lock()

        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            def attempt_wrong_pin():
                r = auth.verify_pin("wrong")
                with lock:
                    results.append(r)

            with ThreadPoolExecutor(max_workers=50) as pool:
                futures = [pool.submit(attempt_wrong_pin) for _ in range(150)]
                for f in as_completed(futures):
                    f.result()
        finally:
            sys.setswitchinterval(old_interval)

        non_exhausted = [r for r in results if not r["exhausted"]]
        exhausted = [r for r in results if r["exhausted"]]

        assert len(non_exhausted) <= 11, (
            f"RACE CONDITION: {len(non_exhausted)} attempts got through "
            f"(max should be 11). {len(exhausted)} were blocked. "
            f"The counter is not properly synchronized."
        )
        assert len(exhausted) >= 139, (
            f"Only {len(exhausted)} out of 150 were blocked. "
            f"Expected at least 139 to be exhausted."
        )

    def test_concurrent_attempts_eventually_exhaust(self):
        """After concurrent barrage, system must be in exhausted state."""
        auth = make_auth("12345")

        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            def attempt():
                auth.verify_pin("wrong")

            with ThreadPoolExecutor(max_workers=30) as pool:
                list(pool.map(lambda _: attempt(), range(100)))
        finally:
            sys.setswitchinterval(old_interval)

        # After 100 attempts, system MUST be exhausted
        result = auth.verify_pin("wrong")
        assert result["exhausted"] is True, (
            "After 100 concurrent wrong attempts, system should be exhausted. "
            "The failure counter is not being incremented atomically."
        )

    def test_no_auth_leak_during_race(self):
        """No thread should receive auth=True with a wrong PIN,
        even under concurrent pressure."""
        auth = make_auth("12345")
        leaked = []
        lock = threading.Lock()

        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            def attempt():
                r = auth.verify_pin("wrong")
                if r["auth"]:
                    with lock:
                        leaked.append(r)

            with ThreadPoolExecutor(max_workers=50) as pool:
                list(pool.map(lambda _: attempt(), range(200)))
        finally:
            sys.setswitchinterval(old_interval)

        assert len(leaked) == 0, (
            f"{len(leaked)} requests got auth=True with wrong PIN!"
        )

    def test_sequential_after_concurrent_barrage(self):
        """After a concurrent barrage, sequential requests must also be blocked."""
        auth = make_auth("12345")

        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            with ThreadPoolExecutor(max_workers=30) as pool:
                list(pool.map(lambda _: auth.verify_pin("wrong"), range(50)))
        finally:
            sys.setswitchinterval(old_interval)

        # Now do 20 sequential attempts - all should be exhausted
        exhausted_count = 0
        for _ in range(20):
            r = auth.verify_pin("wrong")
            if r["exhausted"]:
                exhausted_count += 1

        assert exhausted_count == 20, (
            f"Only {exhausted_count}/20 sequential attempts were exhausted "
            f"after concurrent barrage. Counter not properly synchronized."
        )


# ── Structure tests ──────────────────────────────────────────────────────────

class TestStructure:

    def test_has_pin_auth_class(self):
        auth = PinAuth("test")
        assert hasattr(auth, "verify_pin")
        assert hasattr(auth, "_fail_pin_auth")

    def test_uses_synchronization(self):
        """The fix must use some form of thread synchronization."""
        import inspect
        source = inspect.getsource(PinAuth)
        has_sync = any(kw in source for kw in [
            "Lock", "RLock", "Semaphore", "Value", "atomic",
            "synchronized", "threading",
        ])
        assert has_sync, (
            "PinAuth does not use any synchronization primitives. "
            "The counter must be protected against concurrent access."
        )

    def test_verify_pin_returns_dict(self):
        auth = make_auth("12345")
        result = auth.verify_pin("wrong")
        assert isinstance(result, dict)
        assert "auth" in result
        assert "exhausted" in result
