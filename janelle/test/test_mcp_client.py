import asyncio
from types import SimpleNamespace

from fastmcp.exceptions import ToolError
from pytest import MonkeyPatch, fixture, mark, raises

from janelle.backend import config
from janelle.backend.services import mcp_client
from janelle.backend.services.mcp_client import MCPError


LEAK_MARKER = "internal error detail that must not leak"


class FakeClient:
    """Stand-in for fastmcp.Client driven by class-level behaviour."""

    tools = []
    result = None
    error = None
    delay = 0
    entered_with = []
    calls = []

    def __init__(self, url):
        self.url = url

    async def __aenter__(self):
        FakeClient.entered_with.append(self.url)
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def _respond(self, value):
        if FakeClient.delay:
            await asyncio.sleep(FakeClient.delay)
        if FakeClient.error is not None:
            raise FakeClient.error
        return value

    async def list_tools(self):
        return await self._respond(FakeClient.tools)

    async def call_tool(self, name, arguments=None):
        FakeClient.calls.append((name, arguments))
        return await self._respond(FakeClient.result)


@fixture(autouse=True)
def fake_client(monkeypatch: MonkeyPatch):
    FakeClient.tools = []
    FakeClient.result = SimpleNamespace(data=[])
    FakeClient.error = None
    FakeClient.delay = 0
    FakeClient.entered_with = []
    FakeClient.calls = []
    monkeypatch.setattr(mcp_client, "Client", FakeClient)
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "MCP_SERVER_URL", "http://mcp.test/mcp")
    monkeypatch.setattr(config, "MCP_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(
        config,
        "MCP_ALLOWED_TOOLS",
        frozenset({"search_transactions"}),
    )
    return FakeClient


def test_list_tools_returns_name_description_and_schema():
    FakeClient.tools = [
        SimpleNamespace(
            name="search_transactions",
            description="Search transactions",
            inputSchema={"type": "object"},
        ),
        SimpleNamespace(
            name="retrieve_context",
            description=None,
            input_schema={"type": "object", "properties": {}},
        ),
    ]

    tools = mcp_client.list_tools()

    assert tools == [
        {
            "name": "search_transactions",
            "description": "Search transactions",
            "input_schema": {"type": "object"},
        },
        {
            "name": "retrieve_context",
            "description": "",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]
    assert FakeClient.entered_with == ["http://mcp.test/mcp"]


def test_call_tool_returns_data_and_duration():
    FakeClient.result = SimpleNamespace(data=[{"id": 1}])

    data, duration_ms = mcp_client.call_tool(
        "search_transactions",
        {"start_date": "2026-08-01"},
    )

    assert data == [{"id": 1}]
    assert isinstance(duration_ms, float)
    assert duration_ms >= 0
    assert FakeClient.calls == [
        ("search_transactions", {"start_date": "2026-08-01"}),
    ]


def test_call_tool_accepts_dict_data():
    FakeClient.result = SimpleNamespace(data={"rows": []})

    data, _ = mcp_client.call_tool("search_transactions", {})

    assert data == {"rows": []}


@mark.parametrize("operation", [
    lambda: mcp_client.list_tools(),
    lambda: mcp_client.call_tool("search_transactions", {}),
])
def test_disabled_mode_short_circuits_without_connecting(
    monkeypatch: MonkeyPatch,
    operation,
):
    monkeypatch.setattr(config, "MCP_ENABLED", False)

    with raises(MCPError) as caught:
        operation()

    assert caught.value.code == "mcp_disabled"
    assert FakeClient.entered_with == []


def test_disabled_check_runs_before_allow_list(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "MCP_ENABLED", False)

    with raises(MCPError) as caught:
        mcp_client.call_tool("delete_everything", {})

    assert caught.value.code == "mcp_disabled"


def test_tool_outside_allow_list_is_refused_without_connecting():
    with raises(MCPError) as caught:
        mcp_client.call_tool("retrieve_context", {})

    assert caught.value.code == "tool_not_allowed"
    assert FakeClient.entered_with == []
    assert FakeClient.calls == []


def test_timeout_maps_to_mcp_timeout(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "MCP_TIMEOUT_SECONDS", 0.01)
    FakeClient.delay = 1

    with raises(MCPError) as caught:
        mcp_client.call_tool("search_transactions", {})

    assert caught.value.code == "mcp_timeout"


@mark.parametrize("error, code", [
    (ConnectionError(LEAK_MARKER), "mcp_connection"),
    (RuntimeError(LEAK_MARKER), "mcp_connection"),
    (OSError(LEAK_MARKER), "mcp_connection"),
    (ToolError(LEAK_MARKER), "mcp_tool_error"),
    (TimeoutError(LEAK_MARKER), "mcp_timeout"),
])
def test_errors_map_to_safe_codes_without_leaking_text(error, code):
    FakeClient.error = error

    for operation in (
        lambda: mcp_client.list_tools(),
        lambda: mcp_client.call_tool("search_transactions", {}),
    ):
        with raises(MCPError) as caught:
            operation()

        assert caught.value.code == code
        assert LEAK_MARKER not in caught.value.message
        assert LEAK_MARKER not in str(caught.value)
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__ is True


@mark.parametrize("data", [None, "rows", 42, True])
def test_non_list_or_dict_result_is_invalid(data):
    FakeClient.result = SimpleNamespace(data=data)

    with raises(MCPError) as caught:
        mcp_client.call_tool("search_transactions", {})

    assert caught.value.code == "mcp_invalid_result"


def test_result_without_data_attribute_is_invalid():
    FakeClient.result = object()

    with raises(MCPError) as caught:
        mcp_client.call_tool("search_transactions", {})

    assert caught.value.code == "mcp_invalid_result"


def test_malformed_tool_listing_is_invalid():
    FakeClient.tools = [object()]

    with raises(MCPError) as caught:
        mcp_client.list_tools()

    assert caught.value.code == "mcp_invalid_result"


def test_call_is_safe_when_an_event_loop_is_already_running():
    FakeClient.result = SimpleNamespace(data=[{"id": 3}])

    async def inside_loop():
        return mcp_client.call_tool("search_transactions", {})

    data, _ = asyncio.run(inside_loop())

    assert data == [{"id": 3}]


def test_mcp_error_uses_safe_default_message():
    error = MCPError("mcp_connection")

    assert error.code == "mcp_connection"
    assert error.message == "The MCP server is unavailable."
