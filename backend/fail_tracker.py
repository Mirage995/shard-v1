import time

class FailTracker:
    """
    FailTracker is a reusable utility for preventing infinite retry loops in SHARD agents.

    It tracks repeated failures for a deterministic task key and temporarily blocks
    execution after a configurable number of retries.

    This component is intentionally agent-agnostic and can be reused by any SHARD
    module that executes non-deterministic external tasks (API calls, generation tasks,
    network operations, etc.).
    """
    def __init__(self, max_retries: int = 3, cooldown_minutes: int = 30):
        self.max_retries = max_retries
        self.cooldown_seconds = cooldown_minutes * 60
        self.failures = {}  # dict[key, dict["count", "last_failure"]]

    def register_failure(self, key: str):
        now = time.time()
        if key not in self.failures:
            self.failures[key] = {"count": 1, "last_failure": now}
        else:
            self.failures[key]["count"] += 1
            self.failures[key]["last_failure"] = now
            
    def should_block(self, key: str) -> bool:
        if key not in self.failures:
            return False
            
        record = self.failures[key]
        now = time.time()
        
        # Check cooldown
        if now - record["last_failure"] > self.cooldown_seconds:
            # We naturally recovered from cooldown, reset it
            del self.failures[key]
            return False
            
        if record["count"] >= self.max_retries:
            print(f"[FAIL TRACKER] Blocking repeated failure: {key}")
            return True
            
        return False

    def reset(self, key: str):
        if key in self.failures:
            print(f"[FAIL TRACKER] Task recovered after previous failures: {key}")
            del self.failures[key]
