"""B2 pure-read tests: GETs never write the cached status column; write paths refresh it.

Uses the FakeStore pattern from test_backend_routes, with update_bill instrumented
so every write to the store is visible to the assertions. Both seeded FakeStore
bills (Rent, Spotify) store status "due" while derivation says "paid" at
DEMO_TODAY=2026-08-20, so the store starts drifted without extra setup.
"""
from datetime import date

import pytest

from sophia.backend import app as backend_app_module
from sophia.backend import config
from sophia.backend.clients import bills_db as bills_db_module
from sophia.backend.clients import transactions as transactions_module
from test_backend_routes import FAKE_STORE_METHODS, FakeStore


class CountingStore(FakeStore):
    """FakeStore that records every update_bill call as (bill_id, payload)."""

    def __init__(self):
        super().__init__()
        self.update_bill_calls = []

    def update_bill(self, bill_id, payload):
        self.update_bill_calls.append((bill_id, dict(payload)))
        return super().update_bill(bill_id, payload)

    def create_bill(self, payload):
        row = dict(payload)
        row.setdefault("created_at", "2026-08-20")  # :6005 stamps created_at on create (NOT NULL)
        return super().create_bill(row)


@pytest.fixture
def store(monkeypatch):
    fake = CountingStore()
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


def test_list_bills_returns_derived_status_and_never_writes(client, store):
    response = client.get("/api/bills")
    assert response.status_code == 200
    statuses = {b["id"]: b["status"] for b in response.get_json()}
    assert statuses[1] == "paid"
    assert statuses[3] == "paid"
    assert store.update_bill_calls == []
    assert store.bills[1]["status"] == "due"
    assert store.bills[3]["status"] == "due"


def test_get_bill_returns_derived_status_and_never_writes(client, store):
    response = client.get("/api/bills/3")
    assert response.status_code == 200
    assert response.get_json()["status"] == "paid"
    assert store.update_bill_calls == []
    assert store.bills[3]["status"] == "due"


def test_status_filter_uses_derived_status_without_writes(client, store):
    response = client.get("/api/bills?status=due")
    assert response.status_code == 200
    assert response.get_json() == []
    assert store.update_bill_calls == []


def test_update_bill_refreshes_cache_with_exactly_one_status_write(client, store):
    response = client.put("/api/bills/3", json={"name": "Spotify Premium"})
    assert response.status_code == 200
    assert response.get_json()["status"] == "paid"
    assert store.update_bill_calls == [
        (3, {"name": "Spotify Premium"}),
        (3, {"status": "paid"}),
    ]
    assert store.bills[3]["status"] == "paid"


def test_update_bill_without_drift_writes_payload_only(client, store):
    store.bills[3]["status"] = "paid"
    response = client.put("/api/bills/3", json={"name": "Spotify Premium"})
    assert response.status_code == 200
    assert store.update_bill_calls == [(3, {"name": "Spotify Premium"})]


def test_create_bill_with_past_next_billing_date_caches_overdue(client, store):
    response = client.post(
        "/api/bills",
        json={
            "name": "Water", "merchant": "Sydney Water", "amount_cents": 9000,
            "cadence": "monthly", "next_billing_date": "2026-08-01", "type": "bill",
        },
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "overdue"
    assert store.bills[body["id"]]["status"] == "overdue"
    assert store.update_bill_calls == [(body["id"], {"status": "overdue"})]


def test_create_bill_with_future_next_billing_date_writes_nothing_extra(client, store):
    response = client.post(
        "/api/bills",
        json={
            "name": "Water", "merchant": "Sydney Water", "amount_cents": 9000,
            "cadence": "monthly", "next_billing_date": "2026-09-01", "type": "bill",
        },
    )
    assert response.status_code == 201
    assert response.get_json()["status"] == "due"
    assert store.update_bill_calls == []


def test_cancel_bill_refreshes_drifted_cache(client, store):
    response = client.post("/ui/bills/3/cancel", data={"end_date": "2026-09-30"})
    assert response.status_code == 200
    assert (3, {"end_date": "2026-09-30"}) in store.update_bill_calls
    assert store.bills[3]["status"] == "paid"
