"""Integration tests for the /ui/* HTML fragments.

Runs the real sophia/database Flask app in a background thread against a
temp seeded SQLite file, points the backend's bills_db client at it, and
hits /ui/* with the Flask test client so the rendered HTML is checked
against real seed data end to end.
"""
import importlib.util
import os
import sys
import threading
import time
from datetime import date
from html import unescape

import pytest
import requests
from werkzeug.serving import make_server

from sophia.backend.clients import bills_db as bills_db_module

_DATABASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
if _DATABASE_DIR not in sys.path:
    sys.path.insert(0, _DATABASE_DIR)


def _load_database_app():
    spec = importlib.util.spec_from_file_location("bills_database_app_for_ui_tests", os.path.join(_DATABASE_DIR, "app.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


database_app = _load_database_app()


def _text(response):
    return unescape(response.get_data(as_text=True))


@pytest.fixture(scope="module")
def live_db_base_url(tmp_path_factory):
    db_path = str(tmp_path_factory.mktemp("ui-db") / "bills.db")
    connection = database_app.get_connection(db_path)
    database_app.load_schema(connection, database_app.SCHEMA_PATH)
    database_app.seed(connection)
    connection.close()

    flask_app = database_app.create_app(db_path=db_path, bills_backend_url="http://unreachable-host.invalid:5999")
    server = make_server("127.0.0.1", 0, flask_app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            requests.get(f"{base_url}/health", timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.05)

    yield base_url
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def live_client(live_db_base_url, monkeypatch):
    from sophia.backend import app as backend_app_module
    from sophia.backend import config

    monkeypatch.setattr(config, "BILLS_DB_API_URL", live_db_base_url)
    monkeypatch.setattr(config, "DEMO_TODAY", date(2026, 8, 20))
    app = backend_app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


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
    assert "Plan for August" in text
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
    response = timeline_client.get("/ui/timeline?days=30")
    assert response.status_code == 200
    text = _text(response)
    assert "$1,100" in text
    assert "$13.99" in text
    assert text.count("Predicted") == 1
