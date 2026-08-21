"""Integration tests for the /ui/* HTML fragments.

Uses the live_client fixture from conftest.py: the real sophia/database
Flask app in a background thread against a temp seeded SQLite file, with
the backend pointed at it, so the rendered HTML is checked against real
seed data end to end.
"""
from datetime import date

import pytest

from sophia.backend.clients import bills_db as bills_db_module
from conftest import response_text as _text


def test_bills_fragment_verbatim_header_and_columns(live_client):
    response = live_client.get("/ui/bills")
    assert response.status_code == 200
    text = _text(response)
    assert "Bills & subscriptions ·" in text
    for column in ("Name", "Amount", "Every", "Next billing", "Paid by", "Status"):
        assert f"<th>{column}</th>" in text
    assert "Add a bill" in text
    assert "Confirm this?" in text
    assert "Direct debit" in text
    assert "Fortnight" in text


def test_calendar_fragment_verbatim_copy(live_client):
    response = live_client.get("/ui/calendar")
    assert response.status_code == 200
    text = _text(response)
    assert "Plan for September" in text
    assert "Set aside up to $" in text
    assert "Usual bills — weekly & fortnightly you pay every month" in text
    assert "See other months" in text


def test_timeline_fragment_header_and_range_buttons(live_client):
    response = live_client.get("/ui/timeline")
    assert response.status_code == 200
    text = _text(response)
    assert "Coming up · next 30 days, then to 180" in text
    for value in ("30", "60", "90", "180"):
        assert f">{value}<" in text


def test_disputes_fragment_verbatim_copy(live_client):
    response = live_client.get("/ui/disputes")
    assert response.status_code == 200
    text = _text(response)
    assert "Escalation path" in text
    assert "Copy the note" in text
    assert "Rewrite it" in text
    assert "Mark as sent" in text
    assert "Mark as resolved" in text
    assert (
        "Heads-up for direct-debit bills: the merchant or your bank has to remove the saved payment authority, "
        "so the steps differ." in text
    )


def test_disputes_fragment_empty_state(live_client):
    response = live_client.get("/ui/disputes?bill_id=999999")
    assert response.status_code == 200
    text = _text(response)
    assert 'No open disputes. If a charge looks wrong, open the bill and choose "Dispute".' in text


def test_chat_fragment_chips_placeholder_and_history_heading(live_client):
    response = live_client.get("/ui/chat")
    assert response.status_code == 200
    text = _text(response)
    assert "What do my bills add up to?" in text
    assert "Which subscriptions am I barely using?" in text
    assert "I cancelled Spotify from September — remove the future payments" in text
    assert "Draft a note to dispute my GymCo charge" in text
    assert 'placeholder="Ask"' in text
    assert "Earlier — Mon 17 Aug" in text
    assert text.count("Earlier — Mon 17 Aug") == 1


def test_modal_fragment(live_client):
    response = live_client.get("/ui/modal")
    assert response.status_code == 200
    text = _text(response)
    assert "Confirm this change" in text
    assert "Confirm" in text
    assert "Cancel" in text


def test_toast_fragment_change_saved_and_removed(live_client):
    saved = live_client.get("/ui/toast")
    assert "Done — change saved." in _text(saved)

    removed = live_client.get("/ui/toast", query_string={"text": "Done — removed."})
    assert "Done — removed." in _text(removed)


@pytest.fixture
def timeline_client(monkeypatch):
    from sophia.backend import app as backend_app_module
    from sophia.backend import config

    bills = [
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
    payments = [
        {"id": 1, "bill_id": 1, "date": "2026-08-01", "amount_cents": 110000},
        {"id": 2, "bill_id": 3, "date": "2026-09-15", "amount_cents": 1399},
    ]
    monkeypatch.setattr(bills_db_module, "list_bills", lambda: bills)
    monkeypatch.setattr(bills_db_module, "list_payments", lambda: payments)
    monkeypatch.setattr(config, "DEMO_TODAY", date(2026, 8, 20))
    app = backend_app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_timeline_fragment_actual_vs_predicted_formatting(timeline_client):
    response = timeline_client.get("/ui/timeline?days=60")
    assert response.status_code == 200
    text = _text(response)
    assert "$1,100" in text
    assert "$13.99" in text
    assert "$13.99 " in text or "$13.99<" in text
    assert text.count("Predicted") == 2
