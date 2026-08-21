"""Calendar month parsing shared by /api/calendar*, /api/calendar, and /ui/calendar."""
from datetime import date

from sophia.backend.services.errors import ServiceError


def parse_year_month(value):
    """Parse a "YYYY-MM" string into (year, month); raise ServiceError on anything else."""
    try:
        year_str, month_str = value.split("-")
        year, month = int(year_str), int(month_str)
        date(year, month, 1)
    except (ValueError, AttributeError, TypeError):
        raise ServiceError("month must be YYYY-MM")
    return year, month
