import json
import logging
from unittest.mock import Mock

from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark

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
PRIVATE_MESSAGE = "Total my private Woolworths trips in August"
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
def client(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "MCP_FALLBACK_TO_DATABASE", True)
    monkeypatch.setattr(config, "MCP_TOOL_SUPPORTS_EXTENDED_FILTERS", True)
    monkeypatch.setattr(config, "MCP_SERVER_URL", "http://mcp.test/mcp")
    transaction_orchestrator.reset_transaction_requests()
    with backend_app.app.test_client() as test_client:
        yield test_client
    transaction_orchestrator.reset_transaction_requests()


def response_with_json(payload):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def use_read_plan(monkeypatch: MonkeyPatch, tool_error=None):
    """Plan a Woolworths August sum with the database and tool both stubbed."""
    # Categories, merchant resolution, then the database read on fallback.
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(WOOLWORTHS),
            response_with_json(WOOLWORTHS),
        ]),
    )
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service,
        "create_plan",
        Mock(return_value={
            "operation": "read",
            "transaction_id": None,
            "fields": {},
            "filters": {
                "merchant": "Woolworths",
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
            },
            "calculation": "sum",
            "handoff": "none",
            "reply": "Prepared safely.",
            "fallback": False,
            "planning_error": None,
            "retryable": False,
        }),
    )

    def call_tool(name, arguments):
        if tool_error is not None:
            raise tool_error
        return list(WOOLWORTHS), 912.4

    monkeypatch.setattr(transaction_source.mcp_client, "call_tool", call_tool)


def workflow_records(caplog, event):
    return [
        record
        for record in (
            json.loads(item.getMessage().split("AI_WORKFLOW ", 1)[1])
            for item in caplog.records
            if "AI_WORKFLOW " in item.getMessage()
        )
        if record["event"] == event
    ]


@mark.parametrize(("tool_error", "status", "error", "summary"), [
    (None, "succeeded", None, "via MCP tool search_transactions."),
    (
        MCPError("mcp_connection"),
        "fallback_database",
        "mcp_connection",
        "via database (MCP fallback).",
    ),
])
def test_read_logs_one_redacted_tool_record_and_exposes_it_in_the_response(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    caplog,
    tool_error,
    status,
    error,
    summary,
):
    use_read_plan(monkeypatch, tool_error)

    with caplog.at_level(logging.INFO, logger=client.application.logger.name):
        response = client.post("/chat", json={"message": PRIVATE_MESSAGE})

    assert response.status_code == 200
    result = response.get_json()
    assert result["analytics"]["sum"] == 96.4

    # Response contract: the call is exposed and named in the ACT trace.
    tool = result["agent"]["tools"][0]
    act = [item for item in result["agent"]["trace"] if item["stage"] == "ACT"]
    assert act[0]["summary"].endswith(summary)

    # Logging contract: one record mirroring the call, with no user text.
    records = workflow_records(caplog, "MCP_TOOL")
    assert len(records) == 1
    record = records[0]
    assert set(record) == TOOL_RECORD_KEYS
    assert {key: record[key] for key in tool} == tool
    assert record["stage"] == "ACT"
    assert record["phase"] == "initial"
    assert record["iteration"] == 1
    assert record["request_id"] == result["agent"]["request_id"]
    assert PRIVATE_MESSAGE not in caplog.text
    assert "Weekly shop" not in caplog.text
    assert "The MCP server is unavailable." not in caplog.text

    assert tool.pop("duration_ms") >= 0
    assert tool == {
        "server": "http://mcp.test/mcp",
        "tool": "search_transactions",
        "arguments": {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "merchant": "Woolworths",
        },
        "residual_filters": [],
        "status": status,
        "rows": 1,
        "truncated": False,
        "error": error,
    }


def test_mcp_tools_listing_emits_one_record(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    caplog,
):
    monkeypatch.setattr(
        backend_app.mcp_client,
        "list_tools",
        Mock(return_value=[{
            "name": "search_transactions",
            "description": "Search transactions",
            "input_schema": {"type": "object"},
        }]),
    )

    with caplog.at_level(logging.INFO, logger=client.application.logger.name):
        response = client.get("/mcp/tools")

    assert response.status_code == 200
    records = workflow_records(caplog, "MCP_TOOLS_LISTED")
    assert len(records) == 1
    assert records[0].pop("duration_ms") >= 0
    assert records[0] == {
        "event": "MCP_TOOLS_LISTED",
        "server": "http://mcp.test/mcp",
        "tools": 1,
        "status": "succeeded",
        "error": None,
    }
