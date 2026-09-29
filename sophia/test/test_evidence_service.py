"""Tests for the grounded evidence service: MCP and Ollama are both faked, gates are asserted in code."""
import json

import pytest

from sophia.backend import config
from sophia.backend.ai import guard
from sophia.backend.clients import mcp_server
from sophia.backend.services import evidence
from sophia.backend.services.errors import ModeError, ServiceError

BILL7 = {"id": "bills_bill-7-home-internet.md_0", "text": "# Home internet (bill)\n\n- Merchant: FibreLink\n- Amount: $79.00\n- Status: overdue",
         "metadata": {"source": "bill-7-home-internet.md", "feature": "bills", "doc_type": "markdown"}, "distance": 1.083}
BILL3 = {"id": "bills_bill-3-spotify.md_0", "text": "# Spotify (subscription)\n\n- Amount: $13.99\n- Status: paid",
         "metadata": {"source": "bill-3-spotify.md", "feature": "bills", "doc_type": "markdown"}, "distance": 0.735}
FAR = {"id": "bills_bill-1-rent.md_0", "text": "# Rent (bill)\n\n- Amount: $1,100.00", "metadata": {"source": "bill-1-rent.md"}, "distance": 1.9}


@pytest.fixture
def modes(monkeypatch):
    high, medium, low = config.RAG_DEFAULT_THRESHOLDS
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    monkeypatch.setattr(config, "RAG_TOP_K", 3)
    monkeypatch.setattr(config, "RAG_HIGH", high)
    monkeypatch.setattr(config, "RAG_MEDIUM", medium)
    monkeypatch.setattr(config, "RAG_LOW", low)


def fake_retrieval(monkeypatch, results):
    calls = []

    def call_tool(name, arguments):
        calls.append((name, arguments))
        return {"results": results}, 12.5

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    return calls


def fake_model(monkeypatch, payload):
    attempts = []

    def chat(model, messages, timeout=None):
        attempts.append((model, messages, timeout))
        return {"message": {"content": json.dumps(payload)}}

    monkeypatch.setattr(guard, "chat", chat)
    return attempts


def test_disabled_modes_refuse_before_any_call(monkeypatch):
    calls = fake_retrieval(monkeypatch, [BILL7])
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    with pytest.raises(ModeError) as info:
        evidence.ask("Which bill is overdue?")
    assert info.value.code == "mcp_disabled"
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    with pytest.raises(ModeError) as info:
        evidence.ask("Which bill is overdue?")
    assert (info.value.code, info.value.status) == ("rag_disabled", 503)
    assert calls == []


def test_grounded_answer_cites_only_retrieved_sources_and_rates_the_cited_chunk(modes, monkeypatch):
    calls = fake_retrieval(monkeypatch, [BILL7, BILL3, FAR])
    attempts = fake_model(monkeypatch, {"answer": "Home internet (FibreLink, $79.00) is overdue.", "cited": ["bill-7-home-internet.md", "bill-99-invented.md"], "insufficient": False})
    result = evidence.ask("Which bill is overdue?")
    assert calls == [("retrieve_context", {"feature": "bills", "question": "Which bill is overdue?", "k": 3})]
    assert attempts[0][0] == config.CHAT_MODEL and attempts[0][2] == config.GROUNDED_TIMEOUT_SECONDS
    assert result["insufficient"] is False and result["fallback"] is False
    assert result["citations"] == [{"source": "bill-7-home-internet.md", "bill_id": 7, "title": "Home internet", "distance": 1.083}]
    assert result["confidence"] == "medium"
    assert [r["source"] for r in result["retrieval"]] == ["bill-3-spotify.md", "bill-7-home-internet.md", "bill-1-rent.md"]
    assert "bill-1-rent.md" not in attempts[0][1][0]["content"]
    assert result["duration_ms"] == 12.5


def test_confidence_follows_the_closest_cited_chunk(modes, monkeypatch):
    fake_retrieval(monkeypatch, [BILL7, BILL3])
    fake_model(monkeypatch, {"answer": "Spotify is $13.99 a month; Home internet is overdue.", "cited": ["bill-7-home-internet.md", "bill-3-spotify.md"], "insufficient": False})
    result = evidence.ask("What do I pay for music, and what is overdue?")
    assert [c["source"] for c in result["citations"]] == ["bill-7-home-internet.md", "bill-3-spotify.md"]
    assert result["confidence"] == "high"


def test_all_chunks_beyond_rag_low_is_insufficient_with_no_model_call(modes, monkeypatch):
    fake_retrieval(monkeypatch, [dict(BILL7, distance=1.6), dict(BILL3, distance=1.7)])
    attempts = fake_model(monkeypatch, {"answer": "should not be used", "cited": [], "insufficient": False})
    result = evidence.ask("What is the capital of France?")
    assert attempts == []
    assert result["insufficient"] is True
    assert result["answer"] == evidence.INSUFFICIENT_ANSWER
    assert result["citations"] == [] and result["confidence"] == "none"
    assert result["retrieval"][0]["distance"] == 1.6


def test_model_saying_insufficient_or_citing_nothing_is_insufficient(modes, monkeypatch):
    fake_retrieval(monkeypatch, [BILL7])
    fake_model(monkeypatch, {"answer": "", "cited": [], "insufficient": True})
    assert evidence.ask("Which bill is overdue?")["insufficient"] is True
    fake_model(monkeypatch, {"answer": "Made up", "cited": ["bill-99-invented.md"], "insufficient": False})
    result = evidence.ask("Which bill is overdue?")
    assert result["insufficient"] is True and result["citations"] == [] and result["confidence"] == "none"


def test_confidence_categories_follow_the_thresholds(modes):
    high, medium, low = config.RAG_HIGH, config.RAG_MEDIUM, config.RAG_LOW
    assert evidence.confidence_for([]) == "none"
    assert evidence.confidence_for([{"distance": high - 0.05}]) == "high"
    assert evidence.confidence_for([{"distance": (medium + low) / 2}, {"distance": high - 0.05}]) == "high"
    assert evidence.confidence_for([{"distance": (high + medium) / 2}]) == "medium"
    assert evidence.confidence_for([{"distance": (medium + low) / 2}]) == "low"


def test_guard_fallback_is_reported_not_dressed_up_as_an_answer(modes, monkeypatch):
    fake_retrieval(monkeypatch, [BILL7])
    fake_model(monkeypatch, {"not": "valid"})
    result = evidence.ask("Which bill is overdue?")
    assert result["fallback"] is True and result["insufficient"] is True
    assert result["answer"] == evidence.FALLBACK_ANSWER and result["citations"] == []


def test_malformed_retrieval_is_a_502(modes, monkeypatch):
    fake_retrieval(monkeypatch, [{"id": 1, "text": None}])
    with pytest.raises(ModeError) as info:
        evidence.ask("Which bill is overdue?")
    assert (info.value.code, info.value.status) == ("mcp_invalid_result", 502)


def test_mcp_failures_propagate_unchanged(modes, monkeypatch):
    def down(name, arguments):
        raise ModeError("mcp_connection")

    monkeypatch.setattr(mcp_server, "call_tool", down)
    with pytest.raises(ModeError) as info:
        evidence.ask("q")
    assert (info.value.code, info.value.status) == ("mcp_connection", 503)


def test_tool_error_on_retrieval_means_the_rag_server_is_unavailable(modes, monkeypatch):
    def rag_down(name, arguments):
        raise ModeError("mcp_tool_error")

    monkeypatch.setattr(mcp_server, "call_tool", rag_down)
    with pytest.raises(ModeError) as info:
        evidence.ask("q")
    assert (info.value.code, info.value.status, info.value.message) == ("rag_unavailable", 503, "The RAG server is unavailable.")
    assert info.value.__cause__ is None


def test_blank_question_is_a_400(modes, monkeypatch):
    calls = fake_retrieval(monkeypatch, [BILL7])
    with pytest.raises(ServiceError) as info:
        evidence.ask("   ")
    assert info.value.status == 400 and calls == []


def test_non_string_question_is_a_400(modes, monkeypatch):
    calls = fake_retrieval(monkeypatch, [BILL7])
    with pytest.raises(ServiceError) as info:
        evidence.ask(5)
    assert info.value.status == 400 and calls == []
