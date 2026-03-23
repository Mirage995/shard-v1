import hashlib
import time
import threading


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
        self._lock = threading.Lock()

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
        with self._lock:
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