"""Tests for sophia.backend.engine.dates: month arithmetic and cadence stepping."""
import os
import re
from datetime import date

from sophia.backend.engine import dates as dates_module
from sophia.backend.engine.dates import add_cadence, add_months, expected_per_month, month_bounds


def test_add_months_end_of_month_sequence():
    anchor = date(2026, 8, 31)
    expected = [
        date(2026, 9, 30),
        date(2026, 10, 31),
        date(2026, 11, 30),
        date(2026, 12, 31),
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
    ]
    for n, exp in enumerate(expected, start=1):
        assert add_months(anchor, n) == exp


def test_add_months_from_jan30():
    anchor = date(2027, 1, 30)
    assert add_months(anchor, 1) == date(2027, 2, 28)
    assert add_months(anchor, 2) == date(2027, 3, 30)


def test_add_months_negative():
    assert add_months(date(2027, 3, 31), -1) == date(2027, 2, 28)


def test_add_months_leap_year_anchor():
    anchor = date(2028, 2, 29)
    assert add_months(anchor, 1) == date(2028, 3, 29)
    assert add_months(anchor, 12) == date(2029, 2, 28)


def test_add_cadence_weekly_and_fortnightly():
    assert add_cadence(date(2026, 8, 25), "weekly", 1) == date(2026, 9, 1)
    assert add_cadence(date(2026, 8, 18), "fortnightly", 1) == date(2026, 9, 1)


def test_add_cadence_monthly_delegates_to_add_months():
    assert add_cadence(date(2026, 8, 31), "monthly", 1) == date(2026, 9, 30)


def test_month_bounds():
    assert month_bounds(2026, 9) == (date(2026, 9, 1), date(2026, 10, 1))
    assert month_bounds(2026, 12) == (date(2026, 12, 1), date(2027, 1, 1))


def test_expected_per_month():
    assert expected_per_month("weekly") == 4
    assert expected_per_month("fortnightly") == 2
    assert expected_per_month("monthly") == 1


def test_no_wall_clock_calls_in_engine():
    engine_dir = os.path.dirname(dates_module.__file__)
    pattern = re.compile(r"date\.today\(|datetime\.now\(")
    offenders = []
    for root, _dirs, files in os.walk(engine_dir):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(root, filename)
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
            if pattern.search(content):
                offenders.append(path)
    assert offenders == []
