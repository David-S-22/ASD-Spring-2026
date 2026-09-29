"""Render bill records as the Markdown files the shared RAG server ingests for the bills feature.

One file per bill, under MAX_CHARS characters, so the server's Markdown splitter keeps each
bill as a single chunk. Values are written exactly as the bills database stores them; only
cents become dollars, through engine/money.format_actual. The status line is the stored status
column, which every write path refreshes from engine/status.derive_status; it is never
recomputed here.
"""
import re

from sophia.backend.engine.money import format_actual

MAX_CHARS = 800
OPEN_DISPUTE_STATUSES = ("draft", "sent")


def slug(name):
    """Lower-case the name and keep only runs of letters and digits, joined by hyphens."""
    return "-".join(re.findall(r"[a-z0-9]+", name.lower()))


def file_name(bill):
    """Return the corpus file name for a bill, for example bill-7-home-internet.md."""
    return f"bill-{bill['id']}-{slug(bill['name'])}.md"


def render_bill(bill, payments, disputes):
    """Return the Markdown text for one bill, given its own payments and disputes."""
    lines = [
        f"# {bill['name']} ({bill['type']})",
        "",
        f"- Merchant: {bill['merchant']}",
        f"- Type: {bill['type']}",
        f"- Cadence: {bill['cadence']}",
        f"- Amount: {format_actual(bill['amount_cents'])}",
        f"- Next billing date: {bill['next_billing_date']}",
        f"- Status: {bill['status']}",
    ]
    if bill.get("payment_method"):
        lines.append(f"- Payment method: {bill['payment_method']}")
    if bill.get("end_date"):
        lines.append(f"- End date: {bill['end_date']}")
    if payments:
        last = max(payments, key=lambda payment: payment["date"])
        lines.append(f"- Last payment: {last['date']} ({format_actual(last['amount_cents'])})")
    open_disputes = sum(1 for dispute in disputes if dispute["status"] in OPEN_DISPUTE_STATUSES)
    lines.append(f"- Open disputes: {open_disputes}")
    if bill.get("exclude_from_plan"):
        lines.append("- Excluded from the monthly plan: yes")
    return "\n".join(lines) + "\n"


def render_corpus(bills, payments, disputes):
    """Return {file name: text} for every bill in id order; refuse a text over MAX_CHARS."""
    files = {}
    for bill in sorted(bills, key=lambda bill: bill["id"]):
        bill_payments = [payment for payment in payments if payment["bill_id"] == bill["id"]]
        bill_disputes = [dispute for dispute in disputes if dispute["bill_id"] == bill["id"]]
        text = render_bill(bill, bill_payments, bill_disputes)
        if len(text) > MAX_CHARS:
            raise ValueError(f"{file_name(bill)} is {len(text)} characters; the cap is {MAX_CHARS}")
        files[file_name(bill)] = text
    return files
