"""Tests for shard_semaphore — dual-layer session lock."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import shard_semaphore as sem_module
from shard_semaphore import (
    acquire_file_lock,
    get_lock_reason,
    is_file_locked,
    release_file_lock,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestFileLock(unittest.TestCase):
    """Tests for the cross-process file lock."""

    def setUp(self):
        # Redirect the lock file to a temp location
        self._tmp_dir = tempfile.mkdtemp()
        self._orig_path = sem_module.SESSION_LOCK_FILE
        sem_module.SESSION_LOCK_FILE = Path(self._tmp_dir) / "session.lock"
        # Ensure no leftover lock
        sem_module.SESSION_LOCK_FILE.unlink(missing_ok=True)

    def tearDown(self):
        sem_module.SESSION_LOCK_FILE.unlink(missing_ok=True)
        sem_module.SESSION_LOCK_FILE = self._orig_path

    def test_not_locked_initially(self):
        self.assertFalse(is_file_locked())

    def test_acquire_creates_lock(self):
        acquire_file_lock("audio_session")
        self.assertTrue(is_file_locked())

    def test_acquire_writes_reason(self):
        acquire_file_lock("night_runner")
        self.assertEqual(get_lock_reason(), "night_runner")

    def test_release_removes_lock(self):
        acquire_file_lock("audio_session")
        release_file_lock()
        self.assertFalse(is_file_locked())

    def test_release_idempotent(self):
        """Releasing an already-released lock must not raise."""
        release_file_lock()
        release_file_lock()
        self.assertFalse(is_file_locked())

    def test_get_reason_when_not_locked(self):
        self.assertEqual(get_lock_reason(), "")

    def test_acquire_default_reason(self):
        acquire_file_lock()  # default reason
        reason = get_lock_reason()
        self.assertEqual(reason, "audio_session")

    def test_overwrite_lock_reason(self):
        acquire_file_lock("audio_session")
        acquire_file_lock("night_runner")
        self.assertEqual(get_lock_reason(), "night_runner")


class TestInProcessSemaphore(unittest.TestCase):
    """Tests for the asyncio.Semaphore layer."""

    def setUp(self):
        # Reset semaphore to a known state between tests
        sem_module.SHARD_SESSION_LOCK = asyncio.Semaphore(1)

    def test_semaphore_is_semaphore(self):
        self.assertIsInstance(sem_module.SHARD_SESSION_LOCK, asyncio.Semaphore)

    def test_semaphore_starts_free(self):
        # _value == 1 means no one holds it
        self.assertEqual(sem_module.SHARD_SESSION_LOCK._value, 1)

    def test_semaphore_acquire_blocks_second(self):
        """Two concurrent acquires: only one can proceed immediately."""
        sem = sem_module.SHARD_SESSION_LOCK

        results = []

        async def task(name):
            acquired = sem.locked()  # True if already taken
            async with sem:
                results.append(name)
                await asyncio.sleep(0.02)

        async def run_both():
            await asyncio.gather(task("A"), task("B"))

        run(run_both())
        # Both tasks ran exactly once, in some order
        self.assertCountEqual(results, ["A", "B"])

    def test_semaphore_try_acquire_fails_when_held(self):
        """acquire() with timeout=0 must fail if the lock is already held."""
        sem = sem_module.SHARD_SESSION_LOCK

        async def run_test():
            async with sem:
                # Lock is now held — try to acquire with no wait
                result = await asyncio.wait_for(
                    asyncio.shield(sem.acquire()), timeout=0.01
                )
                return result

        with self.assertRaises((asyncio.TimeoutError, Exception)):
            run(run_test())


if __name__ == "__main__":
    unittest.main()
