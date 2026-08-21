"""Tests for the /ui/* write routes (addendum 1): HTML back, HX-Trigger toast,
DB state actually changed, oob timeline/calendar where the write affects
dates, 422 + error fragment on validation failure, and that /api/* returns a
clean 400 (never 500) on a non-JSON body.

Uses the live_client fixture from conftest.py (real sophia/database in a
background thread, temp seeded SQLite) so "DB state changed" is checked
against the real service, not a mock.
"""
import json

from sophia.backend.clients import bills_db as bills_db_module
from conftest import response_text as _text


_bill_counter = [0]


def _add_bill(client, **overrides):
    _bill_counter[0] += 1
    form = {
        "name": f"Test Streaming {_bill_counter[0]}",
        "merchant": "Test Merchant",
        "amount": "12.50",
        "cadence": "monthly",
        "next_billing_date": "2026-10-01",
        "type": "subscription",
        "payment_method": "card",
    }
    form.update(overrides)
    response = client.post("/ui/bills", data=form)
    assert response.status_code == 201, response.get_data(as_text=True)
    bills = bills_db_module.list_bills()
    created = max(bills, key=lambda b: b["id"])
    return created["id"], response, form["name"]


def test_post_ui_bills_add_returns_html_and_toast_and_oob(live_client):
    bill_id, response, bill_name = _add_bill(live_client)
    assert response.content_type.startswith("text/html")
    assert "HX-Trigger" in response.headers
    assert json.loads(response.headers["HX-Trigger"]) == {"toast": "Done — change saved."}
    body = response.get_data(as_text=True)
    assert 'id="timeline"' in body and 'hx-swap-oob="true"' in body
    assert 'id="calendar-card"' in body

    fetched = bills_db_module.get_bill(bill_id)
    assert fetched["name"] == bill_name


def test_post_ui_bills_edit_changes_db_and_returns_oob(live_client):
    bill_id, _response, _name = _add_bill(live_client)
    response = live_client.post(
        f"/ui/bills/{bill_id}/edit",
        data={
            "name": "Renamed Streaming", "merchant": "Test Merchant", "amount": "15.00", "cadence": "monthly",
            "next_billing_date": "2026-10-01", "type": "subscription", "payment_method": "card",
        },
    )
    assert response.status_code == 200
    assert json.loads(response.headers["HX-Trigger"]) == {"toast": "Done — change saved."}
    assert 'hx-swap-oob="true"' in response.get_data(as_text=True)
    assert bills_db_module.get_bill(bill_id)["name"] == "Renamed Streaming"


def test_post_ui_bills_cancel_sets_end_date_and_drops_from_timeline(live_client):
    bill_id, _response, bill_name = _add_bill(live_client, next_billing_date="2026-08-25", cadence="weekly")
    before = live_client.get("/ui/timeline?days=30").get_data(as_text=True)
    assert bill_name in before

    response = live_client.post(f"/ui/bills/{bill_id}/cancel", data={"end_date": "2026-08-20"})
    assert response.status_code == 200
    assert json.loads(response.headers["HX-Trigger"]) == {"toast": "Done — change saved."}
    assert bills_db_module.get_bill(bill_id)["end_date"] == "2026-08-20"

    after = live_client.get("/ui/timeline?days=30").get_data(as_text=True)
    assert bill_name not in after


def test_post_ui_bills_delete_removes_bill_and_returns_removed_toast(live_client):
    bill_id, _response, _name = _add_bill(live_client)
    response = live_client.post(f"/ui/bills/{bill_id}/delete")
    assert response.status_code == 200
    assert json.loads(response.headers["HX-Trigger"]) == {"toast": "Done — removed."}
    assert bills_db_module.get_bill(bill_id) is None


def test_post_ui_bills_confirm_sets_confirmed_at_no_oob_needed(live_client):
    bill_id, _response, _name = _add_bill(live_client)
    response = live_client.post(f"/ui/bills/{bill_id}/confirm")
    assert response.status_code == 200
    assert json.loads(response.headers["HX-Trigger"]) == {"toast": "Done — change saved."}
    assert bills_db_module.get_bill(bill_id)["confirmed_at"] is not None


def test_post_ui_payments_records_payment_and_refreshes_projection(live_client):
    bill_id, _response, _name = _add_bill(live_client)
    response = live_client.post("/ui/payments", data={"bill_id": str(bill_id), "date": "2026-08-20", "amount": "12.50"})
    assert response.status_code == 201, response.get_data(as_text=True)
    assert "HX-Trigger" in response.headers
    assert 'hx-swap-oob="true"' in response.get_data(as_text=True)
    payments = bills_db_module.list_bill_payments(bill_id)
    assert any(p["amount_cents"] == 1250 for p in payments)


def test_post_ui_disputes_creates_dispute_and_targets_dispute_panel(live_client, monkeypatch):
    bill_id, _response, _name = _add_bill(live_client)

    def fake_chat(model, messages, timeout=None):
        content = json.dumps(
            {
                "letter_text": "x" * 100,
                "steps": ["Step one", "Step two"],
                "escalation": ["Merchant support"],
                "payment_method_note": None,
            }
        )
        return {"message": {"content": content}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    response = live_client.post("/ui/disputes", data={"bill_id": str(bill_id), "reason": "Charged twice"})
    assert response.status_code == 201
    assert json.loads(response.headers["HX-Trigger"]) == {"toast": "Done — change saved.", "switchTab": "disputes"}
    assert 'id="dispute-panel"' in response.get_data(as_text=True)

    disputes = bills_db_module.list_disputes()
    assert any(d["bill_id"] == bill_id and d["reason"] == "Charged twice" for d in disputes)


def test_post_ui_disputes_status_updates_status(live_client, monkeypatch):
    bill_id, _response, _name = _add_bill(live_client)

    def fake_chat(model, messages, timeout=None):
        content = json.dumps(
            {"letter_text": "x" * 100, "steps": ["Step one", "Step two"], "escalation": ["Merchant support"], "payment_method_note": None}
        )
        return {"message": {"content": content}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    live_client.post("/ui/disputes", data={"bill_id": str(bill_id), "reason": "Charged twice"})
    dispute_id = next(d["id"] for d in bills_db_module.list_disputes() if d["bill_id"] == bill_id)

    response = live_client.post(f"/ui/disputes/{dispute_id}/status", data={"status": "sent"})
    assert response.status_code == 200
    assert "HX-Trigger" in response.headers
    assert bills_db_module.get_dispute(dispute_id)["status"] == "sent"


def test_post_ui_disputes_regenerate_adds_a_version(live_client, monkeypatch):
    bill_id, _response, _name = _add_bill(live_client)

    def fake_chat(model, messages, timeout=None):
        content = json.dumps(
            {"letter_text": "x" * 100, "steps": ["Step one", "Step two"], "escalation": ["Merchant support"], "payment_method_note": None}
        )
        return {"message": {"content": content}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    live_client.post("/ui/disputes", data={"bill_id": str(bill_id), "reason": "Charged twice"})
    dispute_id = next(d["id"] for d in bills_db_module.list_disputes() if d["bill_id"] == bill_id)

    response = live_client.post(f"/ui/disputes/{dispute_id}/regenerate", data={"feedback": "Make it shorter"})
    assert response.status_code == 200
    assert "HX-Trigger" in response.headers
    drafts = bills_db_module.list_dispute_drafts(dispute_id)
    assert len(drafts) == 2


def test_ui_chat_never_writes_bills_and_apply_does(live_client, monkeypatch):
    bill_id, _response, _name = _add_bill(live_client, cadence="monthly", next_billing_date="2026-10-01")
    before = bills_db_module.get_bill(bill_id)

    def fake_chat(model, messages, timeout=None):
        content = json.dumps(
            {
                "op": "update", "entity": "bill", "id": bill_id, "fields": {"end_date": "2026-09-16"},
                "question": "none", "say": "Marking it as ending.",
            }
        )
        return {"message": {"content": content}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    chat_response = live_client.post("/ui/chat", data={"message": "cancel this"})
    assert chat_response.status_code == 200
    assert json.loads(chat_response.headers["HX-Trigger"]) == {"toast": "Done — change saved."}
    assert bills_db_module.get_bill(bill_id) == before

    body = chat_response.get_data(as_text=True)
    assert 'hx-post="/ui/chat/apply"' in body

    messages = bills_db_module.list_chat_messages()
    latest_assistant = [m for m in messages if m["role"] == "assistant"][-1]
    apply_response = live_client.post(
        "/ui/chat/apply",
        data={
            "op": "update", "entity": "bill", "id": str(bill_id),
            "fields": json.dumps({"end_date": "2026-09-16"}), "message_id": str(latest_assistant["id"]),
        },
    )
    assert apply_response.status_code == 200
    assert bills_db_module.get_bill(bill_id)["end_date"] == "2026-09-16"
    assert bills_db_module.list_chat_messages()[-2]["id"] == latest_assistant["id"] or any(
        m["id"] == latest_assistant["id"] and m["applied"] for m in bills_db_module.list_chat_messages()
    )


def test_calendar_card_excludes_bills_flagged_exclude_from_plan(live_client):
    rent = next(b for b in bills_db_module.list_bills() if b["name"] == "Rent")
    assert rent["exclude_from_plan"] == 1

    response = live_client.get("/ui/calendar")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Rent" not in body


def test_bill_add_form_missing_required_field_returns_422_error_fragment(live_client):
    response = live_client.post(
        "/ui/bills",
        data={"merchant": "No name here", "amount": "5.00", "cadence": "monthly", "next_billing_date": "2026-10-01", "type": "bill"},
    )
    assert response.status_code == 422
    body = response.get_data(as_text=True)
    assert "error-fragment" in body
    assert "missing required fields" in body


def test_api_chat_with_form_body_returns_400_json_not_500(live_client):
    response = live_client.post("/api/chat", data={"message": "hello"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "expected a JSON body"}


def test_api_disputes_put_with_form_body_returns_400_json_not_500(live_client):
    response = live_client.put("/api/disputes/1", data={"status": "sent"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "expected a JSON body"}


def test_api_chat_apply_with_form_body_returns_400_json_not_500(live_client):
    response = live_client.post("/api/chat/apply", data={"op": "update"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "expected a JSON body"}


def test_api_calendar_month_invalid_returns_400_never_500(live_client):
    response = live_client.get("/api/calendar/2026-13")
    assert response.status_code == 400
    assert response.get_json() == {"error": "month must be YYYY-MM"}


def test_api_calendar_month_unparsable_returns_400(live_client):
    response = live_client.get("/api/calendar/not-a-month")
    assert response.status_code == 400
    assert response.get_json() == {"error": "month must be YYYY-MM"}


def test_api_calendar_range_bad_from_returns_400(live_client):
    response = live_client.get("/api/calendar", query_string={"from": "2026-13"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "month must be YYYY-MM"}


def test_ui_calendar_month_invalid_returns_422_error_fragment(live_client):
    response = live_client.get("/ui/calendar", query_string={"month": "2026-13"})
    assert response.status_code == 422
    body = response.get_data(as_text=True)
    assert "error-fragment" in body
    assert "month must be YYYY-MM" in body


def test_api_chat_apply_disallowed_field_returns_400(live_client):
    response = live_client.post(
        "/api/chat/apply",
        json={"op": "update", "entity": "bill", "id": 1, "fields": {"status": "paid"}},
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "field 'status' cannot be set via chat"}


def test_ui_chat_apply_disallowed_field_returns_422_error_fragment(live_client):
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "update", "entity": "bill", "id": "1", "fields": json.dumps({"status": "paid"})},
    )
    assert response.status_code == 422
    body = _text(response)
    assert "error-fragment" in body
    assert "field 'status' cannot be set via chat" in body


def test_api_chat_apply_value_db_rejects_returns_400_not_500(live_client):
    bill_id, _response, _name = _add_bill(live_client)
    response = live_client.post(
        "/api/chat/apply",
        json={"op": "update", "entity": "bill", "id": bill_id, "fields": {"cadence": "daily"}},
    )
    assert response.status_code == 400
    assert "cadence" in response.get_json()["error"]


def test_ui_chat_apply_value_db_rejects_returns_422_not_500(live_client):
    bill_id, _response, _name = _add_bill(live_client)
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "update", "entity": "bill", "id": str(bill_id), "fields": json.dumps({"cadence": "daily"})},
    )
    assert response.status_code == 422
    body = response.get_data(as_text=True)
    assert "error-fragment" in body
    assert "cadence" in body
