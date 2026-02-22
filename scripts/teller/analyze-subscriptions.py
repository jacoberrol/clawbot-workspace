#!/usr/bin/env python3
"""
Teller Subscription Analyzer
Pulls transaction history and identifies recurring charges worth reviewing.
"""

import json
import ssl
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "teller-config.json"
TELLER_BASE = "https://api.teller.io"


def load_config():
    if not CONFIG_FILE.exists():
        print("❌ No teller-config.json found. Run setup-server.py first.")
        raise SystemExit(1)
    return json.loads(CONFIG_FILE.read_text())


def teller_request(path, config):
    """Make an authenticated mTLS request to Teller API."""
    url = f"{TELLER_BASE}{path}"
    token = config["access_token"]
    cert = config["certificate"]
    key = config["private_key"]

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.load_cert_chain(certfile=cert, keyfile=key)

    req = urllib.request.Request(url)
    # HTTP Basic Auth with access token (password is empty)
    import base64
    credentials = base64.b64encode(f"{token}:".encode()).decode()
    req.add_header("Authorization", f"Basic {credentials}")

    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Teller API error {e.code}: {body[:200]}")


def get_accounts(config):
    return teller_request("/accounts", config)


def get_transactions(config, account_id, count=500):
    return teller_request(
        f"/accounts/{account_id}/transactions?count={count}", config
    )


def find_subscriptions(transactions):
    """
    Identify recurring charges by looking for:
    - Same merchant name appearing 2+ times
    - Reasonably consistent amounts
    - Reasonably consistent intervals
    """
    # Group by merchant/description
    by_merchant = defaultdict(list)
    for txn in transactions:
        if txn.get("type") == "card_payment" or txn.get("amount", 0) < 0:
            name = (
                txn.get("details", {}).get("counterparty", {}).get("name")
                or txn.get("description", "Unknown")
            ).strip()
            try:
                date = datetime.strptime(txn["date"], "%Y-%m-%d")
            except Exception:
                continue
            amount = abs(float(txn.get("amount", 0)))
            by_merchant[name].append({"date": date, "amount": amount, "id": txn.get("id")})

    subscriptions = []

    for merchant, charges in by_merchant.items():
        if len(charges) < 2:
            continue

        charges.sort(key=lambda x: x["date"])
        amounts = [c["amount"] for c in charges]
        avg_amount = sum(amounts) / len(amounts)

        # Check if amounts are consistent (within 5% variance)
        if avg_amount == 0:
            continue
        amount_variance = max(abs(a - avg_amount) / avg_amount for a in amounts)
        if amount_variance > 0.10:  # more than 10% variance = probably not a subscription
            continue

        # Check intervals between charges
        dates = [c["date"] for c in charges]
        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        avg_interval = sum(intervals) / len(intervals)

        # Classify interval
        if 6 <= avg_interval <= 9:
            period = "weekly"
            monthly_cost = avg_amount * 4.33
        elif 25 <= avg_interval <= 35:
            period = "monthly"
            monthly_cost = avg_amount
        elif 55 <= avg_interval <= 70:
            period = "bi-monthly"
            monthly_cost = avg_amount / 2
        elif 85 <= avg_interval <= 100:
            period = "quarterly"
            monthly_cost = avg_amount / 3
        elif 340 <= avg_interval <= 390:
            period = "annual"
            monthly_cost = avg_amount / 12
        else:
            continue  # irregular interval, skip

        # Check interval consistency
        if len(intervals) > 1:
            interval_variance = max(abs(i - avg_interval) / avg_interval for i in intervals)
            if interval_variance > 0.35:
                continue

        last_charge = charges[-1]["date"]
        days_since = (datetime.now() - last_charge).days
        annual_cost = monthly_cost * 12

        subscriptions.append({
            "merchant": merchant,
            "amount": avg_amount,
            "period": period,
            "monthly_cost": monthly_cost,
            "annual_cost": annual_cost,
            "occurrences": len(charges),
            "last_charge": last_charge.strftime("%Y-%m-%d"),
            "days_since_last": days_since,
            "active": days_since <= (avg_interval * 1.5),
        })

    # Sort by monthly cost descending
    subscriptions.sort(key=lambda x: x["monthly_cost"], reverse=True)
    return subscriptions


def format_report(subscriptions, accounts):
    lines = []
    lines.append("\n💳 SUBSCRIPTION ANALYSIS REPORT")
    lines.append("=" * 50)

    if not subscriptions:
        lines.append("No recurring subscriptions detected.")
        return "\n".join(lines)

    active = [s for s in subscriptions if s["active"]]
    inactive = [s for s in subscriptions if not s["active"]]

    total_monthly = sum(s["monthly_cost"] for s in active)
    total_annual = total_monthly * 12

    lines.append(f"\n📊 Summary: {len(active)} active subscriptions")
    lines.append(f"   Est. monthly spend: ${total_monthly:.2f}")
    lines.append(f"   Est. annual spend:  ${total_annual:.2f}")

    lines.append(f"\n🔴 Active Subscriptions (sorted by cost):")
    lines.append("-" * 50)

    for s in active:
        flag = "⚠️ " if s["monthly_cost"] > 20 else "   "
        lines.append(
            f"{flag}{s['merchant']:<35} "
            f"${s['amount']:>7.2f}/{s['period']:<10} "
            f"(~${s['monthly_cost']:.2f}/mo)"
        )

    if inactive:
        lines.append(f"\n🟡 Possibly Lapsed (haven't charged recently):")
        lines.append("-" * 50)
        for s in inactive:
            lines.append(
                f"   {s['merchant']:<35} "
                f"${s['amount']:>7.2f}/{s['period']:<10} "
                f"(last: {s['last_charge']})"
            )

    lines.append("\n💡 Review candidates (highest monthly cost first):")
    for i, s in enumerate(active[:5], 1):
        lines.append(f"  {i}. {s['merchant']} — ${s['monthly_cost']:.2f}/mo (${s['annual_cost']:.2f}/yr)")

    return "\n".join(lines)


def main():
    config = load_config()

    print("🏦 Fetching accounts from Teller...")
    accounts = get_accounts(config)

    if not accounts:
        print("No accounts found. Check your access token.")
        return

    print(f"Found {len(accounts)} account(s):\n")
    all_transactions = []

    for acc in accounts:
        name = acc.get("name", "Unknown")
        inst = acc.get("institution", {}).get("name", "Unknown")
        kind = acc.get("subtype", acc.get("type", ""))
        print(f"  • {inst} — {name} ({kind})")

        try:
            txns = get_transactions(config, acc["id"])
            print(f"    Fetched {len(txns)} transactions")
            all_transactions.extend(txns)
        except Exception as e:
            print(f"    ⚠️  Could not fetch transactions: {e}")

    if not all_transactions:
        print("\nNo transactions found.")
        return

    print(f"\nAnalyzing {len(all_transactions)} total transactions for subscriptions...")
    subscriptions = find_subscriptions(all_transactions)

    report = format_report(subscriptions, accounts)
    print(report)

    # Save raw data for further analysis
    output_file = SCRIPT_DIR / "subscription-report.json"
    output_file.write_text(json.dumps({
        "generated": datetime.now().isoformat(),
        "accounts": len(accounts),
        "transactions_analyzed": len(all_transactions),
        "subscriptions": subscriptions,
    }, indent=2, default=str))
    print(f"\n📄 Full data saved to {output_file}")


if __name__ == "__main__":
    main()
