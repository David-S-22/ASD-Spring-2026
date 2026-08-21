"""Tests for sophia.backend.engine.calendar: monthly usual/extra breakdown."""
from datetime import date

from sophia.backend.engine import Payment
from sophia.backend.engine.calendar import month_breakdown, usual_range
from conftest import make_bill


def test_fortnightly_extra_occurrence_in_september():
    bill = make_bill(
        cadence="fortnightly",
        amount_cents=1750,
        next_billing_date=date(2026, 8, 18),
        created_at=date(2026, 3, 10),
    )
    breakdown = month_breakdown([bill], [], 2026, 9, date(2026, 8, 20))
    extra = [e for e in breakdown.extras if e.reason == "extra_occurrence"]
    assert len(extra) == 1
    assert extra[0].count == 1


def test_weekly_extra_occurrence_in_september():
    bill = make_bill(
        cadence="weekly",
        amount_cents=3850,
        next_billing_date=date(2026, 8, 25),
        created_at=date(2026, 3, 3),
    )
    breakdown = month_breakdown([bill], [], 2026, 9, date(2026, 8, 20))
    extra = [e for e in breakdown.extras if e.reason == "extra_occurrence"]
    assert len(extra) == 1
    assert extra[0].count == 1


def test_netflix_starts_in_september_and_steady_in_october():
    bill = make_bill(
        id=4,
        name="Netflix",
        cadence="monthly",
        amount_cents=2099,
        next_billing_date=date(2026, 9, 2),
        created_at=date(2026, 8, 19),
    )
    sep = month_breakdown([bill], [], 2026, 9, date(2026, 8, 20))
    starts = [e for e in sep.extras if e.reason == "starts"]
    assert len(starts) == 1
    assert starts[0].amount_cents == 2099

    oct_ = month_breakdown([bill], [], 2026, 10, date(2026, 9, 15))
    assert not [e for e in oct_.extras if e.reason == "starts"]
    assert oct_.usual_high_cents == 2099


def test_spotify_ends_in_september_excluded_from_october():
    bill = make_bill(
        id=3,
        name="Spotify",
        cadence="monthly",
        amount_cents=1399,
        next_billing_date=date(2026, 8, 16),
        end_date=date(2026, 9, 16),
        created_at=date(2026, 2, 16),
    )
    sep = month_breakdown([bill], [], 2026, 9, date(2026, 8, 20))
    assert len(sep.ends) == 1
    assert sep.ends[0].amount_cents == 0
    assert sep.ends[0].count == 1

    oct_ = month_breakdown([bill], [], 2026, 10, date(2026, 9, 20))
    assert oct_.ends == []
    assert oct_.extras == []
    assert oct_.usual_high_cents == 0


def test_usual_range_falls_back_below_three_payments():
    bill = make_bill(amount_cents=1399)
    assert usual_range(bill, []) == (1399, 1399)


def test_usual_range_from_last_six_payments():
    bill = make_bill(id=9, amount_cents=14200)
    payments = [
        Payment(bill_id=9, date=date(2026, 6, 10), amount_cents=12840),
        Payment(bill_id=9, date=date(2026, 7, 10), amount_cents=15120),
        Payment(bill_id=9, date=date(2026, 8, 10), amount_cents=13975),
    ]
    assert usual_range(bill, payments) == (12840, 15120)
