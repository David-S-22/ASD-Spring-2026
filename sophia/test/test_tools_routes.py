"""Tests for the Tools card fragments: bills_db and the MCP client are faked, no network."""
import pytest

from conftest import response_text as _text
from sophia.backend import app as backend_app_module
from sophia.backend import config
from sophia.backend.clients import bills_db, mcp_server
from sophia.backend.routes import tools
from sophia.backend.services.errors import ModeError

BILLS = [
    {"id": 7, "name": "Home internet", "merchant": "FibreLink"},
    {"id": 3, "name": "Spotify", "merchant": "Spotify AU"},
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    monkeypatch.setattr(bills_db, "list_bills", lambda: [dict(b) for b in BILLS])
    monkeypatch.setattr(bills_db, "get_bill", lambda bill_id: next((dict(b) for b in BILLS if b["id"] == bill_id), None))
    monkeypatch.setattr(mcp_server, "list_tools", lambda: (_ for _ in ()).throw(AssertionError("probed on load")))
    app = backend_app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_tools_panel_lists_bills_and_posts_to_the_prefixed_route_without_probing(client):
    response = client.get("/ui/tools")
    assert response.status_code == 200
    body = _text(response)
    assert 'id="tools-panel"' in body
    assert 'hx-post="/bills-backend/ui/tools/search_transactions"' in body
    assert '<option value="7">Home internet (FibreLink)</option>' in body
    assert "MCP enabled" in body
    assert "HX-Trigger" not in response.headers


def test_match_transactions_calls_search_transactions_with_the_bill_merchant(client, monkeypatch):
    seen = {}

    def call_tool(name, arguments):
        seen.update(name=name, arguments=arguments)
        return [{"date": "Wed, 10 Jun 2026 00:00:00 GMT", "merchant": "FibreLink", "description": "Internet plan", "amount": 79.0},
                {"date": "2026-06-24", "merchant": "FibreLink", "description": "Internet plan", "amount": 79.0}], 84.0

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    response = client.post("/ui/tools/search_transactions", data={"bill_id": "7"})
    assert response.status_code == 200
    assert seen == {"name": "search_transactions", "arguments": {"merchant": "FibreLink"}}
    body = _text(response)
    assert "2 rows in 84.0 ms" in body and "Internet plan" in body and "$79.00" in body
    assert "2026-06-10" in body and "2026-06-24" in body and "GMT" not in body
    assert "HX-Trigger" not in response.headers


def test_tools_panel_offers_the_bills_db_tools_on_the_same_bill_picker(client):
    body = _text(client.get("/ui/tools"))
    assert 'hx-post="/bills-backend/ui/tools/get_bill_payments"' in body and 'hx-post="/bills-backend/ui/tools/compare_bill_with_bank_charges"' in body
    assert body.count('hx-include="closest form"') == 2 and body.count("<select") == 1


def test_payment_history_calls_get_bill_payments_and_renders_the_payments_in_dollars(client, monkeypatch):
    seen = {}

    def call_tool(name, arguments):
        seen.update(name=name, arguments=arguments)
        return {"bill": {"id": 3, "merchant": "Spotify AU", "amount_cents": 1399},
                "payments": [{"id": 11, "bill_id": 3, "date": "2026-07-27", "amount_cents": 1399}, {"id": 13, "bill_id": 3, "date": "2026-09-27", "amount_cents": 1399}]}, 21.0

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    body = _text(client.post("/ui/tools/get_bill_payments", data={"bill_id": "3"}))
    assert seen == {"name": "get_bill_payments", "arguments": {"bill_id": 3}}
    assert "2 rows in 21.0 ms" in body and "2026-07-27" in body and "$13.99" in body and "vs bill" not in body


def test_compare_sends_a_90_day_window_ending_today_and_notes_the_difference(client, monkeypatch):
    from datetime import timedelta

    seen = {}

    def call_tool(name, arguments):
        seen.update(name=name, arguments=arguments)
        return {"bill": {"id": 3, "merchant": "Spotify AU", "amount_cents": 1399}, "payments": [],
                "charges": [{"id": 26, "date": "2026-08-20", "amount_cents": 1799, "description": "Monthly subscription", "differs_from_bill_cents": 400},
                            {"id": 22, "date": "2026-07-15", "amount_cents": 1399, "description": "Spotify Premium subscription", "differs_from_bill_cents": 0}]}, 33.0

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    body = _text(client.post("/ui/tools/compare_bill_with_bank_charges", data={"bill_id": "3"}))
    start = (config.DEMO_TODAY - timedelta(days=90)).isoformat()
    assert seen == {"name": "compare_bill_with_bank_charges", "arguments": {"bill_id": 3, "start_date": start, "end_date": config.DEMO_TODAY.isoformat()}}
    assert "2 rows in 33.0 ms" in body and "$17.99" in body and "+$4.00 vs bill" in body and "Monthly subscription" in body
    assert "2026-07-15" in body and "-$" not in body


def test_bills_db_tools_with_an_empty_result_and_an_unknown_bill(client, monkeypatch):
    monkeypatch.setattr(mcp_server, "call_tool", lambda name, arguments: ({"bill": {"id": 7}, "payments": []}, 9.0))
    assert "No matching rows." in _text(client.post("/ui/tools/get_bill_payments", data={"bill_id": "7"}))
    response = client.post("/ui/tools/compare_bill_with_bank_charges", data={"bill_id": "99"})
    assert response.status_code == 422 and "bill not found" in _text(response)


def test_display_row_normalises_both_date_shapes():
    assert tools._display_row({"date": "2026-06-10T00:00:00", "description": "x", "amount": 79}) == {"date": "2026-06-10", "description": "x", "amount": "$79.00", "note": ""}
    assert tools._display_row({"date": "Wed, 10 Jun 2026 00:00:00 GMT", "amount": "13.99"}) == {"date": "2026-06-10", "description": "", "amount": "$13.99", "note": ""}
    assert tools._display_row({"date": "later", "amount": None}) == {"date": "later", "description": "", "amount": "", "note": ""}
    assert tools._display_row({"date": "2026-08-20", "amount_cents": 1799, "differs_from_bill_cents": 400})["note"] == "+$4.00 vs bill"
    assert tools._display_row({"date": "2026-08-20", "amount_cents": 1299, "differs_from_bill_cents": -100})["note"] == "-$1.00 vs bill"


def test_unknown_bill_and_unknown_tool_render_error_fragments(client):
    response = client.post("/ui/tools/search_transactions", data={"bill_id": "99"})
    assert response.status_code == 422 and "bill not found" in _text(response)
    response = client.post("/ui/tools/no_such_tool", data={})
    assert response.status_code == 422 and "not allowed" in _text(response)
    response = client.post("/ui/tools/retrieve_context", data={"question": "q"})
    assert response.status_code == 422 and "not allowed" in _text(response)


def test_mode_errors_keep_their_status_and_name_no_server(client, monkeypatch):
    def call_tool(name, arguments):
        raise ModeError("mcp_connection")

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    response = client.post("/ui/tools/search_transactions", data={"bill_id": "7"})
    assert response.status_code == 503
    body = _text(response)
    assert "The MCP server is unavailable." in body
    assert "8000" not in body and "host.docker.internal" not in body


def test_disabled_renders_the_disabled_copy_and_bills_db_outage_is_a_fragment(client, monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    response = client.post("/ui/tools/search_transactions", data={"bill_id": "7"})
    assert response.status_code == 503 and "MCP mode is disabled." in _text(response)
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(bills_db, "list_bills", lambda: (_ for _ in ()).throw(RuntimeError("bills-db down")))
    response = client.get("/ui/tools")
    assert response.status_code == 500 and "Something went wrong" in _text(response) and "bills-db down" not in _text(response)
