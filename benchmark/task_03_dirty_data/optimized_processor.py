import json
import random
import string
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import copy


def _generate_transactions(n=10000, seed=42):
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
        transactions.append(copy.deepcopy(tx))

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


def process_transactions(transactions):
    total_completed = 0.0
    completed_count = 0
    by_category = defaultdict(float)
    by_month = defaultdict(float)
    merchants_set = set()
    merchant_totals = defaultdict(float)
    id_counts = Counter(tx.get("id", "UNKNOWN") for tx in transactions)
    flagged = []
    currency_totals = defaultdict(float)

    for tx in transactions:
        try:
            amount = float(tx.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0.0

        raw_ts = tx.get("timestamp", "")
        if isinstance(raw_ts, (int, float)):
            timestamp = datetime.fromtimestamp(raw_ts)
        else:
            try:
                timestamp = datetime.fromisoformat(str(raw_ts))
            except (ValueError, TypeError):
                timestamp = datetime(2025, 1, 1)

        category = tx.get("category", "").strip() or "uncategorized"
        status = tx.get("status", "pending")
        merchant = tx.get("merchant", "unknown")
        currency = tx.get("currency", "EUR")

        merchants_set.add(merchant)

        if status != "completed":
            continue

        if amount < 0:
            flagged.append(tx.get("id", "UNKNOWN"))

        total_completed += amount
        completed_count += 1
        by_category[category] += amount
        by_month[timestamp.strftime("%Y-%m")] += amount
        merchant_totals[merchant] += amount
        currency_totals[currency] += amount

    if completed_count > 0:
        avg_completed = total_completed / completed_count
    else:
        avg_completed = 0.0

    top_merchants = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:5]
    duplicate_ids = sorted([tid for tid, count in id_counts.items() if count > 1])

    return {
        "total_completed": round(total_completed, 2),
        "by_category": dict(sorted({k: round(v, 2) for k, v in by_category.items()}.items())),
        "by_month": dict(sorted({k: round(v, 2) for k, v in by_month.items()}.items())),
        "unique_merchants": len(merchants_set),
        "avg_completed": round(avg_completed, 2),
        "top_merchants": [(m, round(t, 2)) for m, t in top_merchants],
        "duplicate_ids": duplicate_ids,
        "flagged": flagged,
        "currency_totals": dict(sorted({k: round(v, 2) for k, v in currency_totals.items()}.items())),
    }


if __name__ == "__main__":
    import time
    t0 = time.perf_counter()
    result = process_transactions(_generate_transactions())
    elapsed = time.perf_counter() - t0
    print(f"Processed {len(_generate_transactions())} transactions in {elapsed*1000:.1f}ms")
    print(f"Total completed: {result['total_completed']}")
    print(f"Categories: {len(result['by_category'])}")
    print(f"Months: {len(result['by_month'])}")
    print(f"Unique merchants: {result['unique_merchants']}")
    print(f"Avg completed: {result['avg_completed']}")
    print(f"Top merchant: {result['top_merchants'][0] if result['top_merchants'] else 'N/A'}")
    print(f"Duplicates: {result['duplicate_ids']}")
    print(f"Flagged: {result['flagged']}")
    print(f"Currencies: {result['currency_totals']}")