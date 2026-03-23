"""Tests for the banking module.

Run with: pytest test_task4.py -v
"""
import sys
import threading
import random
from pathlib import Path

import pytest

# ── Import the fixed version ──────────────────────────────────────────────────
spec_path = Path(__file__).parent / "fixed_bank.py"
if not spec_path.exists():
    pytest.skip(f"fixed_bank.py not found at {spec_path}", allow_module_level=True)

from fixed_bank import Bank


# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
def bank():
    b = Bank()
    b.create_account("alice", 1000.0)
    b.create_account("bob", 1000.0)
    return b


@pytest.fixture
def big_bank():
    """Bank with 10 accounts, 1000 each = 10000 total."""
    b = Bank()
    for i in range(10):
        b.create_account(f"acc_{i}", 1000.0)
    return b


# ── Basic correctness (single-threaded) ──────────────────────────────────────

class TestBasicCorrectness:

    def test_create_and_balance(self):
        bank = Bank()
        bank.create_account("x", 500)
        assert bank.get_balance("x") == 500.0

    def test_deposit(self, bank):
        bank.deposit("alice", 250)
        assert bank.get_balance("alice") == 1250.0

    def test_withdraw(self, bank):
        bank.withdraw("alice", 300)
        assert bank.get_balance("alice") == 700.0

    def test_transfer(self, bank):
        bank.transfer("alice", "bob", 200)
        assert bank.get_balance("alice") == 800.0
        assert bank.get_balance("bob") == 1200.0

    def test_insufficient_funds_withdraw(self, bank):
        with pytest.raises(ValueError):
            bank.withdraw("alice", 5000)
        assert bank.get_balance("alice") == 1000.0

    def test_insufficient_funds_transfer(self, bank):
        with pytest.raises(ValueError):
            bank.transfer("alice", "bob", 5000)
        assert bank.get_balance("alice") == 1000.0
        assert bank.get_balance("bob") == 1000.0

    def test_total_funds_conserved(self, bank):
        bank.transfer("alice", "bob", 300)
        bank.deposit("alice", 100)
        bank.withdraw("bob", 50)
        assert bank.total_funds() == 2050.0

    def test_duplicate_account_raises(self, bank):
        with pytest.raises(ValueError):
            bank.create_account("alice", 100)

    def test_unknown_account_raises(self):
        bank = Bank()
        with pytest.raises(KeyError):
            bank.get_balance("ghost")


# ── Concurrency tests ────────────────────────────────────────────────────────

class TestConcurrency:

    def test_concurrent_deposits(self):
        """50 threads each deposit 100 x $10 to the same account.
        Expected final balance: 50 * 100 * 10 = 50000."""
        bank = Bank()
        bank.create_account("shared", 0)

        n_threads = 50
        deposits_per_thread = 100
        amount = 10.0
        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            def do_deposits():
                for _ in range(deposits_per_thread):
                    bank.deposit("shared", amount)

            threads = [threading.Thread(target=do_deposits) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old_interval)

        expected = n_threads * deposits_per_thread * amount
        actual = bank.get_balance("shared")
        assert actual == expected, (
            f"Expected {expected} after {n_threads * deposits_per_thread} deposits "
            f"of {amount}, got {actual}. Lost {expected - actual}."
        )

    def test_concurrent_withdrawals_no_overdraft(self):
        """50 threads try to withdraw $10 from account with $100.
        At most 10 should succeed. Balance must never go negative."""
        bank = Bank()
        bank.create_account("victim", 100.0)

        successes = []
        lock = threading.Lock()
        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            def try_withdraw():
                for _ in range(5):
                    try:
                        bank.withdraw("victim", 10.0)
                        with lock:
                            successes.append(1)
                    except ValueError:
                        pass

            threads = [threading.Thread(target=try_withdraw) for _ in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old_interval)

        balance = bank.get_balance("victim")
        n_success = len(successes)

        assert balance >= 0, (
            f"Balance went negative: {balance}. "
            f"{n_success} withdrawals succeeded but only 10 should have."
        )
        assert balance == 100.0 - n_success * 10.0, (
            f"Balance {balance} inconsistent with {n_success} successful withdrawals."
        )

    def test_concurrent_transfers_conserve_money(self, big_bank):
        """Random transfers between 10 accounts must conserve total funds."""
        initial_total = big_bank.total_funds()

        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            def random_transfers():
                rng = random.Random(threading.current_thread().ident)
                for _ in range(200):
                    a = f"acc_{rng.randint(0, 9)}"
                    b = f"acc_{rng.randint(0, 9)}"
                    if a != b:
                        try:
                            big_bank.transfer(a, b, rng.uniform(1, 50))
                        except ValueError:
                            pass

            threads = [threading.Thread(target=random_transfers) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old_interval)

        final_total = big_bank.total_funds()
        diff = abs(final_total - initial_total)
        assert diff < 0.01, (
            f"Money conservation violated: started with {initial_total}, "
            f"ended with {final_total} (diff: {diff:+.2f})."
        )

    def test_concurrent_mixed_operations(self, bank):
        """Mix of deposits, withdrawals, and transfers must stay consistent."""
        initial_total = bank.total_funds()

        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            def deposits():
                for _ in range(500):
                    bank.deposit("alice", 10)

            def withdrawals():
                for _ in range(500):
                    try:
                        bank.withdraw("bob", 10)
                    except ValueError:
                        pass

            def transfers():
                for _ in range(500):
                    try:
                        bank.transfer("alice", "bob", 5)
                    except ValueError:
                        pass

            threads = [
                threading.Thread(target=deposits),
                threading.Thread(target=deposits),
                threading.Thread(target=deposits),
                threading.Thread(target=withdrawals),
                threading.Thread(target=withdrawals),
                threading.Thread(target=withdrawals),
                threading.Thread(target=transfers),
                threading.Thread(target=transfers),
                threading.Thread(target=transfers),
                threading.Thread(target=transfers),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old_interval)

        alice = bank.get_balance("alice")
        bob = bank.get_balance("bob")
        assert alice >= 0, f"Alice balance negative: {alice}"
        assert bob >= 0, f"Bob balance negative: {bob}"

        # Deposits added 200*10=2000, withdrawals removed at most 100*10*2 threads
        # Total should account for all operations
        total = bank.total_funds()
        # We can't predict exact total (withdrawals may fail), but it must be
        # at least initial (since deposits always succeed)
        assert total >= initial_total, (
            f"Total funds decreased from {initial_total} to {total} despite net deposits."
        )

    def test_no_deadlock_bidirectional(self):
        """Simultaneous A->B and B->A transfers must not deadlock."""
        bank = Bank()
        bank.create_account("X", 100000.0)
        bank.create_account("Y", 100000.0)

        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

        try:
            def x_to_y():
                for _ in range(500):
                    try:
                        bank.transfer("X", "Y", 1)
                    except ValueError:
                        pass

            def y_to_x():
                for _ in range(500):
                    try:
                        bank.transfer("Y", "X", 1)
                    except ValueError:
                        pass

            threads = [
                threading.Thread(target=x_to_y),
                threading.Thread(target=y_to_x),
                threading.Thread(target=x_to_y),
                threading.Thread(target=y_to_x),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            alive = [t for t in threads if t.is_alive()]
            assert not alive, (
                f"{len(alive)} threads still running after 10s timeout. "
                f"This indicates a deadlock in transfer(). "
                f"Hint: when using per-account locks, use consistent lock ordering."
            )
        finally:
            sys.setswitchinterval(old_interval)

        total = bank.total_funds()
        assert abs(total - 200000.0) < 0.01, (
            f"Money conservation violated after bidirectional transfers: {total}"
        )


# ── Structure tests ──────────────────────────────────────────────────────────

class TestStructure:

    def test_has_required_methods(self):
        b = Bank()
        for method in ["create_account", "deposit", "withdraw",
                        "transfer", "get_balance", "total_funds"]:
            assert hasattr(b, method), f"Bank missing method: {method}"

    def test_uses_threading_primitives(self):
        """The fix must use proper synchronization."""
        import inspect
        source = inspect.getsource(Bank)
        uses_lock = "Lock" in source or "RLock" in source
        assert uses_lock, (
            "Bank does not use threading.Lock or RLock. "
            "Concurrent access requires synchronization."
        )
