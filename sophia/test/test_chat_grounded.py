"""Ask Tally answers plain questions from the bills corpus (RAG through MCP); proposals and code-computed questions are untouched, and a missing mode or server falls back to the model's own reply."""
import json

import pytest

from conftest import response_text as _text
from sophia.backend import config
from sophia.backend.clients import bills_db as bills_db_module
from sophia.backend.services import evidence as evidence_service
from sophia.backend.services.errors import ModeError

GROUNDED = {"answer": "Home internet (FibreLink, $79.00) is overdue.", "citations": [{"source": "bill-7-home-internet.md", "bill_id": 7, "title": "Home internet", "distance": 1.083}],
            "confidence": "medium", "insufficient": False, "retrieval": [{"id": "billing_bill-7-home-internet.md_0", "source": "bill-7-home-internet.md", "distance": 1.083}], "fallback": False, "duration_ms": 310.0}
INSUFFICIENT = {"answer": "Tally couldn't find a bill that covers that.", "citations": [], "confidence": "none", "insufficient": True,
                "retrieval": [{"id": "x", "source": "bill-1-rent.md", "distance": 1.62}], "fallback": False, "duration_ms": 290.0}
PLAIN_QUESTION = {"op": None, "entity": None, "id": None, "fields": None, "question": "none", "say": "Let me check."}


@pytest.fixture
def modes_on(monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "RAG_ENABLED", True)


def fake_model(monkeypatch, payload):
    def chat(model, messages, timeout=None, temperature=None):
        return {"message": {"content": json.dumps(payload)}}

    monkeypatch.setattr("sophia.backend.ai.guard.chat", chat)


def fake_evidence(monkeypatch, card=None, error=None):
    questions = []

    def ask(question):
        questions.append(question)
        if error:
            raise error
        return card

    monkeypatch.setattr(evidence_service, "ask", ask)
    return questions


def test_plain_question_is_answered_from_the_corpus_with_chips_and_badge(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, PLAIN_QUESTION)
    questions = fake_evidence(monkeypatch, GROUNDED)
    body = _text(live_client.post("/ui/chat", data={"message": "Which bill is overdue?"}))
    assert questions == ["Which bill is overdue?"]
    assert "Home internet (FibreLink, $79.00) is overdue." in body and "Let me check." not in body
    assert "bill #7 · Home internet · 1.08" in body and "confidence-badge confidence-medium" in body
    assert bills_db_module.list_chat_messages()[-1]["content"] == GROUNDED["answer"]


def test_insufficient_context_is_the_fixed_line_with_no_chips(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, PLAIN_QUESTION)
    fake_evidence(monkeypatch, INSUFFICIENT)
    body = _text(live_client.post("/ui/chat", data={"message": "How much is my car insurance?"}))
    assert "couldn't find a bill" in body and "Insufficient context" in body
    assert "citation-chip" not in body


def test_mcp_failure_falls_back_to_the_models_reply(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, PLAIN_QUESTION)
    fake_evidence(monkeypatch, error=ModeError("mcp_connection"))
    response = live_client.post("/ui/chat", data={"message": "Which bill is overdue?"})
    assert response.status_code == 200
    body = _text(response)
    assert "Let me check." in body and "citation-chip" not in body and "8000" not in body


def test_modes_off_never_reach_the_corpus(live_client, monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    fake_model(monkeypatch, PLAIN_QUESTION)
    questions = fake_evidence(monkeypatch, GROUNDED)
    body = _text(live_client.post("/ui/chat", data={"message": "Which bill is overdue?"}))
    assert questions == [] and "Let me check." in body


def test_code_computed_questions_and_proposals_skip_the_corpus(live_client, modes_on, monkeypatch):
    questions = fake_evidence(monkeypatch, GROUNDED)
    fake_model(monkeypatch, dict(PLAIN_QUESTION, question="total"))
    body = _text(live_client.post("/ui/chat", data={"message": "What do my bills add up to?"}))
    assert "ongoing monthly total" in body
    fake_model(monkeypatch, {"op": "update", "entity": "bill", "id": 3, "fields": {"end_date": "2026-09-16"}, "question": "none",
                             "say": "I've suggested ending Spotify after 16 Sep — approve it to save."})
    body = _text(live_client.post("/ui/chat", data={"message": "I cancelled Spotify from September — remove the future payments"}))
    assert "Update Spotify" in body
    assert questions == []


NETFLIX_AS_UPDATE = {"op": "update", "entity": "bill", "id": 5, "fields": {"next_billing_date": "2026-10-14"}, "question": "none",
                     "say": "I've suggested changing the next billing date — approve it to save."}


def test_a_question_naming_a_bill_never_becomes_a_proposal(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, NETFLIX_AS_UPDATE)
    fake_evidence(monkeypatch, dict(GROUNDED, answer="Netflix is next charged on 2026-10-14.", citations=[{"source": "bill-4-netflix.md", "bill_id": 4, "title": "Netflix", "distance": 0.46}], confidence="high"))
    pending_before = len(bills_db_module.list_suggestions(status="pending"))
    body = _text(live_client.post("/ui/chat", data={"message": "When is my Netflix subscription next charged?"}))
    assert "Netflix is next charged on 2026-10-14." in body and "bill #4 · Netflix" in body
    assert "Proposed:" not in body
    assert len(bills_db_module.list_suggestions(status="pending")) == pending_before


def test_a_question_naming_a_bill_is_grounded_even_when_the_model_says_upcoming(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, dict(PLAIN_QUESTION, question="upcoming"))
    questions = fake_evidence(monkeypatch, GROUNDED)
    body = _text(live_client.post("/ui/chat", data={"message": "When is Netflix due?"}))
    assert questions == ["When is Netflix due?"] and "Coming up this week" not in body


@pytest.mark.parametrize("message", ["What's due this week?", "What is coming up in the next two weeks?", "Anything upcoming?"])
def test_a_general_question_about_what_is_due_is_code_computed_whatever_the_model_says(live_client, modes_on, monkeypatch, message):
    fake_model(monkeypatch, PLAIN_QUESTION)
    questions = fake_evidence(monkeypatch, INSUFFICIENT)
    body = _text(live_client.post("/ui/chat", data={"message": message}))
    assert questions == [] and ("Coming up this week" in body or "Nothing is due" in body)
    assert "couldn't find a bill" not in body


def test_a_general_question_the_model_tags_upcoming_stays_code_computed(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, dict(PLAIN_QUESTION, question="upcoming"))
    questions = fake_evidence(monkeypatch, GROUNDED)
    body = _text(live_client.post("/ui/chat", data={"message": "What's due this week?"}))
    assert questions == [] and ("Coming up this week" in body or "Nothing is due" in body)


def test_a_question_with_a_change_verb_still_proposes(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, {"op": "update", "entity": "bill", "id": 4, "fields": {"end_date": "2026-10-14"}, "question": "none",
                             "say": "I've suggested ending Netflix after 14 Oct — approve it to save."})
    questions = fake_evidence(monkeypatch, GROUNDED)
    body = _text(live_client.post("/ui/chat", data={"message": "Can you cancel Netflix from 14 October?"}))
    assert "Proposed:" in body and "Update Netflix" in body and questions == []


def test_chat_panel_shows_the_rag_mode_badge(live_client, modes_on, monkeypatch):
    body = _text(live_client.get("/ui/chat"))
    assert 'class="mode-badge mode-on">RAG enabled</span>' in body
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    body = _text(live_client.get("/ui/chat"))
    assert 'class="mode-badge mode-off">RAG disabled</span>' in body


def test_api_chat_carries_the_grounded_card(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, PLAIN_QUESTION)
    fake_evidence(monkeypatch, GROUNDED)
    payload = live_client.post("/api/chat", json={"message": "Which bill is overdue?"}).get_json()
    assert payload["reply"] == GROUNDED["answer"]
    assert payload["grounded"]["confidence"] == "medium"
    assert [c["source"] for c in payload["grounded"]["citations"]] == ["bill-7-home-internet.md"]


COMPARE = {"bill": {"id": 3, "merchant": "Spotify AU", "amount_cents": 1399}, "payments": [],
           "charges": [{"id": 26, "date": "2026-08-20", "amount_cents": 1799, "description": "Monthly subscription", "differs_from_bill_cents": 400},
                       {"id": 22, "date": "2026-07-15", "amount_cents": 1399, "description": "Spotify Premium subscription", "differs_from_bill_cents": 0}]}


def fake_tool(monkeypatch, data=None, error=None):
    from sophia.backend.clients import mcp_server

    calls = []

    def call_tool(name, arguments):
        calls.append((name, arguments))
        if error:
            raise error
        return data, 41.0

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    return calls


def test_a_question_about_what_a_bill_charged_is_answered_by_the_compare_tool(live_client, modes_on, monkeypatch):
    from datetime import timedelta

    fake_model(monkeypatch, PLAIN_QUESTION)
    questions = fake_evidence(monkeypatch, GROUNDED)
    calls = fake_tool(monkeypatch, COMPARE)
    pending_before = len(bills_db_module.list_suggestions(status="pending"))
    body = _text(live_client.post("/ui/chat", data={"message": "What has Spotify actually charged me?"}))
    start = (config.DEMO_TODAY - timedelta(days=90)).isoformat()
    assert calls == [("compare_bill_with_bank_charges", {"bill_id": 3, "start_date": start, "end_date": config.DEMO_TODAY.isoformat()})]
    assert questions == [] and "Proposed:" not in body
    assert "Spotify AU charged you two times in the last 90 days" in body and "20 Aug" in body and "$4.00 above" in body
    assert "20 Aug · $17.99 · +$4.00 vs bill" in body and "15 Jul · $13.99" in body
    assert "compare_bill_with_bank_charges" in body and "41.0 ms" in body
    assert len(bills_db_module.list_suggestions(status="pending")) == pending_before


def test_no_bank_charges_is_said_plainly(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, PLAIN_QUESTION)
    fake_tool(monkeypatch, dict(COMPARE, charges=[]))
    body = _text(live_client.post("/ui/chat", data={"message": "Has Spotify charged me?"}))
    assert "No bank charges from Spotify AU in the last 90 days." in body


def test_next_charge_questions_stay_grounded_and_mcp_failure_falls_back_to_the_corpus(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, PLAIN_QUESTION)
    questions = fake_evidence(monkeypatch, GROUNDED)
    calls = fake_tool(monkeypatch, COMPARE)
    live_client.post("/ui/chat", data={"message": "When is my Spotify subscription next charged?"})
    assert calls == [] and questions == ["When is my Spotify subscription next charged?"]
    calls = fake_tool(monkeypatch, error=ModeError("mcp_connection"))
    body = _text(live_client.post("/ui/chat", data={"message": "What has Spotify actually charged me?"}))
    assert len(calls) == 1 and "bill #7 · Home internet" in body


def test_tool_answers_never_run_with_mcp_off(live_client, monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    fake_model(monkeypatch, PLAIN_QUESTION)
    calls = fake_tool(monkeypatch, COMPARE)
    body = _text(live_client.post("/ui/chat", data={"message": "What has Spotify actually charged me?"}))
    assert calls == [] and "Let me check." in body
