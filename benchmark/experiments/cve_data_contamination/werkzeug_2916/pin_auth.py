"""pin_auth.py — Extracted from Werkzeug 3.0.3 (pallets/werkzeug)

Debugger PIN authentication module. This is a self-contained extraction
of the PIN auth logic from werkzeug.debug.DebuggedApplication.

The debugger exposes a PIN-based authentication system to prevent
unauthorized access to the interactive debugger console. After too many
failed attempts, the system should lock out the attacker.

Original source: src/werkzeug/debug/__init__.py (tag 3.0.3)
License: BSD-3-Clause
"""
import hashlib
import json
import time


def hash_pin(pin: str) -> str:
    return hashlib.sha1(
        f"{pin} added salt".encode("utf-8", "replace")
    ).hexdigest()[:12]


class PinAuth:
    """PIN-based authentication for the Werkzeug debugger.

    After 10 failed attempts, the system should report ``exhausted=True``
    and refuse further authentication, effectively locking out the attacker.
    """

    def __init__(self, pin: str):
        self.pin = pin
        self._failed_pin_auth = 0

    def _fail_pin_auth(self) -> None:
        """Record a failed authentication attempt with rate limiting."""
        time.sleep(5.0 if self._failed_pin_auth > 5 else 0.5)
        self._failed_pin_auth += 1

    def verify_pin(self, entered_pin: str) -> dict:
        """Authenticate a PIN attempt.

        Returns a dict with:
            - auth (bool): True if the PIN was correct
            - exhausted (bool): True if too many failed attempts
        """
        exhausted = False
        auth = False

        if self._failed_pin_auth > 10:
            exhausted = True
        else:
            if entered_pin.strip().replace("-", "") == self.pin.replace("-", ""):
                self._failed_pin_auth = 0
                auth = True
            else:
                self._fail_pin_auth()

        return {"auth": auth, "exhausted": exhausted}
