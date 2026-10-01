from __future__ import annotations

import asyncio

from . import config
from .db_api import ServiceError


Client = None


def _client_class():
    global Client
    if Client is None:
        try:
            from fastmcp import Client as fastmcp_client
        except ModuleNotFoundError:
            raise ServiceError("The MCP client dependency is missing in the Budgets backend.", 503, "mcp_unavailable") from None

        Client = fastmcp_client
    return Client


def _run(operation, label: str):
    try:
        from fastmcp.exceptions import McpError, ToolError
    except ModuleNotFoundError:
        raise ServiceError("The MCP client dependency is missing in the Budgets backend.", 503, "mcp_unavailable") from None

    client_class = _client_class()

    async def session():
        async with client_class(
            config.MCP_SERVER_URL,
            timeout=None,
            init_timeout=config.MCP_TIMEOUT_SECONDS + 1,
        ) as client:
            return await operation(client)

    try:
        return asyncio.run(asyncio.wait_for(session(), timeout=config.MCP_TIMEOUT_SECONDS))
    except TimeoutError:
        raise ServiceError("The MCP server did not respond in time.", 503, "mcp_timeout") from None
    except (ToolError, McpError):
        raise ServiceError("The MCP tool reported an error.", 502, "mcp_tool_error") from None
    except Exception:
        raise ServiceError("The MCP server is unavailable.", 503, "mcp_connection") from None


def call_tool(name: str, arguments: dict | None = None):
    if not config.MCP_ENABLED:
        raise ServiceError("MCP mode is disabled.", 503, "mcp_disabled")
    if name not in config.MCP_ALLOWED_TOOLS:
        raise ServiceError("The MCP tool is not allowed.", 400, "tool_not_allowed")

    async def operation(client):
        return await client.call_tool(name, arguments=arguments or {})

    result = _run(operation, name)
    data = getattr(result, "data", None)
    if not isinstance(data, (dict, list)):
        raise ServiceError("The MCP server returned an invalid result.", 502, "mcp_invalid_result")
    return data
