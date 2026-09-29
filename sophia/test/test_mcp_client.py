"""Tests for the MCP client: fastmcp.Client is replaced by FakeClient, no socket is opened."""
import asyncio
import sys
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from sophia.backend import config
from sophia.backend.clients import mcp_server
from sophia.backend.services.errors import ModeError

LEAK = "internal detail that must not leak"


class FakeClient:
    tools = []
    result = None
    error = None
    connect_error = None
    delay = 0
    constructed = []
    calls = []

    def __init__(self, url, timeout=None, init_timeout=None):
        FakeClient.constructed.append((url, timeout, init_timeout))

    async def __aenter__(self):
        if FakeClient.connect_error is not None:
            raise FakeClient.connect_error
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


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.tools = []
    FakeClient.result = SimpleNamespace(data=[])
    FakeClient.error = None
    FakeClient.connect_error = None
    FakeClient.delay = 0
    FakeClient.constructed = []
    FakeClient.calls = []
    monkeypatch.setattr(mcp_server, "Client", FakeClient)
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    monkeypatch.setattr(config, "MCP_SERVER_URL", "http://mcp.test/mcp")
    monkeypatch.setattr(config, "MCP_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(config, "MCP_ALLOWED_TOOLS", frozenset({"search_transactions", "retrieve_context"}))
    return FakeClient


def _raises(code, status, action):
    with pytest.raises(ModeError) as info:
        action()
    assert (info.value.code, info.value.status) == (code, status)
    assert LEAK not in info.value.message
    assert "mcp.test" not in info.value.message and "8000" not in info.value.message
    assert info.value.__cause__ is None
    return info.value


def test_disabled_never_constructs_a_client(monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    _raises("mcp_disabled", 503, lambda: mcp_server.call_tool("search_transactions", {}))
    _raises("mcp_disabled", 503, mcp_server.list_tools)
    assert FakeClient.constructed == []


def test_disabled_path_never_imports_fastmcp(monkeypatch):
    monkeypatch.setattr(config, "MCP_ENABLED", False)
    monkeypatch.setattr(mcp_server, "Client", None)
    monkeypatch.setitem(sys.modules, "fastmcp", None)
    monkeypatch.setitem(sys.modules, "fastmcp.exceptions", None)
    _raises("mcp_disabled", 503, lambda: mcp_server.call_tool("search_transactions", {}))
    _raises("mcp_disabled", 503, mcp_server.list_tools)
    monkeypatch.setattr(config, "MCP_ENABLED", True)
    with pytest.raises(ImportError):
        mcp_server.list_tools()


def test_tool_not_in_allow_list_is_refused_before_connecting():
    _raises("tool_not_allowed", 400, lambda: mcp_server.call_tool("no_such_tool", {}))
    assert FakeClient.constructed == []


def test_connection_failure_is_503_without_upstream_text():
    FakeClient.connect_error = RuntimeError(f"Client failed to connect: {LEAK}")
    _raises("mcp_connection", 503, lambda: mcp_server.call_tool("search_transactions", {"merchant": "FibreLink"}))
    assert FakeClient.calls == []


def test_failure_inside_the_session_is_also_503():
    FakeClient.error = RuntimeError(f"stream closed: {LEAK}")
    _raises("mcp_connection", 503, lambda: mcp_server.call_tool("search_transactions", {"merchant": "FibreLink"}))


def test_timeout_is_503(monkeypatch):
    monkeypatch.setattr(config, "MCP_TIMEOUT_SECONDS", 0.05)
    FakeClient.delay = 0.3
    _raises("mcp_timeout", 503, mcp_server.list_tools)


def test_tool_error_is_502_without_upstream_text():
    FakeClient.error = ToolError(f"1 validation error for call[search_transactions] {LEAK}")
    _raises("mcp_tool_error", 502, lambda: mcp_server.call_tool("search_transactions", {"min_amount": "abc"}))


@pytest.mark.parametrize("data", ["text", None, 42, True])
def test_non_list_or_dict_result_is_502(data):
    FakeClient.result = SimpleNamespace(data=data)
    _raises("mcp_invalid_result", 502, lambda: mcp_server.call_tool("retrieve_context", {"feature": "bills", "question": "x", "k": 2}))


def test_call_tool_returns_data_and_duration_and_passes_arguments_and_timeouts():
    FakeClient.result = SimpleNamespace(data=[{"date": "2026-06-10", "merchant": "FibreLink", "amount": 79.0}])
    data, duration_ms = mcp_server.call_tool("search_transactions", {"merchant": "FibreLink"})
    assert data[0]["merchant"] == "FibreLink"
    assert isinstance(duration_ms, float)
    assert FakeClient.calls == [("search_transactions", {"merchant": "FibreLink"})]
    assert FakeClient.constructed == [("http://mcp.test/mcp", None, 6)]


def test_list_tools_returns_name_description_and_schema_under_both_spellings():
    FakeClient.tools = [
        SimpleNamespace(name="search_transactions", description="Search", input_schema={"type": "object"}),
        SimpleNamespace(name="retrieve_context", description=None, input_schema=None, inputSchema={"required": ["feature"]}),
    ]
    assert mcp_server.list_tools() == [
        {"name": "search_transactions", "description": "Search", "input_schema": {"type": "object"}},
        {"name": "retrieve_context", "description": "", "input_schema": {"required": ["feature"]}},
    ]
