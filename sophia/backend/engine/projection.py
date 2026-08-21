"""Projects a Bill into concrete Occurrence rows across a date window."""
from dataclasses import replace
from datetime import date, timedelta

from sophia.backend.engine import Occurrence
from sophia.backend.engine.dates import add_cadence
from sophia.backend.engine.status import current_cycle_due


def _within(bill, d: date, start: date, end: date) -> bool:
    if d < start or d >= end:
        return False
    if bill.end_date is not None and d > bill.end_date:
        return False
    if bill.created_at is not None and d < bill.created_at:
        return False
    return True


def _occurrence(bill, d: date, n: int) -> Occurrence:
    return Occurrence(
        bill_id=bill.id,
        name=bill.name,
        date=d,
        amount_cents=bill.amount_cents,
        kind="predicted",
        cycle_index=n,
    )


def project(bill, start: date, end: date) -> list:
    """Return every occurrence of bill with start <= date < end and date <= bill.end_date, if set.

    Walks n both directions from bill.next_billing_date so the anchor need
    not itself fall inside the window.
    """
    occurrences = []
    anchor = bill.next_billing_date
    n = 0
    while True:
        d = add_cadence(anchor, bill.cadence, n)
        if d < start:
            break
        if _within(bill, d, start, end):
            occurrences.append(_occurrence(bill, d, n))
        n -= 1
    n = 1
    while True:
        d = add_cadence(anchor, bill.cadence, n)
        if d >= end:
            break
        if _within(bill, d, start, end):
            occurrences.append(_occurrence(bill, d, n))
        n += 1
    occurrences.sort(key=lambda o: o.date)
    return occurrences


def tag_kind(occ, payments) -> str:
    """Return "actual" if a payment for occ.bill_id lands within 3 days of occ.date, else "predicted"."""
    for payment in payments:
        if payment.bill_id == occ.bill_id and abs((payment.date - occ.date).days) <= 3:
            return "actual"
    return "predicted"


def _overdue_occurrence(bill, payments, today: date):
    """Return the bill's current unpaid cycle as an "overdue" Occurrence, or None.

    project()'s forward window starts at today, so a due date strictly
    before today (unpaid, and still within the bill's end_date) would
    otherwise never appear on the timeline at all.
    """
    due = current_cycle_due(bill, today)
    if due is None or due >= today:
        return None
    if bill.end_date is not None and due > bill.end_date:
        return None
    candidate = _occurrence(bill, due, 0)
    if tag_kind(candidate, payments) == "actual":
        return None
    return replace(candidate, kind="overdue")


def timeline(bills, payments, today: date, days: int) -> list:
    """Return every occurrence across bills in [today, today + days), tagged and sorted.

    days is clamped to the 30..180 range. kind is "actual", "predicted", or
    "overdue" - the last one is a real, unpaid charge whose due date has
    already passed (current_cycle_due < today with no matching payment),
    which project()'s forward-only window would otherwise drop entirely.
    """
    clamped_days = max(30, min(180, days))
    end = today + timedelta(days=clamped_days)
    occurrences = []
    for bill in bills:
        for occ in project(bill, today, end):
            occurrences.append(replace(occ, kind=tag_kind(occ, payments)))
        overdue_occ = _overdue_occurrence(bill, payments, today)
        if overdue_occ is not None:
            occurrences.append(overdue_occ)
    occurrences.sort(key=lambda o: (o.date, o.name))
    return occurrences
