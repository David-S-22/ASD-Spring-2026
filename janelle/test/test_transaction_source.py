from unittest.mock import Mock

from pytest import MonkeyPatch, fixture, mark, raises

from janelle.backend import config
from janelle.backend.services import transaction_source
from janelle.backend.services.chat_service import ChatError
from janelle.backend.services.mcp_client import MCPError


DB_URL = "http://transactions-db:6001"
TOOL = "search_transactions"


def row(transaction_id, date, merchant, description, amount):
    return {
        "id": transaction_id,
        "date": date,
        "merchant": merchant,
        "description": description,
        "amount": amount,
        "category_id": 80,
    }


MERIVALE = row(27, "2026-08-09T00:00:00", "Merivale", "Dinner", 84.5)
CHAT_THAI = row(30, "2026-08-26T00:00:00", "Chat Thai", "Dinner", 47.2)


class FakeTool:
    """Record the arguments the source sends and replay canned results."""

    def __init__(self, results=(), error=None):
        self.results = list(results)
        self.error = error
        self.arguments = []

    def __call__(self, name, arguments):
        self.arguments.append((name, dict(arguments)))
        if self.error is not None:
            raise self.error
        return (self.results.pop(0) if self.results else []), 12.5


@fixture(autouse=True)
def mcp_on(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "MCP_FALLBACK_TO_DATABASE", True)
    monkeypatch.setattr(config, "MCP_TOOL_SUPPORTS_EXTENDED_FILTERS", True)
    monkeypatch.setattr(config, "MCP_SERVER_URL", "http://mcp.test/mcp")


@fixture
def context():
    return {
        "request_id": "request-1",
        "phase": "initial",
        "iteration": 1,
        "category_names": {80: "Dining", 81: "Groceries"},
    }


@fixture
def use_tool(monkeypatch: MonkeyPatch):
    def install(results=(), error=None):
        tool = FakeTool(results, error)
        monkeypatch.setattr(transaction_source.mcp_client, "call_tool", tool)
        return tool

    return install


@fixture
def database(monkeypatch: MonkeyPatch):
    mock = Mock(return_value=[MERIVALE])
    monkeypatch.setattr(transaction_source, "_database_query", mock)
    return mock


def query(filters, context, **options):
    return transaction_source.query_transactions(
        DB_URL,
        filters,
        context=context,
        **options,
    )


@mark.parametrize(("filters", "expected"), [
    (
        {"date_from": "2026-08-01", "date_to": "2026-08-31", "category_id": 81},
        {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "category_name": "Groceries",
        },
    ),
    ({"since": "2026-08-24"}, {"start_date": "2026-08-24"}),
    (
        {"merchant": "Woolworths", "search_text": "coffee", "min_amount": 10},
        {"merchant": "Woolworths", "search_text": "coffee", "min_amount": 10},
    ),
])
def test_tool_arguments_map_plan_filters_by_name(filters, expected, context):
    assert transaction_source._tool_arguments(filters, context) == expected


def test_switch_off_uses_the_database_and_records_skipped_disabled(
    monkeypatch: MonkeyPatch,
    use_tool,
    database,
    context,
):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    tool = use_tool()

    assert query({"merchant": "Merivale"}, context) == [MERIVALE]
    assert tool.arguments == []
    assert context["tool_calls"] == [{
        "server": "http://mcp.test/mcp",
        "tool": TOOL,
        "arguments": {},
        "residual_filters": [],
        "status": "skipped_disabled",
        "rows": 1,
        "truncated": False,
        "duration_ms": 0.0,
        "error": None,
    }]


def test_read_calls_the_tool_and_records_the_call(use_tool, database, context):
    tool = use_tool([[MERIVALE]])

    assert query({"merchant": "Merivale"}, context) == [MERIVALE]
    assert tool.arguments == [(TOOL, {"merchant": "Merivale"})]
    database.assert_not_called()
    call = context["tool_calls"][0]
    assert call["server"] == "http://mcp.test/mcp"
    assert call["tool"] == TOOL
    assert call["status"] == "succeeded"
    assert call["rows"] == 1
    assert call["truncated"] is False
    assert call["error"] is None
    assert call["residual_filters"] == []


def test_write_preview_never_calls_the_tool(use_tool, database, context):
    tool = use_tool()

    rows = query({"merchant": "Merivale"}, context, include_version=True)

    assert rows == [MERIVALE]
    assert tool.arguments == []
    database.assert_called_once_with(DB_URL, {"merchant": "Merivale"}, True)
    assert "tool_calls" not in context


def test_unreachable_server_falls_back_to_the_database(
    use_tool,
    database,
    context,
):
    use_tool(error=MCPError("mcp_connection"))

    assert query({"merchant": "Merivale"}, context) == [MERIVALE]
    database.assert_called_once_with(DB_URL, {"merchant": "Merivale"}, False)
    call = context["tool_calls"][0]
    assert call["status"] == "fallback_database"
    assert call["error"] == "mcp_connection"
    assert call["rows"] == 1
    assert call["arguments"] == {"merchant": "Merivale"}


def test_unreachable_server_without_fallback_fails_safely(
    monkeypatch: MonkeyPatch,
    use_tool,
    database,
    context,
):
    monkeypatch.setattr(config, "MCP_FALLBACK_TO_DATABASE", False)
    use_tool(error=MCPError("mcp_timeout"))

    with raises(ChatError) as error:
        query({"merchant": "Merivale"}, context)

    assert error.value.code == "mcp_unavailable"
    assert error.value.status == 503
    database.assert_not_called()
    call = context["tool_calls"][0]
    assert call["status"] == "failed"
    assert call["error"] == "mcp_timeout"
    assert call["rows"] == 0


def test_dates_produce_one_call_per_date_merged_and_deduplicated(
    use_tool,
    context,
):
    june = row(2, "2026-06-10T00:00:00", "Netflix", "Subscription", 20.99)
    july = row(4, "2026-07-15T00:00:00", "DriveBox", "Storage", 2.99)
    tool = use_tool([[june, july], [july]])

    rows = query({"dates": ["2026-06-10", "2026-07-15"]}, context)

    assert [item["id"] for item in rows] == [4, 2]
    assert tool.arguments == [
        (TOOL, {"start_date": "2026-06-10", "end_date": "2026-06-10"}),
        (TOOL, {"start_date": "2026-07-15", "end_date": "2026-07-15"}),
    ]
    assert len(context["tool_calls"]) == 2


def test_extended_filters_are_applied_locally_when_unsupported(
    monkeypatch: MonkeyPatch,
    use_tool,
    context,
):
    monkeypatch.setattr(config, "MCP_TOOL_SUPPORTS_EXTENDED_FILTERS", False)
    tool = use_tool([[MERIVALE, CHAT_THAI]])

    rows = query(
        {
            "date_from": "2026-08-01",
            "merchant": "merivale",
            "search_text": "DINNER",
            "min_amount": 50,
            "max_amount": 100,
        },
        context,
    )

    assert rows == [MERIVALE]
    assert tool.arguments == [(TOOL, {"start_date": "2026-08-01"})]
    assert context["tool_calls"][0]["residual_filters"] == [
        "merchant",
        "search_text",
        "min_amount",
        "max_amount",
    ]
