"""Derives per-bill payment status (paid/due/overdue) from projected occurrences."""
from datetime import date

from sophia.backend.engine.dates import add_cadence


def _day_month(d: date) -> str:
    """Format a date as day-of-month (no leading zero) plus abbreviated month, e.g. "2 Sep"."""
    return f"{d.day} {d.strftime('%b')}"


def current_cycle_due(bill, today: date):
    """Return the latest occurrence date <= today, or None if the bill has not started yet.

    A candidate occurrence before bill.created_at (when set) does not count
    as a real prior cycle, so a bill's very first charge reports None until
    that first occurrence has actually happened.
    """
    anchor = bill.next_billing_date
    if anchor <= today:
        n = 0
        while add_cadence(anchor, bill.cadence, n + 1) <= today:
            n += 1
        return add_cadence(anchor, bill.cadence, n)
    n = -1
    candidate = add_cadence(anchor, bill.cadence, n)
    while candidate > today:
        if bill.created_at is not None and candidate < bill.created_at:
            return None
        n -= 1
        candidate = add_cadence(anchor, bill.cadence, n)
    if bill.created_at is not None and candidate < bill.created_at:
        return None
    return candidate


def derive_status(bill, payments, today: date):
    """Return (status, label) for a bill as of today.

    status is one of paid/due/overdue, following the rules: an ended bill is
    always paid; a bill with no prior cycle is due with a "First charge"
    label; a bill with a payment covering the current cycle is paid (with a
    "Due" label instead when the next occurrence lands within 7 days); a
    bill due exactly today is due; anything else is overdue.
    """
    if bill.end_date is not None and bill.end_date < today:
        return ("paid", f"Ended {_day_month(bill.end_date)}")
    due_now = current_cycle_due(bill, today)
    if due_now is None:
        return ("due", f"First charge {_day_month(bill.next_billing_date)}")
    bill_payments = [p for p in payments if p.bill_id == bill.id]
    if any(p.date >= due_now for p in bill_payments):
        label = f"Paid for {due_now.strftime('%b')}"
        next_occurrence = (
            bill.next_billing_date
            if bill.next_billing_date > due_now
            else add_cadence(due_now, bill.cadence, 1)
        )
        if today <= next_occurrence and (next_occurrence - today).days <= 7:
            label = f"Due {_day_month(next_occurrence)}"
        return ("paid", label)
    if today == due_now:
        return ("due", "Due today")
    return ("overdue", f"Overdue {(today - due_now).days} days")
