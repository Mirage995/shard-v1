import threading

class Bank:
    """Manages accounts with deposit, withdraw, and transfer operations."""

    def __init__(self):
        self.accounts = {}
        self._audit_log = []
        self._lock = threading.Lock()

    def _audit(self, op, account_id, amount, balance_before):
        self._audit_log.append({
            "op": op,
            "account": account_id,
            "amount": amount,
            "balance_before": balance_before,
        })

    def create_account(self, account_id, initial_balance=0.0):
        with self._lock:
            if account_id in self.accounts:
                raise ValueError(f"Account {account_id} already exists")
            if initial_balance < 0:
                raise ValueError("Initial balance cannot be negative")
            self.accounts[account_id] = float(initial_balance)

    def get_balance(self, account_id):
        with self._lock:
            if account_id not in self.accounts:
                raise KeyError(f"Account {account_id} not found")
            return self.accounts[account_id]

    def deposit(self, account_id, amount):
        with self._lock:
            if amount <= 0:
                raise ValueError("Amount must be positive")
            if account_id not in self.accounts:
                raise KeyError(f"Account {account_id} not found")
            current = self.accounts[account_id]
            self._audit("deposit", account_id, amount, current)
            new_balance = current + amount
            self.accounts[account_id] = new_balance

    def withdraw(self, account_id, amount):
        with self._lock:
            if amount <= 0:
                raise ValueError("Amount must be positive")
            if account_id not in self.accounts:
                raise KeyError(f"Account {account_id} not found")
            current = self.accounts[account_id]
            if current < amount:
                raise ValueError("Insufficient funds")
            self._audit("withdraw", account_id, amount, current)
            new_balance = current - amount
            self.accounts[account_id] = new_balance

    def transfer(self, from_id, to_id, amount):
        with self._lock:
            if amount <= 0:
                raise ValueError("Amount must be positive")
            if from_id not in self.accounts:
                raise KeyError(f"Account {from_id} not found")
            if to_id not in self.accounts:
                raise KeyError(f"Account {to_id} not found")
            if from_id == to_id:
                return

            from_balance = self.accounts[from_id]
            if from_balance < amount:
                raise ValueError("Insufficient funds")
            to_balance = self.accounts[to_id]

            self._audit("transfer_out", from_id, amount, from_balance)
            self._audit("transfer_in", to_id, amount, to_balance)

            self.accounts[from_id] = from_balance - amount
            self.accounts[to_id] = to_balance + amount

    def total_funds(self):
        with self._lock:
            return sum(self.accounts.values())

    def get_audit_log(self):
        with self._lock:
            return list(self._audit_log)