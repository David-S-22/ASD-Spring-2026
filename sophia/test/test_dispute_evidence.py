"""Dispute letters cite bank facts read through MCP (the compare tool and the confirmed-anomalies tool); MCP off or down leaves the letter as it was, and the panel says so."""
import json
from datetime import date

from conftest import response_text as _text
from sophia.backend import config
from sophia.backend.clients import bills_db as bills_db_module
from sophia.backend.clients import mcp_server
from sophia.backend.engine import Bill
from sophia.backend.services import disputes
from sophia.backend.services.errors import ModeError

SPOTIFY = Bill(id=3, name="Spotify", merchant="Spotify AU", amount_cents=1399, cadence="monthly", next_billing_date=date(2026, 9, 27),
               type="subscription", payment_method="card", end_date=None, confirmed_at=None, created_at=None)
COMPARE = {"bill": {"id": 3, "merchant": "Spotify AU", "amount_cents": 1399}, "payments": [],
           "charges": [{"id": 26, "date": "2026-08-20", "amount_cents": 1799, "description": "Monthly subscription", "differs_from_bill_cents": 400},
                       {"id": 22, "date": "2026-07-15", "amount_cents": 1399, "description": "Spotify Premium subscription", "differs_from_bill_cents": 0},
                       {"id": 15, "date": "2026-07-08", "amount_cents": 1399, "description": "Spotify Premium subscription", "differs_from_bill_cents": 0}]}
FLAGGED = [{"transaction": {"id": 22, "merchant": "Spotify AU", "amount": 13.99}, "anomaly": {"id": 10, "transaction_id": 22, "is_confirmed_by_user": True}},
           {"transaction": {"id": 1, "merchant": "Harbourview Realty", "amount": 1100.0}, "anomaly": {"id": 1, "transaction_id": 1, "is_confirmed_by_user": True}}]


def fake_tools(monkeypatch, error=None):
    calls = []

    def call_tool(name, arguments):
        calls.append((name, arguments))
        if error:
            raise error
        return ({"compare_bill_with_bank_charges": COMPARE, "get_transactions_with_confirmed_anomalies": FLAGGED}[name], 12.0)

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    return calls


def fake_draft(monkeypatch):
    prompts = []

    def chat(model, messages, timeout=None, temperature=None):
        prompts.append(messages)
        return {"message": {"content": json.dumps({"letter_text": "x" * 100, "steps": ["Step one", "Step two"], "escalation": ["Merchant support"], "payment_method_note": None})}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", chat)
    return prompts


def test_bank_evidence_lists_the_merchants_charges_confirmed_ones_first(monkeypatch):
    calls = fake_tools(monkeypatch)
    rows = disputes.bank_evidence(SPOTIFY, date(2026, 9, 26))
    assert rows == ["15 Jul Spotify AU $13.99, flagged by Spending Alerts and confirmed by you", "20 Aug Spotify AU $17.99", "8 Jul Spotify AU $13.99"]
    assert calls == [("compare_bill_with_bank_charges", {"bill_id": 3, "start_date": "2026-06-28", "end_date": "2026-09-26"}),
                     ("get_transactions_with_confirmed_anomalies", {})]


def test_bank_evidence_is_none_when_mcp_is_off_or_fails(monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    assert disputes.bank_evidence(SPOTIFY, date(2026, 9, 26)) is None
    fake_tools(monkeypatch, error=ModeError("mcp_connection"))
    assert disputes.bank_evidence(SPOTIFY, date(2026, 9, 26)) is None


def test_draft_prompt_carries_the_bank_facts_only_when_there_are_some(monkeypatch):
    fake_tools(monkeypatch)
    prompts = fake_draft(monkeypatch)
    monkeypatch.setattr(bills_db_module, "list_bill_payments", lambda bill_id: [])
    row = {"id": 3, "name": "Spotify", "merchant": "Spotify AU", "amount_cents": 1399, "cadence": "monthly", "next_billing_date": "2026-09-27", "type": "subscription", "payment_method": "card"}
    disputes.draft_for_bill(row, "Charged twice in July", opened_on=date(2026, 9, 26))
    user_text = prompts[0][1]["content"]
    assert "Bank statement facts" in user_text and "15 Jul Spotify AU $13.99, flagged by Spending Alerts and confirmed by you" in user_text
    assert "cite them exactly" in user_text.lower() or "cite these" in user_text.lower()
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    disputes.draft_for_bill(row, "Charged twice in July", opened_on=date(2026, 9, 26))
    assert "Bank statement" not in prompts[1][1]["content"]


def test_dispute_panel_says_when_bank_evidence_is_unavailable(live_client, monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    body = _text(live_client.get("/ui/disputes"))
    assert "Bank evidence unavailable: MCP mode is disabled." in body
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    assert "Bank evidence unavailable" not in _text(live_client.get("/ui/disputes"))


def test_creating_a_dispute_through_the_ui_uses_the_disputes_opened_date(live_client, monkeypatch):
    calls = fake_tools(monkeypatch)
    fake_draft(monkeypatch)
    response = live_client.post("/ui/disputes", data={"bill_id": "3", "reason": "Charged twice in July"})
    assert response.status_code == 201
    compare = next(c for c in calls if c[0] == "compare_bill_with_bank_charges")
    assert compare[1]["bill_id"] == 3 and compare[1]["end_date"] >= compare[1]["start_date"]
