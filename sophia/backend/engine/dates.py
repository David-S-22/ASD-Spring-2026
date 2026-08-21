"""Calendar arithmetic for bill cadences.

Every function is pure and takes each date as an explicit argument; nothing
in this module reads the system clock.
"""
from calendar import monthrange
from datetime import date, timedelta


def add_months(anchor: date, n: int) -> date:
    """Add n calendar months to anchor.

    The day is clamped to the target month's length (e.g. 31 Aug + 1 month
    is 30 Sep). Computed directly from the anchor, never iteratively. n may
    be negative.
    """
    month_index = anchor.month - 1 + n
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    day = min(anchor.day, monthrange(year, month)[1])
    return date(year, month, day)


def add_cadence(anchor: date, cadence: str, n: int) -> date:
    """Add n cadence steps to anchor for a weekly, fortnightly, or monthly cadence."""
    if cadence == "weekly":
        return anchor + timedelta(weeks=n)
    if cadence == "fortnightly":
        return anchor + timedelta(weeks=2 * n)
    if cadence == "monthly":
        return add_months(anchor, n)
    raise ValueError(f"unknown cadence: {cadence}")


def month_bounds(y: int, m: int) -> tuple[date, date]:
    """Return (first day of month, first day of the following month)."""
    first = date(y, m, 1)
    if m == 12:
        next_first = date(y + 1, 1, 1)
    else:
        next_first = date(y, m + 1, 1)
    return first, next_first


def expected_per_month(cadence: str) -> int:
    """Return the expected occurrence count per calendar month for a cadence."""
    return {"weekly": 4, "fortnightly": 2, "monthly": 1}[cadence]
