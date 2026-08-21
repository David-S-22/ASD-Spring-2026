"""Shared fixtures and factories for the bills engine test suite."""
from datetime import date

import pytest

from sophia.backend.engine import Bill, Payment

TODAY = date(2026, 8, 20)


@pytest.fixture
def today():
    return TODAY


def make_bill(**overrides):
    """Build a Bill with sensible defaults, overridden per test."""
    defaults = dict(
        id=1,
        name="Test Bill",
        merchant="Test Merchant",
        amount_cents=1000,
        cadence="monthly",
        next_billing_date=date(2026, 9, 1),
        type="bill",
        payment_method="card",
        end_date=None,
        confirmed_at=None,
        created_at=None,
    )
    defaults.update(overrides)
    return Bill(**defaults)


def make_payment(bill_id, payment_date, amount_cents):
    """Build a Payment for the given bill."""
    return Payment(bill_id=bill_id, date=payment_date, amount_cents=amount_cents)
