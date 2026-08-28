"""Tests for the sophia/backend Flask app against a monkeypatched bills_db client, no network."""
import json
from datetime import date

import pytest
import requests

from sophia.backend import app as backend_app_module
from sophia.backend import config
from sophia.backend.ai import chat_prompt
from sophia.backend.clients import bills_db as bills_db_module
from sophia.backend.clients import transactions as transactions_module
from sophia.backend.engine.status import derive_status

BILLS = [
    {
        "id": 1, "name": "Rent", "merchant": "Harbourview Realty", "amount_cents": 110000,
        "cadence": "monthly", "next_billing_date": "2026-09-01", "type": "bill",
        "payment_method": "direct_debit", "status": "due", "end_date": None,
        "source": "manual", "confirmed_at": "2026-08-01", "created_at": "2026-03-01",
    },
    {
        "id": 3, "name": "Spotify", "merchant": "Spotify AU", "amount_cents": 1399,
        "cadence": "monthly", "next_billing_date": "2026-08-16", "type": "subscription",
        "payment_method": "card", "status": "due", "end_date": None,
        "source": "manual", "confirmed_at": "2026-08-16", "created_at": "2026-02-16",
    },
]

PAYMENTS = [
    {"id": 1, "bill_id": 1, "date": "2026-08-01", "amount_cents": 110000},
    {"id": 2, "bill_id": 3, "date": "2026-08-16", "amount_cents": 1399},
    {"id": 3, "bill_id": 3, "date": "2026-09-15", "amount_cents": 1399},
]


class FakeStore:
    """In-memory stand-in for sophia/database's HTTP API, wired in via monkeypatch."""

    def __init__(self):
        self.bills = {b["id"]: dict(b) for b in BILLS}
        self.payments = {p["id"]: dict(p) for p in PAYMENTS}
        self.disputes = {}
        self.drafts = {}
        self.chat_messages = {}
        self._next_payment_id = 4
        self._next_dispute_id = 1
        self._next_draft_id = 1
        self._next_chat_id = 1

    def list_bills(self):
        return [dict(b) for b in self.bills.values()]

    def get_bill(self, bill_id):
        row = self.bills.get(bill_id)
        return dict(row) if row else None

    def update_bill(self, bill_id, payload):
        self.bills[bill_id].update(payload)
        return dict(self.bills[bill_id])

    def create_bill(self, payload):
        new_id = max(self.bills) + 1 if self.bills else 1
        row = dict(payload)
        row["id"] = new_id
        row.setdefault("status", "due")
        row.setdefault("source", "manual")
        self.bills[new_id] = row
        return dict(row)

    def delete_bill(self, bill_id):
        self.bills.pop(bill_id, None)
        return {"deleted": bill_id}

    def list_bill_payments(self, bill_id):
        return [dict(p) for p in self.payments.values() if p["bill_id"] == bill_id]

    def list_payments(self):
        return [dict(p) for p in self.payments.values()]

    def get_payment(self, payment_id):
        row = self.payments.get(payment_id)
        return dict(row) if row else None

    def create_payment(self, payload):
        new_id = self._next_payment_id
        self._next_payment_id += 1
        row = dict(payload)
        row["id"] = new_id
        self.payments[new_id] = row
        return dict(row)

    def update_payment(self, payment_id, payload):
        self.payments[payment_id].update(payload)
        return dict(self.payments[payment_id])

    def delete_payment(self, payment_id):
        self.payments.pop(payment_id, None)
        return {"deleted": payment_id}

    def list_disputes(self):
        return [dict(d) for d in self.disputes.values()]

    def create_dispute(self, payload):
        new_id = self._next_dispute_id
        self._next_dispute_id += 1
        row = dict(payload)
        row["id"] = new_id
        row.setdefault("status", "draft")
        row.setdefault("opened_at", "2026-08-20")
        self.disputes[new_id] = row
        return dict(row)

    def get_dispute(self, dispute_id):
        row = self.disputes.get(dispute_id)
        return dict(row) if row else None

    def update_dispute(self, dispute_id, payload):
        self.disputes[dispute_id].update(payload)
        return dict(self.disputes[dispute_id])

    def delete_dispute(self, dispute_id):
        self.disputes.pop(dispute_id, None)
        return {"deleted": dispute_id}

    def list_dispute_drafts(self, dispute_id):
        return [dict(d) for d in self.drafts.values() if d["dispute_id"] == dispute_id]

    def create_dispute_draft(self, dispute_id, payload):
        new_id = self._next_draft_id
        self._next_draft_id += 1
        existing = [d for d in self.drafts.values() if d["dispute_id"] == dispute_id]
        version = max((d["version"] for d in existing), default=0) + 1
        steps_json = payload["steps_json"]
        if not isinstance(steps_json, str):
            steps_json = json.dumps(steps_json)
        row = {
            "id": new_id, "dispute_id": dispute_id, "version": version,
            "letter_text": payload["letter_text"], "steps_json": steps_json,
            "created_at": "2026-08-20",
        }
        self.drafts[new_id] = row
        return dict(row)

    def list_chat_messages(self):
        return [dict(m) for m in self.chat_messages.values()]

    def create_chat_message(self, payload):
        new_id = self._next_chat_id
        self._next_chat_id += 1
        row = dict(payload)
        row["id"] = new_id
        row.setdefault("applied", 0)
        row.setdefault("op_json", None)
        row.setdefault("created_at", "2026-08-20T09:00:00")
        self.chat_messages[new_id] = row
        return dict(row)

    def update_chat_message(self, message_id, payload):
        self.chat_messages[message_id].update(payload)
        return dict(self.chat_messages[message_id])

    def health(self):
        return {"ok": True}


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    for name in (
        "list_bills", "get_bill", "update_bill", "create_bill", "delete_bill", "list_bill_payments",
        "list_payments", "get_payment", "create_payment", "update_payment", "delete_payment",
        "list_disputes", "create_dispute", "get_dispute", "update_dispute", "delete_dispute",
        "list_dispute_drafts", "create_dispute_draft", "list_chat_messages", "create_chat_message",
        "update_chat_message", "health",
    ):
        monkeypatch.setattr(bills_db_module, name, getattr(fake, name))
    monkeypatch.setattr(config, "DEMO_TODAY", date(2026, 8, 20))
    monkeypatch.setattr(transactions_module, "list_transactions", lambda merchant=None, since=None: ([], "stub"))
    return fake


@pytest.fixture
def client(store):
    app = backend_app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_timeline_tags_and_display_amount_formatting(client):
    response = client.get("/api/timeline?days=30")
    assert response.status_code == 200
    items_by_bill = {item["bill_id"]: item for item in response.get_json()["items"]}

    assert items_by_bill[1]["kind"] == "predicted"
    assert items_by_bill[1]["display_amount"] == "$1,100"

    assert items_by_bill[3]["kind"] == "actual"
    assert items_by_bill[3]["display_amount"] == "$13.99"


def test_calendar_matches_engine_directly(client, store):
    response = client.get("/api/calendar/2026-09")
    assert response.status_code == 200
    data = response.get_json()

    from sophia.backend.engine.calendar import month_breakdown

    bills = [bills_db_module.row_to_bill(r) for r in store.list_bills()]
    payments = [bills_db_module.row_to_payment(r) for r in store.list_payments()]
    expected = month_breakdown(bills, payments, 2026, 9, date(2026, 8, 20))

    assert data["usual_low_cents"] == expected.usual_low_cents
    assert data["usual_high_cents"] == expected.usual_high_cents
    assert data["total_high_cents"] == expected.total_high_cents


def test_payment_post_refreshes_owning_bill_status(client, store):
    store.bills[3]["status"] = "overdue"
    response = client.post("/api/payments", json={"bill_id": 3, "date": "2026-09-16", "amount_cents": 1399})
    assert response.status_code == 201

    bill = bills_db_module.row_to_bill(store.bills[3])
    payments = [bills_db_module.row_to_payment(p) for p in store.payments.values()]
    expected_status, _label = derive_status(bill, payments, date(2026, 8, 20))
    assert store.bills[3]["status"] == expected_status
    assert expected_status != "overdue"


def test_chat_only_writes_chat_messages_and_apply_uses_crud(client, store, monkeypatch):
    def fake_chat(model, messages, timeout=None):
        content = json.dumps(
            {
                "op": "update", "entity": "bill", "id": 3, "fields": {"end_date": "2026-09-16"},
                "question": "none", "say": "Mark Spotify as ending after 16 Sep.",
            }
        )
        return {"message": {"content": content}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)

    bills_before = {k: dict(v) for k, v in store.bills.items()}
    response = client.post("/api/chat", json={"message": "I cancelled Spotify from September"})
    assert response.status_code == 200
    data = response.get_json()
    preview = dict(data["preview"])
    message_id = preview.pop("message_id", None)
    assert preview == {"op": "update", "entity": "bill", "id": 3, "fields": {"end_date": "2026-09-16"}}
    assert message_id is not None
    assert store.bills == bills_before
    assert len(store.chat_messages) == 2
    assert {m["role"] for m in store.chat_messages.values()} == {"user", "assistant"}

    apply_response = client.post("/api/chat/apply", json=data["preview"])
    assert apply_response.status_code == 200
    assert store.bills[3]["end_date"] == "2026-09-16"


def test_guard_falls_back_when_ollama_unreachable(client, monkeypatch):
    def raise_connection_error(model, messages, timeout=None):
        raise requests.ConnectionError("unreachable")

    monkeypatch.setattr("sophia.backend.ai.guard.chat", raise_connection_error)
    response = client.post("/api/chat", json={"message": "anything"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["fallback"] is True
    assert data["reply"] == chat_prompt.FALLBACK["say"]


def test_dispute_creation_falls_back_and_adds_direct_debit_step(client, monkeypatch):
    def raise_connection_error(model, messages, timeout=None):
        raise requests.ConnectionError("unreachable")

    monkeypatch.setattr("sophia.backend.ai.guard.chat", raise_connection_error)
    response = client.post("/api/disputes", json={"bill_id": 1, "reason": "Charged after cancellation"})
    assert response.status_code == 201
    data = response.get_json()
    assert data["draft"]["fallback"] is True
    assert any("authority" in step.lower() or "direct debit" in step.lower() for step in data["draft"]["steps"])


def test_barely_using_flags_bills_billed_repeatedly_since_confirmation(client, store, monkeypatch):
    store.bills[12] = {
        "id": 12, "name": "DriveBox", "merchant": "DriveBox", "amount_cents": 299,
        "cadence": "monthly", "next_billing_date": "2026-08-28", "type": "subscription",
        "payment_method": "card", "status": "due", "end_date": None,
        "source": "manual", "confirmed_at": "2026-03-28", "created_at": "2026-03-28",
    }
    for payment_id, payment_date in enumerate(
        ["2026-04-28", "2026-05-28", "2026-06-28", "2026-07-28"], start=100
    ):
        store.payments[payment_id] = {"id": payment_id, "bill_id": 12, "date": payment_date, "amount_cents": 299}

    store.bills[3]["confirmed_at"] = "2026-08-16"
    store.payments = {
        k: v for k, v in store.payments.items() if not (v["bill_id"] == 3 and v["date"] >= "2026-08-16")
    }

    def fake_chat(model, messages, timeout=None):
        content = json.dumps(
            {"op": None, "entity": None, "id": None, "fields": None, "question": "barely_using", "say": ""}
        )
        return {"message": {"content": content}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    response = client.post("/api/chat", json={"message": "Which subscriptions am I barely using?"})
    assert response.status_code == 200
    reply = response.get_json()["reply"]
    assert (
        "DriveBox has billed four times since you last confirmed you're using it — worth a look at $2.99/month."
        in reply
    )
    assert "Spotify" not in reply


def test_handoff_urls_start_with_configured_frontend_origin(client, store):
    response = client.post(
        "/api/handoff/recurring", json={"source": "transactions", "merchant": "Spotify AU", "intent": "end"}
    )
    assert response.status_code == 200
    assert response.get_json()["ui_url"].startswith(config.FRONTEND_ORIGIN)

    created = client.post(
        "/api/suggestions",
        json={
            "source": "alerts", "alert_id": 7, "merchant": "StreamCo", "amount": 1299,
            "cadence": "monthly", "last_seen": "2026-08-01", "occurrences": 4,
        },
    )
    assert created.status_code == 201
    assert created.get_json()["confirm_url"].startswith(config.FRONTEND_ORIGIN)
