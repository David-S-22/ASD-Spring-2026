"""The suggestions window: AI-proposed changes wait for approval, and every
outcome — applied, rejected, failed — is on the record for both the user and
the model's next turn."""
import json

import pytest

from sophia.backend.clients import bills_db as bills_db_module
from sophia.backend.services import chat as chat_service
from sophia.backend.services.errors import ServiceError
from conftest import response_text as _text


def _propose(live_client, monkeypatch, response_dict, message="do it"):
    def fake_chat(model, messages, timeout=None):
        return {"message": {"content": json.dumps(response_dict)}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", fake_chat)
    response = live_client.post("/ui/chat", data={"message": message})
    assert response.status_code == 200
    return response


CREATE_DISNEY = {
    "op": "create", "entity": "bill", "id": None,
    "fields": {"name": "Disney Plus", "merchant": "Disney Plus", "amount": 15.0,
               "cadence": "monthly", "next_billing_date": "2026-09-05",
               "type": "subscription", "payment_method": "card"},
    "question": "none", "say": "I've suggested adding Disney Plus — approve it to save.",
}


def test_chat_proposal_creates_a_pending_suggestion_not_a_bill(live_client, monkeypatch):
    before = len(bills_db_module.list_bills())
    _propose(live_client, monkeypatch, CREATE_DISNEY)
    assert len(bills_db_module.list_bills()) == before
    pending = bills_db_module.list_suggestions(status="pending")
    assert pending
    latest = pending[-1]
    assert latest["op"] == "create" and latest["entity"] == "bill"
    payload = json.loads(latest["payload_json"])
    assert payload["amount_cents"] == 1500  # dollars canonicalised at proposal time


def test_approve_applies_and_refreshes_the_bills_table(live_client, monkeypatch):
    _propose(live_client, monkeypatch, CREATE_DISNEY)
    suggestion_id = bills_db_module.list_suggestions(status="pending")[-1]["id"]

    response = live_client.post(f"/ui/suggestions/{suggestion_id}/approve")
    assert response.status_code == 200
    body = _text(response)
    # The response carries the refreshed panel plus the bills views out of
    # band — the table shows the new row without any manual refresh.
    assert 'id="bills-table" hx-swap-oob="true"' in body
    assert 'id="timeline" hx-swap-oob="true"' in body
    assert 'id="calendar-card" hx-swap-oob="true"' in body
    assert "Disney Plus" in body
    created = [b for b in bills_db_module.list_bills() if b["name"] == "Disney Plus"]
    assert len(created) == 1 and created[0]["source"] == "chat"
    assert bills_db_module.get_suggestion(suggestion_id)["status"] == "applied"
    # ...and the transcript the model reads says exactly what happened.
    outcome = bills_db_module.list_chat_messages()[-1]
    assert "approved and applied" in outcome["content"] and "Disney Plus" in outcome["content"]


def test_reject_changes_nothing_and_tells_the_model(live_client, monkeypatch):
    target = bills_db_module.list_bills()[0]
    _propose(live_client, monkeypatch, {
        "op": "delete", "entity": "bill", "id": target["id"], "fields": None,
        "question": "none", "say": "I've suggested deleting it — approve to remove."})
    suggestion_id = bills_db_module.list_suggestions(status="pending")[-1]["id"]

    response = live_client.post(f"/ui/suggestions/{suggestion_id}/reject")
    assert response.status_code == 200
    assert bills_db_module.get_bill(target["id"]) is not None
    assert bills_db_module.get_suggestion(suggestion_id)["status"] == "rejected"
    outcome = bills_db_module.list_chat_messages()[-1]
    assert "rejected by the user" in outcome["content"]
    assert "NOT applied" in outcome["content"]


def test_approving_a_delete_for_a_missing_bill_fails_honestly(live_client, monkeypatch):
    _propose(live_client, monkeypatch, {
        "op": "delete", "entity": "bill", "id": 99999, "fields": None,
        "question": "none", "say": "I've suggested deleting it."})
    suggestion_id = bills_db_module.list_suggestions(status="pending")[-1]["id"]

    response = live_client.post(f"/ui/suggestions/{suggestion_id}/approve")
    assert response.status_code == 200
    body = _text(response)
    assert "bill not found" in json.loads(response.headers["HX-Trigger"])["toast"]
    row = bills_db_module.get_suggestion(suggestion_id)
    assert row["status"] == "failed" and "bill not found" in row["error"]
    outcome = bills_db_module.list_chat_messages()[-1]
    assert "FAILED" in outcome["content"] and "nothing was changed" in outcome["content"]
    # The failed card stays visible in the panel with its error.
    assert "Couldn't apply" in _text(live_client.get("/ui/suggestions"))


def test_a_suggestion_applies_at_most_once(live_client, monkeypatch):
    """The double-click/double-approve guard: the second approve must not
    create a second bill."""
    _propose(live_client, monkeypatch, CREATE_DISNEY, message="add disney again")
    suggestion_id = bills_db_module.list_suggestions(status="pending")[-1]["id"]

    first = live_client.post(f"/ui/suggestions/{suggestion_id}/approve")
    assert first.status_code == 200
    count_after_first = len([b for b in bills_db_module.list_bills() if b["name"] == "Disney Plus"])

    second = live_client.post(f"/ui/suggestions/{suggestion_id}/approve")
    assert second.status_code == 200  # renders current state, applies nothing
    assert "already applied" in json.loads(second.headers["HX-Trigger"])["toast"]
    assert len([b for b in bills_db_module.list_bills() if b["name"] == "Disney Plus"]) == count_after_first


def test_update_suggestion_panel_shows_a_before_after_diff(live_client, monkeypatch):
    spotify = next(b for b in bills_db_module.list_bills() if b["name"] == "Spotify")
    _propose(live_client, monkeypatch, {
        "op": "update", "entity": "bill", "id": spotify["id"],
        "fields": {"end_date": "2026-09-16"}, "question": "none",
        "say": "I've suggested ending Spotify — approve to save."})
    panel = _text(live_client.get("/ui/suggestions"))
    assert "Update Spotify" in panel
    assert "2026-09-16" in panel
    assert "suggestion-old" in panel or "—" in panel  # the before value renders


def test_chat_reply_card_names_the_change(live_client, monkeypatch):
    """No more blind Confirm buttons: the inline card carries the same titled,
    field-level detail the panel shows."""
    response = _propose(live_client, monkeypatch, CREATE_DISNEY, message="add disney once more")
    body = _text(response)
    assert "Add bill: Disney Plus" in body
    assert "$15.00" in body
    assert ">Approve<" in body and ">Reject<" in body


def test_api_suggestion_endpoints_roundtrip(live_client, monkeypatch):
    _propose(live_client, monkeypatch, {
        "op": "update", "entity": "bill", "id": 1,
        "fields": {"exclude_from_plan": 1}, "question": "none",
        "say": "I've suggested excluding Rent from the plan."})
    listed = live_client.get("/api/chat/suggestions", query_string={"status": "pending"}).get_json()
    suggestion_id = listed[-1]["id"]
    applied = live_client.post(f"/api/chat/suggestions/{suggestion_id}/approve")
    assert applied.status_code == 200
    assert live_client.post(f"/api/chat/suggestions/{suggestion_id}/reject").status_code == 409


def test_invalid_enum_value_becomes_a_question_not_a_proposal(live_client, monkeypatch):
    """Live-model case from the field: 'change rent from a bill to none' →
    type="none". That used to become an Approve button that could only fail;
    it must be a rephrase request, with nothing proposed."""
    before_pending = len(bills_db_module.list_suggestions(status="pending"))
    response = _propose(live_client, monkeypatch, {
        "op": "update", "entity": "bill", "id": 1,
        "fields": {"type": "none"}, "question": "none",
        "say": "I've suggested changing the rent from a bill to none."})
    body = _text(response)
    assert "couldn't turn that into a change" in body
    assert "type must be one of" in body
    assert len(bills_db_module.list_suggestions(status="pending")) == before_pending


def test_invalid_cadence_becomes_a_question_not_a_proposal(live_client, monkeypatch):
    before_pending = len(bills_db_module.list_suggestions(status="pending"))
    response = _propose(live_client, monkeypatch, {
        "op": "create", "entity": "bill", "id": None,
        "fields": {"name": "Daily Juice", "amount": 5, "cadence": "daily",
                   "next_billing_date": "2026-09-01", "type": "subscription"},
        "question": "none", "say": "Adding it."})
    assert "cadence must be one of" in _text(response)
    assert len(bills_db_module.list_suggestions(status="pending")) == before_pending


def test_proposal_renders_in_the_panel_only_not_the_chat(live_client, monkeypatch):
    """One surface for one decision: the reply carries a pointer, and the only
    decidable card in the response is the panel's (arriving out of band)."""
    response = _propose(live_client, monkeypatch, CREATE_DISNEY, message="add disney plus")
    body = _text(response)
    assert "Review it in" in body  # the pointer line
    # every decidable card in the response belongs to the panel: one per
    # visible (pending or failed) suggestion, none inline in the chat reply
    visible = len([s for s in bills_db_module.list_suggestions() if s["status"] in ("pending", "failed")])
    panel_part = body[body.index('id="suggestions-panel"'):]
    assert body.count('class="suggestion-card') == visible
    assert panel_part.count('class="suggestion-card') == visible
    assert 'id="suggestions-panel" hx-swap-oob="true"' in body
