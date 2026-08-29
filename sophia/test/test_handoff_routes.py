"""Tests for the inbound handoff routes, against the FakeStore pattern from test_backend_routes."""
from datetime import date

import pytest

from sophia.backend import app as backend_app_module
from sophia.backend import config
from sophia.backend.clients import bills_db as bills_db_module
from sophia.backend.clients import transactions as transactions_module
from test_backend_routes import FAKE_STORE_METHODS, FakeStore


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    for name in FAKE_STORE_METHODS:
        monkeypatch.setattr(bills_db_module, name, getattr(fake, name))
    monkeypatch.setattr(config, "DEMO_TODAY", date(2026, 8, 20))
    monkeypatch.setattr(transactions_module, "list_transactions", lambda merchant=None, since=None: ([], "stub"))
    return fake


@pytest.fixture
def client(store):
    app = backend_app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_recurring_end_for_known_merchant_uses_effective_from(client):
    response = client.post(
        "/api/handoff/recurring",
        json={"source": "transactions", "merchant": "Spotify AU", "intent": "end", "effective_from": "2026-09-01"},
    )
    assert response.status_code == 200
    op = response.get_json()["preview"]["op"]
    assert op == {"op": "update", "entity": "bill", "id": 3, "fields": {"end_date": "2026-09-01"}}


def test_recurring_end_defaults_to_demo_today(client):
    response = client.post(
        "/api/handoff/recurring", json={"source": "transactions", "merchant": "Spotify AU", "intent": "end"}
    )
    op = response.get_json()["preview"]["op"]
    assert op["fields"] == {"end_date": config.DEMO_TODAY.isoformat()}


def test_recurring_change_amount_targets_matched_bill(client):
    response = client.post(
        "/api/handoff/recurring",
        json={"source": "transactions", "merchant": "Spotify AU", "intent": "change_amount", "amount": 1499},
    )
    op = response.get_json()["preview"]["op"]
    assert op == {"op": "update", "entity": "bill", "id": 3, "fields": {"amount_cents": 1499}}


def test_recurring_unknown_merchant_previews_a_create(client):
    response = client.post(
        "/api/handoff/recurring",
        json={"source": "transactions", "merchant": "Fresh Gym", "intent": "create", "amount": 4200},
    )
    op = response.get_json()["preview"]["op"]
    assert op == {
        "op": "create",
        "entity": "bill",
        "id": None,
        "fields": {"merchant": "Fresh Gym", "name": "Fresh Gym", "amount_cents": 4200},
    }


def test_recurring_response_is_preview_only_with_apply_url_and_ui_url(client, store):
    bills_before = {k: dict(v) for k, v in store.bills.items()}
    response = client.post(
        "/api/handoff/recurring", json={"source": "transactions", "merchant": "Spotify AU", "intent": "end"}
    )
    data = response.get_json()
    assert data["apply_url"] == "/api/chat/apply"
    assert data["ui_url"].startswith(config.FRONTEND_ORIGIN)
    assert store.bills == bills_before


def test_suggestions_creates_unconfirmed_f4_subscription(client, store):
    response = client.post(
        "/api/suggestions",
        json={
            "source": "alerts", "alert_id": 12, "merchant": "Beem", "amount": 599,
            "cadence": "monthly", "last_seen": "2026-08-10", "occurrences": 3,
        },
    )
    assert response.status_code == 201
    data = response.get_json()
    created = store.bills[data["bill_id"]]
    assert created["source"] == "f4_handoff"
    assert created["confirmed_at"] is None
    assert created["type"] == "subscription"
    assert created["next_billing_date"] == "2026-08-10"
    assert data["confirm_url"].startswith(config.FRONTEND_ORIGIN)
