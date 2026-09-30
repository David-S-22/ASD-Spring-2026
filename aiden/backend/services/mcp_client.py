"""Client for the shared MCP server, mirroring the other services' clients.

Like Janelle's and Sophia's clients, every failure is raised as ``MCPError``
with a safe code so that server errors, URLs with credentials or transaction
values cannot leak through this module.
"""
import asyncio
import threading
import time

from fastmcp import Client
from fastmcp.exceptions import McpError, ToolError

from ..config import config


SAFE_MESSAGES = {
    "mcp_connection": "The MCP server is unavailable.",
    "mcp_timeout": "The MCP server did not respond in time.",
    "mcp_tool_error": "The MCP tool reported an error.",
    "mcp_invalid_result": "The MCP tool returned an invalid result.",
}


class MCPError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        self.message = message or SAFE_MESSAGES.get(code, "The MCP request failed.")
        super().__init__(self.message)


def _run(coroutine):
    """Run a coroutine to completion from synchronous code.

    Flask request handlers and the review worker normally have no event loop,
    so ``asyncio.run`` is used directly. If a loop is already running in this
    thread, the coroutine runs on a fresh loop in a helper thread instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    outcome = {}

    def target():
        try:
            outcome["value"] = asyncio.run(coroutine)
        except BaseException as error:  # re-raised in the calling thread
            outcome["error"] = error

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def _call(operation):
    """Open a client session, run ``operation(client)`` and map failures."""

    async def session():
        async with Client(config.MCP_SERVER_URL) as client:
            return await operation(client)

    async def bounded():
        return await asyncio.wait_for(session(), timeout=config.MCP_TIMEOUT_SECONDS)

    try:
        return _run(bounded())
    except MCPError:
        raise
    except TimeoutError:
        raise MCPError("mcp_timeout") from None
    except (ToolError, McpError):
        raise MCPError("mcp_tool_error") from None
    except Exception:
        raise MCPError("mcp_connection") from None


def _tool_summary(tool):
    input_schema = getattr(tool, "input_schema", None)
    if input_schema is None:
        input_schema = getattr(tool, "inputSchema", None)
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": input_schema or {},
    }


def list_tools():
    """Return ``[{"name", "description", "input_schema"}]`` from the server."""

    async def operation(client):
        return await client.list_tools()

    tools = _call(operation)
    if not isinstance(tools, list):
        raise MCPError("mcp_invalid_result")
    try:
        return [_tool_summary(tool) for tool in tools]
    except AttributeError:
        raise MCPError("mcp_invalid_result") from None


def call_tool(name, arguments=None):
    """Call a tool and return ``(result.data, duration_ms)``."""

    async def operation(client):
        return await client.call_tool(name, arguments=arguments or {})

    started = time.perf_counter()
    result = _call(operation)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)

    data = getattr(result, "data", None)
    if not isinstance(data, (list, dict)):
        raise MCPError("mcp_invalid_result")
    return data, duration_ms
