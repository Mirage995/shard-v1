"""bank.py — Account management module.

Used in production for internal fund transfers between departments.
Some users have reported occasional balance discrepancies.
"""

import threading
import logging

# Configure logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')


class Bank:
    """Manages accounts with deposit, withdraw, and transfer operations."""

    def __init__(self):
        self.accounts = {}
        self.locks = {}
        self._audit_log = []
        self._audit_log_lock = threading.Lock()
        self._max_audit_log_size = 1000  # Limit audit log size

    def _audit(self, op, account_id, amount, balance_before):
        with self._audit_log_lock:
            if len(self._audit_log) >= self._max_audit_log_size:
                self._audit_log.pop(0)  # Remove the oldest entry
            self._audit_log.append({
                "op": op,
                "account": account_id,
                "amount": amount,
                "balance_before": balance_before,
            })

    def create_account(self, account_id, initial_balance=0.0):
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("Account ID must be a non-empty string")
        if account_id in self.accounts:
            raise ValueError(f"Account {account_id} already exists")
        if initial_balance < 0:
            raise ValueError("Initial balance cannot be negative")
        with threading.Lock():
            self.accounts[account_id] = float(initial_balance)
            self.locks[account_id] = threading.Lock()

    def get_balance(self, account_id):
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("Account ID must be a non-empty string")
        if account_id not in self.accounts:
            raise KeyError(f"Account {account_id} not found")
        with self.locks[account_id]:
            return self.accounts[account_id]

    def deposit(self, account_id, amount):
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("Account ID must be a non-empty string")
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if account_id not in self.accounts:
            raise KeyError(f"Account {account_id} not found")
        with self.locks[account_id]:
            current = self.accounts[account_id]
            if amount > float('inf') - current:
                logging.error(f"Potential overflow detected. Deposit amount: {amount}, current balance: {current}")
                raise OverflowError("Deposit amount too large, potential overflow")
            self._audit("deposit", account_id, amount, current)
            new_balance = current + amount
            self.accounts[account_id] = new_balance

    def withdraw(self, account_id, amount):
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("Account ID must be a non-empty string")
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if account_id not in self.accounts:
            raise KeyError(f"Account {account_id} not found")
        with self.locks[account_id]:
            current = self.accounts[account_id]
            if current < amount:
                raise ValueError("Insufficient funds")
            if amount > current:
                logging.warning(f"Withdrawal amount {amount} exceeds current balance {current}.")
            if current - amount < float('-inf'):
                logging.error(f"Potential underflow detected. Withdrawal amount: {amount}, current balance: {current}")
                raise OverflowError("Withdrawal amount too large, potential underflow")
            self._audit("withdraw", account_id, amount, current)
            new_balance = current - amount
            self.accounts[account_id] = new_balance

    def transfer(self, from_id, to_id, amount):
        if not isinstance(from_id, str) or not from_id:
            raise ValueError("From Account ID must be a non-empty string")
        if not isinstance(to_id, str) or not to_id:
            raise ValueError("To Account ID must be a non-empty string")
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if from_id not in self.accounts:
            raise KeyError(f"Account {from_id} not found")
        if to_id not in self.accounts:
            raise KeyError(f"Account {to_id} not found")
        if from_id == to_id:
            logging.warning("Transferring to the same account. No operation performed.")
            return

        account_ids = sorted([from_id, to_id])
        lock1 = self.locks[account_ids[0]]
        lock2 = self.locks[account_ids[1]]

        with lock1:
            with lock2:
                from_balance = self.accounts[from_id]
                if from_balance < amount:
                    raise ValueError("Insufficient funds")

                if from_balance - amount < float('-inf'):
                    logging.error(f"Potential underflow detected in from_account. Transfer amount: {amount}, current balance: {from_balance}")
                    raise OverflowError("Transfer amount too large, potential underflow in from_account")

                self._audit("transfer_out", from_id, amount, from_balance)
                self.accounts[from_id] = from_balance - amount

                to_balance = self.accounts[to_id]
                if amount > float('inf') - to_balance:
                    logging.error(f"Potential overflow detected in to_account. Transfer amount: {amount}, current balance: {to_balance}")
                    raise OverflowError("Transfer amount too large, potential overflow in to_account")

                self._audit("transfer_in", to_id, amount, to_balance)
                self.accounts[to_id] = to_balance + amount

    def total_funds(self):
        with threading.Lock():
            return sum(self.accounts.values())

    def get_audit_log(self):
        with self._audit_log_lock:
            return list(self._audit_log)