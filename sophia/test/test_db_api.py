"""Tests for the sophia/database Flask CRUD API against a temp SQLite file per test."""
import importlib.util
import os
import sys

import pytest

_DATABASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
if _DATABASE_DIR not in sys.path:
    sys.path.insert(0, _DATABASE_DIR)


def _load_database_app():
    spec = importlib.util.spec_from_file_location("bills_database_app", os.path.join(_DATABASE_DIR, "app.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


database_app = _load_database_app()


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "bills.db")
    connection = database_app.get_connection(db_path)
    database_app.load_schema(connection, database_app.SCHEMA_PATH)
    database_app.seed(connection)
    connection.close()
    app = database_app.create_app(db_path=db_path)
    app.config["TESTING"] = True
    return app.test_client()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_seed_row_counts(client):
    bills = client.get("/bills").get_json()
    payments = client.get("/payments").get_json()
    disputes = client.get("/disputes").get_json()
    chat_messages = client.get("/chat_messages").get_json()
    assert len(bills) >= 10
    assert len(payments) >= 10
    assert len(disputes) >= 10
    assert len(chat_messages) >= 10

    total_drafts = 0
    for dispute in disputes:
        drafts = client.get(f"/disputes/{dispute['id']}/drafts").get_json()
        total_drafts += len(drafts)
    assert total_drafts >= 10


def test_bill_crud_round_trip(client):
    created = client.post(
        "/bills",
        json={
            "name": "Test Streaming",
            "merchant": "Test Merchant",
            "amount_cents": 1299,
            "cadence": "monthly",
            "next_billing_date": "2026-10-01",
            "type": "subscription",
            "payment_method": "card",
        },
    )
    assert created.status_code == 201
    bill_id = created.get_json()["id"]
    assert created.get_json()["status"] == "due"
    assert created.get_json()["source"] == "manual"

    fetched = client.get(f"/bills/{bill_id}")
    assert fetched.status_code == 200
    assert fetched.get_json()["name"] == "Test Streaming"

    updated = client.put(f"/bills/{bill_id}", json={"amount_cents": 1499})
    assert updated.status_code == 200
    assert updated.get_json()["amount_cents"] == 1499

    deleted = client.delete(f"/bills/{bill_id}")
    assert deleted.status_code == 200
    assert client.get(f"/bills/{bill_id}").status_code == 404


def test_payment_round_trip_and_bill_payments_listing(client):
    created = client.post(
        "/payments", json={"bill_id": 1, "date": "2026-08-01", "amount_cents": 110000}
    )
    assert created.status_code == 201
    payment_id = created.get_json()["id"]

    fetched = client.get(f"/payments/{payment_id}")
    assert fetched.status_code == 200

    bill_payments = client.get("/bills/1/payments").get_json()
    assert any(p["id"] == payment_id for p in bill_payments)

    deleted = client.delete(f"/payments/{payment_id}")
    assert deleted.status_code == 200
    assert client.get(f"/payments/{payment_id}").status_code == 404


def test_dispute_and_draft_version_increment(client):
    created = client.post("/disputes", json={"bill_id": 3, "reason": "Test reason"})
    assert created.status_code == 201
    dispute = created.get_json()
    assert dispute["status"] == "draft"

    updated = client.put(f"/disputes/{dispute['id']}", json={"status": "sent"})
    assert updated.status_code == 200
    assert updated.get_json()["status"] == "sent"

    draft1 = client.post(
        f"/disputes/{dispute['id']}/drafts",
        json={"letter_text": "First draft.", "steps_json": {"steps": ["Step one"], "escalation": ["Merchant support"]}},
    )
    assert draft1.status_code == 201
    assert draft1.get_json()["version"] == 1

    draft2 = client.post(
        f"/disputes/{dispute['id']}/drafts",
        json={"letter_text": "Second draft.", "steps_json": {"steps": ["Step one"], "escalation": ["Merchant support"]}},
    )
    assert draft2.status_code == 201
    assert draft2.get_json()["version"] == 2

    drafts = client.get(f"/disputes/{dispute['id']}/drafts").get_json()
    assert [d["version"] for d in drafts] == [1, 2]


def test_chat_messages_post_and_delete_all(client):
    created = client.post("/chat_messages", json={"role": "user", "content": "Test message"})
    assert created.status_code == 201
    assert created.get_json()["applied"] == 0

    deleted = client.delete("/chat_messages")
    assert deleted.status_code == 200
    assert client.get("/chat_messages").get_json() == []


def test_deleting_a_bill_cascades_to_payments_and_disputes(client):
    bill_id = 2
    payments_before = client.get(f"/bills/{bill_id}/payments").get_json()
    disputes_before = client.get("/disputes").get_json()
    dispute_ids = [d["id"] for d in disputes_before if d["bill_id"] == bill_id]
    assert payments_before
    assert dispute_ids

    deleted = client.delete(f"/bills/{bill_id}")
    assert deleted.status_code == 200

    assert client.get(f"/bills/{bill_id}/payments").get_json() == []
    disputes_after = client.get("/disputes").get_json()
    assert all(d["bill_id"] != bill_id for d in disputes_after)
    for dispute_id in dispute_ids:
        assert client.get(f"/disputes/{dispute_id}/drafts").get_json() == []


def test_db_api_has_no_upcoming_route(client):
    assert client.get("/upcoming?days=90").status_code == 404
