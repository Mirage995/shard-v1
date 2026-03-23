"""legacy_processor.py — Transaction processor.

Processes financial transactions and returns a summary report.
Written by a former intern who no longer works here.
"""
import json
import random
import string
from datetime import datetime, timedelta


def _generate_transactions(n=10000, seed=42):
    """Generate n synthetic transactions for testing."""
    rng = random.Random(seed)

    categories = ["food", "transport", "entertainment", "utilities", "healthcare",
                  "education", "shopping", "travel"]
    statuses = ["completed", "pending", "refunded"]
    currencies = ["EUR", "USD", "GBP"]

    base_date = datetime(2025, 1, 1)
    transactions = []

    for i in range(n):
        tx_id = f"TX-{i:06d}"
        days_offset = rng.randint(0, 364)
        ts = base_date + timedelta(days=days_offset, seconds=rng.randint(0, 86399))

        tx = {
            "id": tx_id,
            "amount": round(rng.uniform(0.50, 500.00), 2),
            "currency": rng.choice(currencies),
            "category": rng.choice(categories),
            "status": rng.choice(statuses),
            "timestamp": ts.isoformat(),
            "merchant": f"merchant_{rng.randint(1, 200)}",
            "user_id": f"user_{rng.randint(1, 50)}",
        }
        transactions.append(tx)

    for idx in [77, 2341, 5918, 8102]:
        if idx < n:
            transactions[idx]["amount"] = str(transactions[idx]["amount"])

    for idx in [156, 3087, 6543, 9201]:
        if idx < n:
            transactions[idx]["category"] = transactions[idx]["category"] + "  "

    for idx in [312, 4455, 7789]:
        if idx < n:
            dt = datetime.fromisoformat(transactions[idx]["timestamp"])
            transactions[idx]["timestamp"] = int(dt.timestamp())

    for idx in [501, 6000]:
        if idx < n:
            del transactions[idx]["merchant"]

    if n > 1000:
        transactions[1000]["id"] = transactions[999]["id"]
    if n > 5000:
        transactions[5000]["id"] = transactions[4999]["id"]

    if n > 2000:
        transactions[2000]["amount"] = 0
        transactions[2000]["status"] = "completed"

    if n > 3000:
        transactions[3000]["merchant"] = "café_müller_naïve"

    if n > 4000:
        transactions[4000]["amount"] = -25.50
        transactions[4000]["status"] = "completed"

    if n > 7000:
        transactions[7000]["amount"] = 99999.99
        transactions[7000]["status"] = "completed"

    if n > 8500:
        transactions[8500]["category"] = ""

    return transactions


TRANSACTIONS = _generate_transactions()


def process_transactions(transactions):
    """Process transactions and return a summary report."""
    cleaned = []
    for tx in transactions:
        clean = {}
        clean["id"] = tx.get("id", "UNKNOWN")

        raw_amount = tx.get("amount", 0)
        try:
            clean["amount"] = float(raw_amount)
        except (ValueError, TypeError):
            clean["amount"] = 0.0

        clean["currency"] = tx.get("currency", "EUR")

        raw_cat = tx.get("category", "")
        cat = raw_cat.strip() if isinstance(raw_cat, str) else str(raw_cat)
        clean["category"] = cat if cat else "uncategorized"

        clean["status"] = tx.get("status", "pending")

        raw_ts = tx.get("timestamp", "")
        if isinstance(raw_ts, int) or isinstance(raw_ts, float):
            try:
                clean["timestamp"] = datetime.fromtimestamp(raw_ts)
            except (OSError, ValueError):
                clean["timestamp"] = datetime(2025, 1, 1)
        elif isinstance(raw_ts, str):
            try:
                clean["timestamp"] = datetime.fromisoformat(raw_ts)
            except ValueError:
                clean["timestamp"] = datetime(2025, 1, 1)
        else:
            clean["timestamp"] = datetime(2025, 1, 1)

        clean["merchant"] = tx.get("merchant", "unknown")

        cleaned.append(clean)

    cleaned.sort(key=lambda x: x["timestamp"])

    total_completed = 0.0
    completed_count = 0
    by_category = {}
    by_month = {}
    merchants_set = set()
    merchant_totals = {}
    id_counts = {}
    flagged = []
    currency_totals = {}

    for tx in cleaned:
        tid = tx["id"]
        if tid in id_counts:
            id_counts[tid] = id_counts[tid] + 1
        else:
            id_counts[tid] = 1

        merchants_set.add(tx["merchant"])

        if tx["status"] != "completed":
            continue

        amount = tx["amount"]

        if amount < 0:
            flagged.append(tid)

        total_completed = total_completed + amount
        completed_count = completed_count + 1

        cat = tx["category"]
        if cat in by_category:
            by_category[cat] = by_category[cat] + amount
        else:
            by_category[cat] = amount

        month_key = tx["timestamp"].strftime("%Y-%m")
        if month_key in by_month:
            by_month[month_key] = by_month[month_key] + amount
        else:
            by_month[month_key] = amount

        merch = tx["merchant"]
        if merch in merchant_totals:
            merchant_totals[merch] = merchant_totals[merch] + amount
        else:
            merchant_totals[merch] = amount

        cur = tx["currency"]
        if cur in currency_totals:
            currency_totals[cur] = currency_totals[cur] + amount
        else:
            currency_totals[cur] = amount

    if completed_count > 0:
        avg_completed = total_completed / completed_count
    else:
        avg_completed = 0.0

    sorted_merchants = []
    for m, total in merchant_totals.items():
        sorted_merchants.append((m, total))
    sorted_merchants.sort(key=lambda x: x[1], reverse=True)
    top_merchants = sorted_merchants[:5]

    duplicate_ids = []
    for tid, count in id_counts.items():
        if count > 1:
            duplicate_ids.append(tid)
    duplicate_ids.sort()

    total_completed = round(total_completed, 2)
    avg_completed = round(avg_completed, 2)
    by_category = {k: round(v, 2) for k, v in sorted(by_category.items())}
    by_month = {k: round(v, 2) for k, v in sorted(by_month.items())}
    top_merchants = [(m, round(t, 2)) for m, t in top_merchants]
    currency_totals = {k: round(v, 2) for k, v in sorted(currency_totals.items())}

    return {
        "total_completed": total_completed,
        "by_category": by_category,
        "by_month": by_month,
        "unique_merchants": len(merchants_set),
        "avg_completed": avg_completed,
        "top_merchants": top_merchants,
        "duplicate_ids": duplicate_ids,
        "flagged": flagged,
        "currency_totals": currency_totals,
    }


if __name__ == "__main__":
    import time
    t0 = time.perf_counter()
    result = process_transactions(TRANSACTIONS)
    elapsed = time.perf_counter() - t0
    print(f"Processed {len(TRANSACTIONS)} transactions in {elapsed*1000:.1f}ms")
    print(f"Total completed: {result['total_completed']}")
    print(f"Categories: {len(result['by_category'])}")
    print(f"Months: {len(result['by_month'])}")
    print(f"Unique merchants: {result['unique_merchants']}")
    print(f"Avg completed: {result['avg_completed']}")
    print(f"Top merchant: {result['top_merchants'][0] if result['top_merchants'] else 'N/A'}")
    print(f"Duplicates: {result['duplicate_ids']}")
    print(f"Flagged: {result['flagged']}")
    print(f"Currencies: {result['currency_totals']}")
