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
    # The prompt names where the bill came from. It only appears for a
    # source=f4_handoff bill that has not been confirmed -- GymCo in the seed.
    assert "Added from Spending Alerts — keep it?" in text
    assert "Direct debit" in text
    assert "Fortnight" in text


def test_calendar_fragment_verbatim_copy(live_client):
    response = live_client.get("/ui/calendar")
    assert response.status_code == 200
    text = _text(response)
    assert "Plan for September" in text
    assert "Set aside up to $" in text
    assert "Usual bills you pay every month" in text
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


def test_chat_fragment_chips_placeholder_and_clean_open(live_client):
    """The panel opens on a welcome state, not on somebody else's transcript.

    The four suggestion chips share their wording with seeded user messages, so
    the check that history is not replayed uses assistant replies instead --
    those appear only if stored messages are being rendered.
    """
    response = live_client.get("/ui/chat")
    assert response.status_code == 200
    text = _text(response)
    assert "What do my bills add up to?" in text
    assert "Which subscriptions am I barely using?" in text
    assert "I cancelled Spotify from September — remove the future payments" in text
    assert "Draft a note to dispute my GymCo charge" in text
    assert 'placeholder="Ask"' in text
    assert "Ask about your bills, or pick one of the suggestions above." in text
    assert "Earlier — Mon 17 Aug" not in text
    assert "September needs up to $697" not in text
    assert "Cloud storage has billed four times" not in text


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


HANDOFF_QUERY = {
    "source": "f4",
    "alert_id": "7",
    "merchant": "Spotify",
    "amount": "12.99",
    "cadence": "monthly",
    "first_seen": "2026-05-01",
    "last_seen": "2026-08-01",
    "occurrences": "4",
}


def _handoff_query(**overrides):
    query = dict(HANDOFF_QUERY)
    query.update(overrides)
    return {key: value for key, value in query.items() if value is not None}


def test_handoff_subscription_prefills_add_bill_form(live_client):
    response = live_client.get("/ui/handoff/subscription", query_string=_handoff_query())
    assert response.status_code == 200
    text = _text(response)
    assert "Add a bill" in text
    assert 'value="Spotify"' in text
    assert 'value="12.99"' in text
    assert '<option value="subscription" selected>' in text
    assert 'value="2026-09-01"' in text
    assert 'name="source" value="f4_handoff"' in text
    assert "Suggested by Spending Alerts — based on 4 charges from 2026-05-01 to 2026-08-01" in text
    assert "low confidence" not in text


def test_handoff_subscription_missing_merchant_is_rejected(live_client):
    response = live_client.get("/ui/handoff/subscription", query_string=_handoff_query(merchant=None))
    assert response.status_code == 422
    assert 'class="error"' in _text(response)


def test_handoff_subscription_unknown_cadence_is_rejected(live_client):
    response = live_client.get("/ui/handoff/subscription", query_string=_handoff_query(cadence="yearly"))
    assert response.status_code == 422
    assert 'class="error"' in _text(response)


def test_handoff_subscription_reversed_dates_are_rejected(live_client):
    response = live_client.get(
        "/ui/handoff/subscription", query_string=_handoff_query(first_seen="2026-08-02", last_seen="2026-08-01")
    )
    assert response.status_code == 422
    assert 'class="error"' in _text(response)


def test_handoff_subscription_low_confidence_wording_and_return_link(live_client):
    response = live_client.get(
        "/ui/handoff/subscription",
        query_string=_handoff_query(confidence="low", return_url="http://localhost:3004/alerts"),
    )
    text = _text(response)
    assert "(low confidence — please check the amount and cadence)" in text
    assert 'href="http://localhost:3004/alerts"' in text
    assert "Back to alerts" in text


@pytest.mark.parametrize(
    ("last_seen", "cadence", "expected"),
    [("2026-08-01", "monthly", "2026-09-01"), ("2026-08-19", "weekly", "2026-08-26")],
)
def test_handoff_subscription_projects_next_billing_date(live_client, last_seen, cadence, expected):
    response = live_client.get(
        "/ui/handoff/subscription", query_string=_handoff_query(last_seen=last_seen, cadence=cadence)
    )
    assert response.status_code == 200
    assert f'value="{expected}"' in _text(response)


def test_paid_bill_with_an_imminent_next_charge_is_not_green(live_client):
    """A bill settled for this cycle but charging again within 7 days reads
    "Due <date>". Rendering that on the green paid chip made two unpaid-looking
    rows scan as handled; the tone is its own so the colour matches the words.
    The JSON API's `status` is unchanged -- this is presentation only.
    """
    text = _text(live_client.get("/ui/bills"))
    assert 'class="chip chip-upcoming">Due ' in text
    assert 'class="chip chip-paid">Due ' not in text


def test_total_answer_names_both_figures_and_quotes_the_header_number(live_client):
    """The chat answer and the table header quote different totals on purpose --
    a calendar month versus an ongoing monthly rate -- so the answer has to say
    which is which. This pins the harder half: the rate it quotes is the number
    the header actually renders, so the two can never drift into contradicting
    each other.
    """
    from sophia.backend import config
    from sophia.backend.services import chat as chat_service

    header = _text(live_client.get("/ui/bills"))
    answer = chat_service._answer_total()

    assert config.DEMO_TODAY.strftime("%B") in answer
    assert "ongoing monthly total" in answer

    rate = answer.split("ongoing monthly total across all bills is ")[1].rstrip(".")
    assert f"subscriptions · {rate}" in header
