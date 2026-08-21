"""Aggregates a calendar month's expected bill costs into a usual/extra breakdown."""
from dataclasses import dataclass
from datetime import date, timedelta

from sophia.backend.engine.dates import expected_per_month, month_bounds
from sophia.backend.engine.projection import project
from sophia.backend.engine.status import current_cycle_due


@dataclass(frozen=True)
class ExtraLine:
    bill_id: int
    name: str
    reason: str
    amount_cents: int
    count: int


@dataclass(frozen=True)
class MonthBreakdown:
    year: int
    month: int
    usual_low_cents: int
    usual_high_cents: int
    extras: list
    ends: list
    total_high_cents: int


def usual_range(bill, payments):
    """Return (lo_cents, hi_cents) from a bill's own last 6 payments.

    Falls back to (amount_cents, amount_cents) when fewer than 3 payments
    for this bill exist.
    """
    bill_payments = sorted(
        (p for p in payments if p.bill_id == bill.id), key=lambda p: p.date
    )
    recent = bill_payments[-6:]
    if len(recent) >= 3:
        amounts = [p.amount_cents for p in recent]
        return (min(amounts), max(amounts))
    return (bill.amount_cents, bill.amount_cents)


def _has_occurrence_before(bill, first: date) -> bool:
    return current_cycle_due(bill, first - timedelta(days=1)) is not None


def month_breakdown(bills, payments, year: int, month: int, today: date) -> MonthBreakdown:
    """Build the usual/extra cost breakdown for one calendar month.

    A steady bill (already billing before this month, still active)
    contributes its expected occurrence count at its usual range, plus an
    extra_occurrence line for any occurrences beyond that. A bill with no
    prior occurrence that bills at least once this month is a starts line.
    A bill whose end_date falls in this month counts its occurrences as
    usual and adds an informational ends line (zero cost). Anything else
    contributes nothing.
    """
    first, next_first = month_bounds(year, month)
    usual_low_cents = 0
    usual_high_cents = 0
    extras = []
    ends = []
    for bill in bills:
        occ = project(bill, first, next_first)
        ends_in_month = bill.end_date is not None and first <= bill.end_date < next_first
        if ends_in_month:
            lo, hi = usual_range(bill, payments)
            usual_low_cents += len(occ) * lo
            usual_high_cents += len(occ) * hi
            ends.append(ExtraLine(bill.id, bill.name, "ends", 0, len(occ)))
            continue
        active_this_month = bill.end_date is None or bill.end_date >= first
        if active_this_month and _has_occurrence_before(bill, first):
            base = expected_per_month(bill.cadence)
            lo, hi = usual_range(bill, payments)
            usual_low_cents += base * lo
            usual_high_cents += base * hi
            if len(occ) > base:
                count = len(occ) - base
                extras.append(
                    ExtraLine(bill.id, bill.name, "extra_occurrence", bill.amount_cents * count, count)
                )
        elif len(occ) >= 1:
            extras.append(
                ExtraLine(bill.id, bill.name, "starts", bill.amount_cents * len(occ), len(occ))
            )
    total_high_cents = usual_high_cents + sum(e.amount_cents for e in extras)
    return MonthBreakdown(year, month, usual_low_cents, usual_high_cents, extras, ends, total_high_cents)
