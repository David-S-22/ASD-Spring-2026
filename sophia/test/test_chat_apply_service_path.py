"""Chat apply must obey the same invariants a manual edit does.

Regression suite for the finding that chat writes went through the raw DB
client: a chat update storing next_billing_date="early September" was accepted
and then every bills read 500ed until the row was repaired by hand.
"""
import json

from sophia.backend.clients import bills_db as bills_db_module
from conftest import response_text as _text


def test_chat_apply_update_refuses_a_non_iso_date(live_client):
    """The exact poisoning case: a paraphrased date must be refused, and the
    bills table must still render afterwards."""
    before = bills_db_module.get_bill(5)
    response = live_client.post(
        "/api/chat/apply",
        json={"op": "update", "entity": "bill", "id": 5, "fields": {"next": "early September"}},
    )
    assert response.status_code == 400
    assert "next_billing_date must be YYYY-MM-DD" in response.get_json()["error"]
    assert bills_db_module.get_bill(5) == before
    assert live_client.get("/ui/bills").status_code == 200
    assert live_client.get("/api/bills").status_code == 200


def test_chat_apply_create_refuses_missing_required_fields(live_client):
    """An under-specified create (the hallucination backstop's last line) is
    refused by the services layer, exactly like the manual add form."""
    response = live_client.post(
        "/api/chat/apply",
        json={"op": "create", "entity": "bill", "fields": {"name": "Mystery", "amount": 5}},
    )
    assert response.status_code == 400
    assert "missing required fields" in response.get_json()["error"]
    assert not [b for b in bills_db_module.list_bills() if b["name"] == "Mystery"]


def test_chat_apply_refuses_a_raw_amount_cents_key(live_client):
    """The prompt asks for dollars under "amount"; a model that emits
    amount_cents itself is emitting a unit nothing verified ($15 stored as
    15 cents). The raw key must fail loudly, not store silently."""
    response = live_client.post(
        "/api/chat/apply",
        json={
            "op": "create", "entity": "bill",
            "fields": {"name": "Cheap", "amount_cents": 15, "cadence": "monthly",
                       "next_billing_date": "2026-09-10", "type": "subscription"},
        },
    )
    assert response.status_code == 400
    assert "amount_cents" in response.get_json()["error"]
    assert not [b for b in bills_db_module.list_bills() if b["name"] == "Cheap"]


def test_chat_apply_delete_missing_bill_is_a_clean_404(live_client):
    response = live_client.post(
        "/api/chat/apply",
        json={"op": "delete", "entity": "bill", "id": 99999, "fields": None},
    )
    assert response.status_code == 404
    assert response.get_json() == {"error": "bill not found"}


def test_chat_apply_update_with_no_id_is_a_clean_error_not_html(live_client):
    """id=None reaches the DB API as /bills/None, whose 404 body is Flask's
    HTML page. That must come back as a short message, never markup."""
    response = live_client.post(
        "/api/chat/apply",
        json={"op": "update", "entity": "bill", "id": None, "fields": {"end_date": "2026-09-16"}},
    )
    assert response.status_code == 404
    error = response.get_json()["error"]
    assert "<" not in error and len(error) < 120


def test_ui_chat_apply_malformed_fields_is_422_not_500(live_client):
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "update", "entity": "bill", "id": "5", "fields": "{not json"},
    )
    assert response.status_code == 422
    assert "fields must be JSON" in _text(response)


def test_chat_apply_create_syncs_the_status_cache(live_client):
    """Routing through the services layer buys status-cache sync for free; a
    chat-created bill must carry the same derived status a manual one would."""
    fields = {"name": "StatusCheck", "amount": 12.5, "cadence": "monthly",
              "next_billing_date": "2026-09-15", "type": "subscription"}
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "create", "entity": "bill", "fields": json.dumps(fields)},
    )
    assert response.status_code == 200
    created = next(b for b in bills_db_module.list_bills() if b["name"] == "StatusCheck")
    assert created["amount_cents"] == 1250
    assert created["source"] == "chat"
    assert created["status"] == "due"


def test_created_bills_are_stamped_on_the_demo_clock(live_client):
    """The DB stamps created_at with real UTC now; the app reasons in
    DEMO_TODAY. projection drops occurrences before created_at, so a bill
    created 'after' its own next charge was in the table but missing from the
    timeline. Creation must stamp the demo clock."""
    fields = {"name": "ClockCheck", "amount": 9.0, "cadence": "weekly",
              "next_billing_date": "2026-08-21", "type": "bill"}
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "create", "entity": "bill", "fields": json.dumps(fields)},
    )
    assert response.status_code == 200
    created = next(b for b in bills_db_module.list_bills() if b["name"] == "ClockCheck")
    assert created["created_at"] == "2026-08-20"
    timeline = live_client.get("/api/timeline").get_json()
    assert any(i["name"] == "ClockCheck" and i["date"] == "2026-08-21" for i in timeline["items"])
