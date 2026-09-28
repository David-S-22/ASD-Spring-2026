import json
import logging
from unittest.mock import Mock

from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture

import janelle.backend.app as backend_app
import janelle.backend.services.transaction_orchestrator as transaction_orchestrator
from janelle.backend import config
from janelle.backend.services import transaction_source
from janelle.backend.services.mcp_client import MCPError


CATEGORIES = [
    {"id": 1, "name": "Uncategorised", "type": None},
    {"id": 80, "name": "Dining", "type": "want"},
]
WOOLWORTHS = [
    {
        "id": 41,
        "date": "2026-08-14T00:00:00",
        "merchant": "Woolworths",
        "description": "Weekly shop",
        "amount": 96.4,
        "category_id": 80,
    },
]
TOOL_RECORD_KEYS = {
    "event",
    "request_id",
    "phase",
    "iteration",
    "stage",
    "server",
    "tool",
    "arguments",
    "residual_filters",
    "status",
    "rows",
    "truncated",
    "duration_ms",
    "error",
}


@fixture
def client():
    transaction_orchestrator.reset_transaction_requests()
    with backend_app.app.test_client() as test_client:
        yield test_client
    transaction_orchestrator.reset_transaction_requests()


@fixture
def mcp_on(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "MCP_FALLBACK_TO_DATABASE", True)
    monkeypatch.setattr(config, "MCP_TOOL_SUPPORTS_EXTENDED_FILTERS", True)
    monkeypatch.setattr(config, "MCP_SERVER_URL", "http://mcp.test/mcp")


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def extraction(**overrides):
    result = {
        "operation": "read",
        "transaction_id": None,
        "fields": {},
        "filters": {},
        "calculation": "none",
        "handoff": "none",
        "reply": "Prepared safely.",
        "fallback": False,
        "planning_error": None,
        "retryable": False,
    }
    result.update(overrides)
    return result


def use_extraction(monkeypatch: MonkeyPatch, result):
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service,
        "create_plan",
        Mock(return_value=extraction(**result)),
    )


def use_tool(monkeypatch: MonkeyPatch, rows=None, error=None):
    calls = []

    def call_tool(name, arguments):
        calls.append((name, dict(arguments)))
        if error is not None:
            raise error
        return list(rows or []), 912.4

    monkeypatch.setattr(transaction_source.mcp_client, "call_tool", call_tool)
    return calls


def workflow_records(caplog):
    return [
        json.loads(record.getMessage().split("AI_WORKFLOW ", 1)[1])
        for record in caplog.records
        if "AI_WORKFLOW " in record.getMessage()
    ]


def tool_records(caplog):
    return [
        record
        for record in workflow_records(caplog)
        if record["event"] == "MCP_TOOL"
    ]


def test_tool_record_carries_the_full_schema_and_no_user_text(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    mcp_on,
    caplog,
):
    private_message = "Total my private Woolworths trips in August"
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(WOOLWORTHS),
        ]),
    )
    use_extraction(monkeypatch, {
        "filters": {
            "merchant": "Woolworths",
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
        },
        "calculation": "sum",
    })
    calls = use_tool(monkeypatch, WOOLWORTHS)

    with caplog.at_level(
        logging.INFO,
        logger=client.application.logger.name,
    ):
        response = client.post("/chat", json={"message": private_message})

    assert response.status_code == 200
    records = tool_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert set(record) == TOOL_RECORD_KEYS
    assert record["event"] == "MCP_TOOL"
    assert record["stage"] == "ACT"
    assert record["phase"] == "initial"
    assert record["iteration"] == 1
    assert record["request_id"] == response.get_json()["agent"]["request_id"]
    assert record["server"] == "http://mcp.test/mcp"
    assert record["tool"] == "search_transactions"
    assert record["status"] == "succeeded"
    assert record["rows"] == 1
    assert record["truncated"] is False
    assert record["error"] is None
    assert record["residual_filters"] == []
    assert record["arguments"] == calls[0][1]
    assert record["arguments"] == {
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "merchant": "Woolworths",
    }
    assert "message" not in record
    assert private_message not in caplog.text
    assert "Weekly shop" not in caplog.text


def test_fallback_is_logged_with_a_safe_error_code(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    mcp_on,
    caplog,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(WOOLWORTHS),
        ]),
    )
    use_extraction(monkeypatch, {"calculation": "count"})
    use_tool(monkeypatch, error=MCPError("mcp_connection"))

    with caplog.at_level(
        logging.INFO,
        logger=client.application.logger.name,
    ):
        response = client.post("/chat", json={"message": "How many?"})

    assert response.status_code == 200
    assert response.get_json()["analytics"]["count"] == 1
    record = tool_records(caplog)[0]
    assert record["status"] == "fallback_database"
    assert record["error"] == "mcp_connection"
    assert record["rows"] == 1
    assert "The MCP server is unavailable." not in caplog.text
    act = [
        item
        for item in response.get_json()["agent"]["trace"]
        if item["stage"] == "ACT"
    ]
    assert act[0]["summary"] == (
        "Queried transactions using trusted application code "
        "via database (MCP fallback)."
    )


def test_write_preview_and_confirmation_log_no_tool_record(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    mcp_on,
    caplog,
):
    created = {
        "id": 90,
        "date": "2026-09-01T00:00:00",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 80,
    }
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(CATEGORIES),
            response_with_json(created),
        ]),
    )
    monkeypatch.setattr(
        backend_app.requests,
        "post",
        Mock(return_value=response_with_json(created, status=201)),
    )
    use_extraction(monkeypatch, {
        "operation": "create",
        "fields": {
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    })
    calls = use_tool(monkeypatch, WOOLWORTHS)

    with caplog.at_level(
        logging.INFO,
        logger=client.application.logger.name,
    ):
        preview = client.post(
            "/chat",
            json={
                "message": (
                    "Add lunch at Atomic Cafe on 1 September 2026 "
                    "for $24.50 in Dining"
                ),
            },
        ).get_json()
        applied = client.post("/chat/apply", json=preview["preview"])

    assert applied.status_code == 200
    assert preview["agent"]["tools"] == []
    assert applied.get_json()["agent"]["tools"] == []
    assert tool_records(caplog) == []
    assert calls == []


def test_chat_read_response_exposes_the_tool_call_and_names_it_in_the_trace(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    mcp_on,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(WOOLWORTHS),
        ]),
    )
    use_extraction(monkeypatch, {
        "filters": {"merchant": "Woolworths"},
        "calculation": "count",
    })
    use_tool(monkeypatch, WOOLWORTHS)

    result = client.post(
        "/chat",
        json={"message": "How many Woolworths trips?"},
    ).get_json()

    assert result["agent"]["tools"] == [{
        "server": "http://mcp.test/mcp",
        "tool": "search_transactions",
        "arguments": {"merchant": "Woolworths"},
        "residual_filters": [],
        "status": "succeeded",
        "rows": 1,
        "truncated": False,
        "duration_ms": 912.4,
        "error": None,
    }]
    act = [item for item in result["agent"]["trace"] if item["stage"] == "ACT"]
    assert act[0]["summary"] == (
        "Queried transactions using trusted application code "
        "via MCP tool search_transactions."
    )


def test_mcp_tools_listing_emits_one_record(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    mcp_on,
    caplog,
):
    monkeypatch.setattr(
        backend_app.mcp_client,
        "list_tools",
        Mock(return_value=[
            {
                "name": "search_transactions",
                "description": "Search transactions",
                "input_schema": {"type": "object"},
            },
        ]),
    )

    with caplog.at_level(
        logging.INFO,
        logger=client.application.logger.name,
    ):
        response = client.get("/mcp/tools")

    assert response.status_code == 200
    records = [
        record
        for record in workflow_records(caplog)
        if record["event"] == "MCP_TOOLS_LISTED"
    ]
    assert len(records) == 1
    assert records[0] == {
        "event": "MCP_TOOLS_LISTED",
        "server": "http://mcp.test/mcp",
        "tools": 1,
        "status": "succeeded",
        "duration_ms": records[0]["duration_ms"],
        "error": None,
    }
    assert records[0]["duration_ms"] >= 0
