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
