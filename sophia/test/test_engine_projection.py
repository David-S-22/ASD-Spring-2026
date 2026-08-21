"""Tests for sophia.backend.engine.projection: occurrence projection and timeline."""
from datetime import date, timedelta

from sophia.backend.engine import Payment
from sophia.backend.engine.projection import project, tag_kind, timeline
from conftest import make_bill


def test_fortnightly_september_occurrences():
    bill = make_bill(cadence="fortnightly", amount_cents=1750, next_billing_date=date(2026, 8, 18))
    occ = project(bill, date(2026, 9, 1), date(2026, 10, 1))
    assert [o.date for o in occ] == [date(2026, 9, 1), date(2026, 9, 15), date(2026, 9, 29)]


def test_fortnightly_alternate_anchor_gives_two_in_september():
    bill = make_bill(cadence="fortnightly", amount_cents=1750, next_billing_date=date(2026, 9, 5))
    occ = project(bill, date(2026, 9, 1), date(2026, 10, 1))
    assert [o.date for o in occ] == [date(2026, 9, 5), date(2026, 9, 19)]


def test_weekly_september_occurrences():
    bill = make_bill(cadence="weekly", amount_cents=3850, next_billing_date=date(2026, 8, 25))
    occ = project(bill, date(2026, 9, 1), date(2026, 10, 1))
    assert [o.date for o in occ] == [
        date(2026, 9, 1),
        date(2026, 9, 8),
        date(2026, 9, 15),
        date(2026, 9, 22),
        date(2026, 9, 29),
    ]


def test_days_clamped_to_30_and_180():
    bill = make_bill(cadence="weekly", next_billing_date=date(2026, 8, 20))
    today = date(2026, 8, 20)
    assert [o.date for o in timeline([bill], [], today, 29)] == [
        o.date for o in timeline([bill], [], today, 30)
    ]
    assert [o.date for o in timeline([bill], [], today, 181)] == [
        o.date for o in timeline([bill], [], today, 180)
    ]


def test_timeline_window_is_half_open_and_includes_today():
    bill = make_bill(cadence="weekly", next_billing_date=date(2026, 8, 20))
    today = date(2026, 8, 20)
    occ = timeline([bill], [], today, 30)
    assert occ[0].date == today
    window_end = today + timedelta(days=30)
    assert all(today <= o.date < window_end for o in occ)


def test_end_date_before_window_gives_zero_occurrences():
    bill = make_bill(
        cadence="monthly",
        next_billing_date=date(2026, 6, 1),
        end_date=date(2026, 7, 1),
    )
    occ = project(bill, date(2026, 8, 1), date(2026, 9, 1))
    assert occ == []


def test_tag_kind_actual_within_three_days_predicted_beyond():
    bill = make_bill(cadence="monthly", amount_cents=2099, next_billing_date=date(2026, 9, 1))
    occurrence = project(bill, date(2026, 9, 1), date(2026, 10, 1))[0]
    close_payment = Payment(bill_id=bill.id, date=date(2026, 9, 3), amount_cents=bill.amount_cents)
    far_payment = Payment(bill_id=bill.id, date=date(2026, 9, 5), amount_cents=bill.amount_cents)
    assert tag_kind(occurrence, [close_payment]) == "actual"
    assert tag_kind(occurrence, [far_payment]) == "predicted"


def test_timeline_is_deterministic():
    bill = make_bill(cadence="monthly", next_billing_date=date(2026, 9, 1))
    today = date(2026, 8, 20)
    assert timeline([bill], [], today, 60) == timeline([bill], [], today, 60)
