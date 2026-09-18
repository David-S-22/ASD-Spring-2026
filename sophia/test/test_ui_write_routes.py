"""Tests for the /ui/* write routes (addendum 1): HTML back, HX-Trigger toast,
DB state actually changed, oob timeline/calendar where the write affects
dates, 422 + error fragment on validation failure, and that /api/* returns a
clean 400 (never 500) on a non-JSON body.

Uses the live_client fixture from conftest.py (real sophia/database in a
background thread, temp seeded SQLite) so "DB state changed" is checked
against the real service, not a mock.
"""
import json
import re

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
    # Single-page layout: the write response is the refreshed table alone —
    # Coming up and the Calendar are no longer on the page to refresh.
    body = response.get_data(as_text=True)
    assert 'id="bills-table"' in body
    assert 'id="timeline"' not in body and 'id="calendar-card"' not in body

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
    assert 'id="bills-table"' in response.get_data(as_text=True)
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
    assert 'id="bills-table"' in response.get_data(as_text=True)
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
    # Asking a question changes nothing, so it must not claim to. The apply
    # route is the one that writes, and it still sends the toast.
    assert "HX-Trigger" not in chat_response.headers
    assert bills_db_module.get_bill(bill_id) == before

    body = chat_response.get_data(as_text=True)
    # The emitted markup carries the /bills-backend/ prefix so one set of URLs
    # works both standalone and inside the shared shell; nginx strips it before
    # the request reaches Flask, which is why the request paths below are
    # still the unprefixed routes. The reply's card posts to the suggestion
    # endpoints — the proposal is a pending suggestion, approvable from the
    # chat card or the Suggestions panel alike.
    suggestion = bills_db_module.list_suggestions(status="pending")[-1]
    assert f'hx-post="/bills-backend/ui/suggestions/{suggestion["id"]}/approve"' in body
    assert f'hx-post="/bills-backend/ui/suggestions/{suggestion["id"]}/reject"' in body
    # ...and refreshes the panel out of band so the badge appears immediately.
    assert 'id="suggestions-panel" hx-swap-oob="true"' in body

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


def test_ui_chat_apply_can_create_a_bill_from_the_shape_the_model_emits(live_client):
    """The whole point: an add-a-bill request from chat now lands as a row.

    Fields are exactly what the model produces against the current prompt --
    amount in dollars, real column names elsewhere.
    """
    fields = {
        "name": "Audible",
        "merchant": "Audible",
        "amount": 16.45,
        "cadence": "monthly",
        "next_billing_date": "2026-09-10",
        "type": "subscription",
        "payment_method": "card",
    }
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "create", "entity": "bill", "fields": json.dumps(fields)},
    )
    assert response.status_code == 200
    created = [b for b in bills_db_module.list_bills() if b["name"] == "Audible"]
    assert len(created) == 1
    assert created[0]["amount_cents"] == 1645
    assert created[0]["source"] == "chat"


def test_ui_chat_apply_creates_a_bill_from_the_older_drifted_shape(live_client):
    """A smaller model says "amount"/"next" and names no merchant; still lands."""
    fields = {"name": "Kindle", "amount": 9.99, "next": "2026-09-20",
              "cadence": "monthly", "type": "subscription"}
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "create", "entity": "bill", "fields": json.dumps(fields)},
    )
    assert response.status_code == 200
    created = [b for b in bills_db_module.list_bills() if b["name"] == "Kindle"]
    assert created[0]["amount_cents"] == 999
    assert created[0]["merchant"] == "Kindle"
    assert created[0]["next_billing_date"] == "2026-09-20"


def test_ui_chat_apply_still_refuses_an_invented_field_on_create(live_client):
    """Normalisation widens the vocabulary; it must not disarm the allowlist."""
    fields = {"name": "X", "amount": 5, "cadence": "monthly", "type": "bill",
              "next_billing_date": "2026-09-01", "colour": "blue"}
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "create", "entity": "bill", "fields": json.dumps(fields)},
    )
    assert response.status_code == 422
    assert "field 'colour' cannot be set via chat" in _text(response)
    assert not [b for b in bills_db_module.list_bills() if b["name"] == "X"]


def test_ui_chat_apply_refuses_an_amount_that_is_not_a_number(live_client):
    fields = {"name": "Y", "amount": "lots", "cadence": "monthly", "type": "bill",
              "next_billing_date": "2026-09-01"}
    response = live_client.post(
        "/ui/chat/apply",
        data={"op": "create", "entity": "bill", "fields": json.dumps(fields)},
    )
    assert response.status_code == 422
    assert "must be an amount" in _text(response)


def test_ui_dispute_delete_removes_it_and_refreshes_the_list(live_client, monkeypatch):
    """The Disputes tab's remove button: dispute and its drafts go, the panel
    falls back to the next dispute (or the empty state), and the list arrives
    refreshed out of band so the removed row doesn't linger."""
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        lambda model, messages, timeout=None: (_ for _ in ()).throw(RuntimeError("no model in tests")),
    )
    bill_id, _response, _name = _add_bill(live_client)
    created = live_client.post("/ui/disputes", data={"bill_id": str(bill_id), "reason": "Duplicate charge"})
    assert created.status_code == 201
    dispute_id = max(d["id"] for d in bills_db_module.list_disputes())
    assert bills_db_module.list_dispute_drafts(dispute_id)

    response = live_client.post(f"/ui/disputes/{dispute_id}/delete")
    assert response.status_code == 200
    assert response.headers.get("HX-Trigger")
    body = response.get_data(as_text=True)
    assert 'id="dispute-list" hx-swap-oob="true"' in body
    assert "Duplicate charge" not in body
    assert bills_db_module.get_dispute(dispute_id) is None
    assert bills_db_module.list_dispute_drafts(dispute_id) == []


def test_disputes_tab_starts_collapsed_and_fetches_no_panel(live_client):
    """The Disputes card opens as tiles only. Two contracts app.js leans on:
    the panel is hidden (its scroll-on-open keys off the hidden -> visible
    transition), and nothing fetches a panel on load -- a stray hx-trigger="load"
    here would open someone's letter unasked and defeat the whole layout."""
    text = _text(live_client.get("/ui/disputes-tab"))
    assert "collapsed-disputes" in text
    panel = re.search(r'<div id="dispute-panel"[^>]*>', text)
    assert panel, "the tab must ship a panel placeholder for writes to target"
    assert "hidden" in panel.group(0)
    assert "hx-trigger" not in panel.group(0)
    assert 'hx-target="#dispute-panel"' in text, "tiles must target the panel"


def test_open_dispute_panel_is_not_hidden(live_client):
    """The counterweight to every "panel is hidden" assertion in this file.
    Without it, making the panel permanently hidden -- which would kill the
    feature outright -- passes the entire suite."""
    dispute_id = bills_db_module.list_disputes()[0]["id"]
    text = _text(live_client.get(f"/ui/disputes?dispute_id={dispute_id}"))
    panel = re.search(r'<div class="dispute-panel" id="dispute-panel"[^>]*>', text)
    assert panel, "panel root missing"
    assert "hidden" not in panel.group(0), "a panel showing a dispute must be visible"
    assert "close-dispute-panel" in text


def test_creating_a_dispute_refreshes_the_tile_grid(live_client, monkeypatch):
    """Every other dispute write appends the list out of band; create did not.
    The grid is only ever populated by #disputes-tab's one-shot hx-trigger="load",
    so a freshly drafted dispute had no tile -- and once Close wiped the panel
    there was no control left anywhere that could reopen it. A page reload was
    the only recovery, and drafting again burns a second AI call and inserts a
    duplicate, because create_dispute does not dedupe."""
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        lambda model, messages, timeout=None: (_ for _ in ()).throw(RuntimeError("no model in tests")),
    )
    bill_id, _r, _n = _add_bill(live_client)
    body = live_client.post(
        "/ui/disputes", data={"bill_id": str(bill_id), "reason": "Charged after cancelling"}
    ).get_data(as_text=True)

    assert 'id="dispute-list" hx-swap-oob="true"' in body, "the tile grid must ride along"
    new_id = max(d["id"] for d in bills_db_module.list_disputes())
    assert f"dispute_id={new_id}" in body, "the new dispute needs a tile that can reopen it"


def test_ui_dispute_delete_collapses_the_panel_instead_of_opening_another(live_client, monkeypatch):
    """With the collapsed-by-default Disputes card, removing a dispute must
    leave the panel shut. The old always-open layout fell back to disputes[0],
    which now reads as "I deleted one and an unrelated dispute sprang open" --
    and the swapped-in panel carries no hidden attribute, so nothing collapses
    it again short of finding the Close button on a letter you never asked for.
    """
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        lambda model, messages, timeout=None: (_ for _ in ()).throw(RuntimeError("no model in tests")),
    )
    doomed_bill_id, _r, _n = _add_bill(live_client)
    live_client.post("/ui/disputes", data={"bill_id": str(doomed_bill_id), "reason": "Delete this one"})
    doomed_id = max(d["id"] for d in bills_db_module.list_disputes())
    # The seed ships disputes of its own, so survivors are guaranteed here --
    # which is exactly the case that used to spring one of them open.
    assert len(bills_db_module.list_disputes()) > 1

    body = live_client.post(f"/ui/disputes/{doomed_id}/delete").get_data(as_text=True)

    panel = body.split('id="dispute-list"')[0]
    assert "close-dispute" not in panel, "deleting one dispute must not open another"
    assert 'class="empty"' in panel, "the panel should come back as the empty state"
    assert re.search(r'id="dispute-panel"[^>]*\shidden', panel), "the collapsed panel must come back hidden"


def test_empty_dispute_panel_is_hidden_so_it_leaves_no_stray_rule(live_client):
    """The collapsed layout gives .dispute-panel a top border and padding, so an
    empty-but-visible panel paints a horizontal rule under the tile grid with no
    Close button to dismiss it (the button is only rendered when a dispute is)."""
    text = live_client.get("/ui/disputes?dispute_id=99999").get_data(as_text=True)
    assert 'id="dispute-panel"' in text
    assert "hidden" in text


def test_ui_dispute_delete_missing_is_a_clean_422(live_client):
    response = live_client.post("/ui/disputes/99999/delete")
    assert response.status_code == 422
    assert "dispute not found" in response.get_data(as_text=True)


def test_ui_dispute_status_change_refreshes_the_list_chips(live_client, monkeypatch):
    """Marking a dispute sent used to leave the list row's 'draft' chip
    standing until the tab was reopened."""
    monkeypatch.setattr(
        "sophia.backend.ai.guard.chat",
        lambda model, messages, timeout=None: (_ for _ in ()).throw(RuntimeError("no model in tests")),
    )
    bill_id, _response, _name = _add_bill(live_client)
    live_client.post("/ui/disputes", data={"bill_id": str(bill_id), "reason": "Chip check"})
    dispute_id = max(d["id"] for d in bills_db_module.list_disputes())

    response = live_client.post(f"/ui/disputes/{dispute_id}/status", data={"status": "sent"})
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="dispute-list" hx-swap-oob="true"' in body
    assert "chip-dispute-sent" in body
