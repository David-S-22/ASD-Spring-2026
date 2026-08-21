"""Cents-to-dollar string formatting."""


def format_actual(cents: int) -> str:
    """Format an exact cent amount, e.g. 4200 -> "$42.00", 110000 -> "$1,100.00"."""
    sign = "-" if cents < 0 else ""
    dollars, remainder = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{remainder:02d}"


def _round_half_up_dollars(cents: int) -> int:
    """Round a cent amount to whole dollars, with .50 and above rounding up."""
    dollars, remainder = divmod(abs(cents), 100)
    if remainder >= 50:
        dollars += 1
    return -dollars if cents < 0 else dollars


def format_estimate(lo_cents: int, hi_cents: int) -> str:
    """Format a whole-dollar range, e.g. (37900, 41500) -> "$379–415".

    Equal bounds collapse to a single value, e.g. (37900, 37900) -> "$379".
    """
    lo = _round_half_up_dollars(lo_cents)
    hi = _round_half_up_dollars(hi_cents)
    if lo == hi:
        return f"${lo:,}"
    return f"${lo:,}–{hi:,}"


def format_estimate_single(cents: int) -> str:
    """Format a single amount to whole dollars, e.g. 43600 -> "$436", 4299 -> "$43"."""
    return f"${_round_half_up_dollars(cents):,}"
