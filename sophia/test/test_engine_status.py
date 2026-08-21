"""Tests for sophia.backend.engine.status: paid/due/overdue derivation."""
from datetime import date

from sophia.backend.engine import Payment
from sophia.backend.engine.status import current_cycle_due, derive_status
from conftest import make_bill


def test_netflix_first_charge_has_no_due_now():
    bill = make_bill(
        id=4,
        name="Netflix",
        cadence="monthly",
        amount_cents=2099,
        next_billing_date=date(2026, 9, 2),
        created_at=date(2026, 8, 19),
    )
    today = date(2026, 8, 20)
    assert current_cycle_due(bill, today) is None
    status, label = derive_status(bill, [], today)
    assert status == "due"
    assert label == "First charge 2 Sep"


def test_internet_overdue_then_paid():
    bill = make_bill(
        id=7,
        name="Home internet",
        cadence="monthly",
        amount_cents=7900,
        payment_method="bpay",
        next_billing_date=date(2026, 8, 15),
        created_at=date(2026, 1, 15),
    )
    today = date(2026, 8, 20)
    late_payment = Payment(bill_id=7, date=date(2026, 7, 15), amount_cents=7900)
    status, label = derive_status(bill, [late_payment], today)
    assert status == "overdue"
    assert label == "Overdue 5 days"

    on_time_payment = Payment(bill_id=7, date=date(2026, 8, 18), amount_cents=7900)
    status, _ = derive_status(bill, [late_payment, on_time_payment], today)
    assert status == "paid"


def test_rent_paid_then_due_today_then_overdue():
    bill = make_bill(
        id=1,
        name="Rent",
        cadence="monthly",
        amount_cents=110000,
        payment_method="direct_debit",
        next_billing_date=date(2026, 9, 1),
        created_at=date(2026, 3, 1),
    )
    payments = [Payment(bill_id=1, date=date(2026, 8, 1), amount_cents=110000)]

    status, label = derive_status(bill, payments, date(2026, 8, 20))
    assert status == "paid"
    assert label == "Paid for Aug"

    status, label = derive_status(bill, payments, date(2026, 9, 1))
    assert status == "due"
    assert label == "Due today"

    status, _ = derive_status(bill, payments, date(2026, 9, 2))
    assert status == "overdue"


def test_next_occurrence_for_31st_anchor_does_not_drift():
    bill = make_bill(
        id=8,
        name="Phone plan",
        cadence="monthly",
        amount_cents=4900,
        payment_method="card",
        next_billing_date=date(2026, 8, 31),
        created_at=date(2026, 1, 31),
    )
    payments = [Payment(bill_id=8, date=date(2027, 2, 28), amount_cents=4900)]
    status, label = derive_status(bill, payments, date(2027, 3, 25))
    assert status == "paid"
    assert label == "Due 31 Mar"
