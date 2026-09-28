from unittest.mock import Mock

from pytest import MonkeyPatch, fixture, mark, raises

from janelle.backend import config
from janelle.backend.services import transaction_source
from janelle.backend.services.chat_service import ChatError
from janelle.backend.services.mcp_client import MCPError


DB_URL = "http://transactions-db:6001"
CATEGORY_NAMES = {80: "Dining", 81: "Groceries"}


def row(transaction_id, date, merchant, description, amount, category_id=80):
    return {
        "id": transaction_id,
        "date": date,
        "merchant": merchant,
        "description": description,
        "amount": amount,
        "category_id": category_id,
    }


MERIVALE = row(27, "2026-08-09T00:00:00", "Merivale", "Dinner", 84.5)
CHAT_THAI = row(30, "2026-08-26T00:00:00", "Chat Thai", "Dinner", 47.2)


class FakeTool:
    """Record the arguments the source sends and replay canned results."""

    def __init__(self, results=None, error=None):
        self.results = list(results if results is not None else [[]])
        self.error = error
        self.arguments = []

    def __call__(self, name, arguments):
        self.arguments.append((name, dict(arguments)))
        if self.error is not None:
            raise self.error
        result = self.results.pop(0) if self.results else []
        return result, 12.5


@fixture
def context():
    return {
        "request_id": "request-1",
        "phase": "initial",
        "iteration": 1,
        "category_names": CATEGORY_NAMES,
    }


@fixture(autouse=True)
def mcp_on(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "MCP_FALLBACK_TO_DATABASE", True)
    monkeypatch.setattr(config, "MCP_TOOL_SUPPORTS_EXTENDED_FILTERS", True)
    monkeypatch.setattr(config, "MCP_SERVER_URL", "http://mcp.test/mcp")


def use_tool(monkeypatch: MonkeyPatch, tool):
    monkeypatch.setattr(
        transaction_source.mcp_client,
        "call_tool",
        tool,
    )
    return tool


def use_database(monkeypatch: MonkeyPatch, rows):
    database = Mock(return_value=rows)
    monkeypatch.setattr(
        transaction_source,
        "_database_query",
        database,
    )
    return database


@mark.parametrize(
    ("filters", "expected"),
    [
        ({}, {}),
        (
            {"date_from": "2026-08-01", "date_to": "2026-08-31"},
            {"start_date": "2026-08-01", "end_date": "2026-08-31"},
        ),
        ({"since": "2026-08-24"}, {"start_date": "2026-08-24"}),
        (
            {"since": "2026-08-24", "date_from": "2026-08-01"},
            {"start_date": "2026-08-01"},
        ),
        ({"category_id": 81}, {"category_name": "Groceries"}),
        (
            {
                "merchant": "Woolworths",
                "search_text": "coffee",
                "min_amount": 10,
                "max_amount": 90.5,
            },
            {
                "merchant": "Woolworths",
                "search_text": "coffee",
                "min_amount": 10,
                "max_amount": 90.5,
            },
        ),
    ],
)
def test_tool_arguments_map_plan_filters_by_name(filters, expected, context):
    assert transaction_source._tool_arguments(filters, context) == expected


def test_read_calls_the_tool_and_records_the_call(
    monkeypatch: MonkeyPatch,
    context,
):
    tool = use_tool(monkeypatch, FakeTool([[MERIVALE]]))
    database = use_database(monkeypatch, [])

    rows = transaction_source.query_transactions(
        DB_URL,
        {"merchant": "Merivale"},
        context=context,
    )

    assert rows == [MERIVALE]
    assert tool.arguments == [
        ("search_transactions", {"merchant": "Merivale"}),
    ]
    database.assert_not_called()
    call = context["tool_calls"][0]
    assert call["server"] == "http://mcp.test/mcp"
    assert call["tool"] == "search_transactions"
    assert call["status"] == "succeeded"
    assert call["rows"] == 1
    assert call["truncated"] is False
    assert call["error"] is None
    assert call["residual_filters"] == []


def test_write_preview_never_calls_the_tool(
    monkeypatch: MonkeyPatch,
    context,
):
    tool = use_tool(monkeypatch, FakeTool())
    database = use_database(monkeypatch, [MERIVALE])

    rows = transaction_source.query_transactions(
        DB_URL,
        {"merchant": "Merivale"},
        include_version=True,
        context=context,
    )

    assert rows == [MERIVALE]
    assert tool.arguments == []
    database.assert_called_once_with(DB_URL, {"merchant": "Merivale"}, True)
    assert "tool_calls" not in context


def test_switch_off_uses_the_database_and_records_skipped_disabled(
    monkeypatch: MonkeyPatch,
    context,
):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    tool = use_tool(monkeypatch, FakeTool())
    use_database(monkeypatch, [MERIVALE])

    rows = transaction_source.query_transactions(
        DB_URL,
        {"merchant": "Merivale"},
        context=context,
    )

    assert rows == [MERIVALE]
    assert tool.arguments == []
    assert context["tool_calls"] == [{
        "server": "http://mcp.test/mcp",
        "tool": "search_transactions",
        "arguments": {},
        "residual_filters": [],
        "status": "skipped_disabled",
        "rows": 1,
        "truncated": False,
        "duration_ms": 0.0,
        "error": None,
    }]


def test_unreachable_server_falls_back_to_the_database(
    monkeypatch: MonkeyPatch,
    context,
):
    use_tool(monkeypatch, FakeTool(error=MCPError("mcp_connection")))
    database = use_database(monkeypatch, [MERIVALE])

    rows = transaction_source.query_transactions(
        DB_URL,
        {"merchant": "Merivale"},
        context=context,
    )

    assert rows == [MERIVALE]
    database.assert_called_once_with(DB_URL, {"merchant": "Merivale"}, False)
    call = context["tool_calls"][0]
    assert call["status"] == "fallback_database"
    assert call["error"] == "mcp_connection"
    assert call["rows"] == 1
    assert call["arguments"] == {"merchant": "Merivale"}


def test_unreachable_server_without_fallback_fails_safely(
    monkeypatch: MonkeyPatch,
    context,
):
    monkeypatch.setattr(config, "MCP_FALLBACK_TO_DATABASE", False)
    use_tool(monkeypatch, FakeTool(error=MCPError("mcp_timeout")))
    database = use_database(monkeypatch, [MERIVALE])

    with raises(ChatError) as error:
        transaction_source.query_transactions(
            DB_URL,
            {"merchant": "Merivale"},
            context=context,
        )

    assert error.value.code == "mcp_unavailable"
    assert error.value.status == 503
    database.assert_not_called()
    call = context["tool_calls"][0]
    assert call["status"] == "failed"
    assert call["error"] == "mcp_timeout"
    assert call["rows"] == 0


def test_dates_produce_one_call_per_date_merged_and_deduplicated(
    monkeypatch: MonkeyPatch,
    context,
):
    june = row(2, "2026-06-10T00:00:00", "Netflix", "Subscription", 20.99)
    july = row(4, "2026-07-15T00:00:00", "DriveBox", "Storage", 2.99)
    tool = use_tool(monkeypatch, FakeTool([[june, july], [july]]))

    rows = transaction_source.query_transactions(
        DB_URL,
        {"dates": ["2026-06-10", "2026-07-15"]},
        context=context,
    )

    assert [item["id"] for item in rows] == [4, 2]
    assert tool.arguments == [
        (
            "search_transactions",
            {"start_date": "2026-06-10", "end_date": "2026-06-10"},
        ),
        (
            "search_transactions",
            {"start_date": "2026-07-15", "end_date": "2026-07-15"},
        ),
    ]
    assert len(context["tool_calls"]) == 2


def test_extended_filters_are_applied_locally_when_unsupported(
    monkeypatch: MonkeyPatch,
    context,
):
    monkeypatch.setattr(config, "MCP_TOOL_SUPPORTS_EXTENDED_FILTERS", False)
    tool = use_tool(monkeypatch, FakeTool([[MERIVALE, CHAT_THAI]]))

    rows = transaction_source.query_transactions(
        DB_URL,
        {
            "date_from": "2026-08-01",
            "merchant": "merivale",
            "search_text": "DINNER",
            "min_amount": 50,
            "max_amount": 100,
        },
        context=context,
    )

    assert rows == [MERIVALE]
    assert tool.arguments == [
        ("search_transactions", {"start_date": "2026-08-01"}),
    ]
    assert context["tool_calls"][0]["residual_filters"] == [
        "merchant",
        "search_text",
        "min_amount",
        "max_amount",
    ]
