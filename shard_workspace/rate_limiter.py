import threading
import time

class RateLimiter:
    def __init__(self, rate):
        self.rate = rate
        self.tokens = rate
        self.last_update = time.time()
        self.lock = threading.Lock()

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now
        self.tokens = min(self.rate, self.tokens + elapsed * self.rate)

    def allow(self):
        with self.lock:
            self._refill()

            if self.tokens >= 1:
                self.tokens -= 1
                return True

            return False