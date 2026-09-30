"""Tests for the R1 JSON routes and the error envelope: no network, config switches patched per test."""
import json

import pytest

from sophia.backend import app as backend_app_module
from sophia.backend import config
from sophia.backend.clients import bills_db as bills_db_module
from sophia.backend.clients import transactions as transactions_module
from sophia.backend.services.errors import MODE_MESSAGES, MODE_STATUSES, ModeError, ServiceError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(bills_db_module, "health", lambda: {"ok": True})
    monkeypatch.setattr(transactions_module, "list_transactions", lambda merchant=None, since=None: ([], "stub"))
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    app = backend_app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_mode_error_carries_safe_message_status_and_code():
    error = ModeError("mcp_disabled")
    assert (error.message, error.status, error.code) == ("MCP mode is disabled.", 503, "mcp_disabled")
    assert isinstance(error, ServiceError)
    assert ServiceError("plain").code is None
    assert set(MODE_MESSAGES) == set(MODE_STATUSES)
    assert (MODE_MESSAGES["rag_unavailable"], MODE_STATUSES["rag_unavailable"]) == ("The RAG server is unavailable.", 503)


def test_json_error_envelope_includes_code_only_when_present(client):
    app = client.application

    @app.get("/__raise_mode")
    def raise_mode():
        raise ModeError("tool_not_allowed")

    @app.get("/__raise_plain")
    def raise_plain():
        raise ServiceError("plain", status=404)

    mode = client.get("/__raise_mode")
    assert mode.status_code == 400
    assert json.loads(mode.data) == {"error": "The MCP tool is not allowed.", "code": "tool_not_allowed"}
    plain = client.get("/__raise_plain")
    assert plain.status_code == 404
    assert json.loads(plain.data) == {"error": "plain"}
    assert client.post("/api/chat", data="x", content_type="text/plain").get_json() == {"error": "expected a JSON body"}


from sophia.backend.clients import mcp_server
from sophia.backend.services import evidence as evidence_service


def test_tools_json_twin_refuses_when_disabled_with_janelle_shape(client):
    response = client.post("/api/tools/search_transactions", json={"merchant": "FibreLink"})
    assert response.status_code == 503
    assert json.loads(response.data) == {"error": "MCP mode is disabled.", "code": "mcp_disabled"}
    response = client.post("/api/evidence", json={"question": "Which bill is overdue?"})
    assert response.status_code == 503
    assert json.loads(response.data)["code"] == "mcp_disabled"
    assert client.get("/api/tools").status_code == 503


def test_retrieve_context_tool_route_also_needs_rag_enabled(client, monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(mcp_server, "call_tool", lambda name, arguments: ({"results": []}, 1.0))
    response = client.post("/api/tools/retrieve_context", json={"feature": "bills", "question": "q", "k": 2})
    assert response.status_code == 503
    assert json.loads(response.data) == {"error": "RAG mode is disabled.", "code": "rag_disabled"}
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    assert client.post("/api/tools/retrieve_context", json={"feature": "bills", "question": "q", "k": 2}).status_code == 200


def test_tools_json_twin_passes_arguments_and_wraps_the_rows(client, monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    seen = {}

    def call_tool(name, arguments):
        seen.update(name=name, arguments=arguments)
        return [{"date": "2026-06-10", "description": "Internet plan", "amount": 79.0}], 84.0

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    response = client.post("/api/tools/search_transactions", json={"merchant": "FibreLink"})
    assert response.status_code == 200
    assert seen == {"name": "search_transactions", "arguments": {"merchant": "FibreLink"}}
    assert json.loads(response.data) == {"tool": "search_transactions", "arguments": {"merchant": "FibreLink"}, "result": [{"date": "2026-06-10", "description": "Internet plan", "amount": 79.0}], "count": 1, "duration_ms": 84.0}
    assert client.post("/api/tools/search_transactions", data="x", content_type="text/plain").status_code == 400
    assert client.post("/api/tools/search_transactions", json=[1, 2]).status_code == 400
    monkeypatch.setattr(mcp_server, "list_tools", lambda: [{"name": "retrieve_context", "description": "", "input_schema": {}}])
    assert json.loads(client.get("/api/tools").data) == {"tools": [{"name": "retrieve_context", "description": "", "input_schema": {}}]}


def test_tools_json_twin_maps_mode_errors_and_rag_down(client, monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "RAG_ENABLED", True)

    def call_tool(name, arguments):
        raise ModeError("mcp_tool_error")

    monkeypatch.setattr(mcp_server, "call_tool", call_tool)
    response = client.post("/api/tools/search_transactions", json={"min_amount": "abc"})
    assert response.status_code == 502
    assert json.loads(response.data) == {"error": "The MCP tool reported an error.", "code": "mcp_tool_error"}
    response = client.post("/api/tools/retrieve_context", json={"feature": "bills", "question": "q", "k": 2})
    assert response.status_code == 503
    assert json.loads(response.data) == {"error": "The RAG server is unavailable.", "code": "rag_unavailable"}


def test_evidence_json_twin_returns_the_service_dict(client, monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    monkeypatch.setattr(evidence_service, "ask", lambda question: {"answer": "A", "citations": [], "confidence": "low", "insufficient": False, "retrieval": [], "fallback": False, "duration_ms": 1.0, "asked": question})
    response = client.post("/api/evidence", json={"question": "Which bill is overdue?"})
    assert response.status_code == 200
    assert json.loads(response.data)["asked"] == "Which bill is overdue?"
    assert client.post("/api/evidence", json=["not", "an", "object"]).status_code == 400
    assert client.post("/api/evidence", data="x", content_type="text/plain").status_code == 400
