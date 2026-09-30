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


def test_api_chat_carries_the_grounded_card(live_client, modes_on, monkeypatch):
    fake_model(monkeypatch, PLAIN_QUESTION)
    fake_evidence(monkeypatch, GROUNDED)
    payload = live_client.post("/api/chat", json={"message": "Which bill is overdue?"}).get_json()
    assert payload["reply"] == GROUNDED["answer"]
    assert payload["grounded"]["confidence"] == "medium"
    assert [c["source"] for c in payload["grounded"]["citations"]] == ["bill-7-home-internet.md"]
