"""Parametrised tests for the validation branches in the bills and payments services."""
from datetime import date

import pytest

from sophia.backend import config
from sophia.backend.clients import bills_db as bills_db_module
from sophia.backend.services import bills as bills_service
from sophia.backend.services import chat as chat_service
from sophia.backend.services import payments as payments_service
from sophia.backend.services.errors import NotFound, ServiceError
from test_backend_routes import FAKE_STORE_METHODS, FakeStore

VALID_BILL = {
    "name": "Fresh Gym", "merchant": "Fresh Gym", "amount_cents": 4200,
    "cadence": "monthly", "next_billing_date": "2026-09-05", "type": "subscription",
}


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    for name in FAKE_STORE_METHODS:
        monkeypatch.setattr(bills_db_module, name, getattr(fake, name))
    monkeypatch.setattr(config, "DEMO_TODAY", date(2026, 8, 20))
    return fake


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "missing required fields"),
        ({**VALID_BILL, "amount_cents": "twelve"}, "amount_cents must be a whole number"),
        ({**VALID_BILL, "next_billing_date": "soon"}, "next_billing_date must be YYYY-MM-DD"),
        ({**VALID_BILL, "end_date": "never"}, "end_date must be YYYY-MM-DD"),
    ],
)
def test_create_bill_rejects_bad_payloads(store, payload, message):
    with pytest.raises(ServiceError, match=message):
        bills_service.create_bill(payload)


@pytest.mark.parametrize(
    ("end_date", "message"),
    [
        (None, "end_date is required"),
        ("", "end_date is required"),
        ("13/09/2026", "end_date must be YYYY-MM-DD"),
    ],
)
def test_cancel_bill_rejects_bad_end_dates(store, end_date, message):
    with pytest.raises(ServiceError, match=message):
        bills_service.cancel_bill(1, end_date)


@pytest.mark.parametrize(
    "call",
    [
        lambda: bills_service.update_bill(999, {"name": "x"}),
        lambda: bills_service.delete_bill(999),
        lambda: bills_service.confirm_bill(999),
        lambda: bills_service.cancel_bill(999, "2026-09-01"),
    ],
)
def test_bill_writes_raise_not_found_for_unknown_ids(store, call):
    with pytest.raises(NotFound):
        call()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"date": "2026-08-01", "amount_cents": 100}, "bill_id is required"),
        ({"bill_id": "x", "date": "2026-08-01", "amount_cents": 100}, "bill_id must be an integer"),
        ({"bill_id": 1, "amount_cents": 100}, "date is required"),
        ({"bill_id": 1, "date": "01/08/2026", "amount_cents": 100}, "date must be YYYY-MM-DD"),
        ({"bill_id": 1, "date": "2026-08-01"}, "amount_cents is required"),
        ({"bill_id": 1, "date": "2026-08-01", "amount_cents": "ten"}, "amount_cents must be a whole number"),
    ],
)
def test_create_payment_rejects_bad_payloads(store, payload, message):
    with pytest.raises(ServiceError, match=message):
        payments_service.create_payment(payload)


def test_create_payment_for_unknown_bill_raises_not_found(store):
    with pytest.raises(NotFound):
        payments_service.create_payment({"bill_id": 999, "date": "2026-08-01", "amount_cents": 100})


def test_update_payment_recomputes_owning_bill_status(store):
    store.bills[3]["status"] = "stale-status"
    updated = payments_service.update_payment(3, {"date": "2026-08-16"})
    assert updated["date"] == "2026-08-16"
    assert store.bills[3]["status"] != "stale-status"


def test_delete_payment_refreshes_owning_bill(store):
    store.bills[3]["status"] = "stale-status"
    result = payments_service.delete_payment(3)
    assert result == {"deleted": 3}
    assert store.bills[3]["status"] != "stale-status"


def test_refresh_skips_bills_that_no_longer_exist(store):
    store.bills.pop(1)
    result = payments_service.delete_payment(1)
    assert result == {"deleted": 1}


# --- chat field normalisation -------------------------------------------------
# The model is asked for the real column names but drifts predictably; these pin
# the translation, and just as importantly pin that the whitelist still bites.

def test_normalise_maps_amount_dollars_onto_amount_cents():
    out = chat_service._normalise_chat_fields("bill", "create", {"name": "X", "amount": 16.45})
    assert out["amount_cents"] == 1645
    assert "amount" not in out


def test_normalise_maps_next_variants_onto_next_billing_date():
    for alias in ("next", "next_date", "next_billing"):
        out = chat_service._normalise_chat_fields("bill", "create", {alias: "2026-09-05"})
        assert out["next_billing_date"] == "2026-09-05"


def test_normalise_defaults_merchant_to_name_on_create_only():
    created = chat_service._normalise_chat_fields("bill", "create", {"name": "Audible"})
    assert created["merchant"] == "Audible"
    updated = chat_service._normalise_chat_fields("bill", "update", {"name": "Audible"})
    assert "merchant" not in updated


def test_normalise_keeps_an_explicit_merchant():
    out = chat_service._normalise_chat_fields("bill", "create", {"name": "Rent", "merchant": "Harbourview Realty"})
    assert out["merchant"] == "Harbourview Realty"


def test_normalise_rejects_a_non_numeric_amount():
    with pytest.raises(ServiceError) as excinfo:
        chat_service._normalise_chat_fields("bill", "create", {"amount": "lots"})
    assert "must be an amount" in str(excinfo.value.message)


def test_normalise_rejects_conflicting_aliases():
    with pytest.raises(ServiceError):
        chat_service._normalise_chat_fields(
            "bill", "create", {"next": "2026-09-05", "next_billing_date": "2026-10-01"}
        )


def test_normalise_leaves_unknown_fields_for_the_whitelist_to_reject():
    """Normalisation must not quietly swallow an invented field."""
    out = chat_service._normalise_chat_fields("bill", "create", {"name": "X", "colour": "blue"})
    assert out["colour"] == "blue"
