"""Client for the shared MCP server; every failure is a ModeError with a safe message. fastmcp loads on first use."""
import asyncio
import logging
import time

from sophia.backend import config
from sophia.backend.services.errors import ModeError

logger = logging.getLogger(__name__)

Client = None


def _client_class():
    """Return the fastmcp Client class, importing it on first use so the disabled path never loads fastmcp."""
    global Client
    if Client is None:
        from fastmcp import Client as fastmcp_client

        Client = fastmcp_client
    return Client


def _session(operation, label):
    """Open one client session, run operation(client) under the timeout, map failures to ModeError."""
    from fastmcp.exceptions import McpError, ToolError

    client_class = _client_class()

    async def run():
        async with client_class(config.MCP_SERVER_URL, timeout=None, init_timeout=config.MCP_TIMEOUT_SECONDS + 1) as client:
            return await operation(client)

    try:
        return asyncio.run(asyncio.wait_for(run(), timeout=config.MCP_TIMEOUT_SECONDS))
    except TimeoutError:
        logger.info("MCP_TOOL tool=%s status=timeout", label)
        raise ModeError("mcp_timeout") from None
    except (ToolError, McpError) as exc:
        logger.info("MCP_TOOL tool=%s status=tool_error kind=%s", label, type(exc).__name__)
        raise ModeError("mcp_tool_error") from None
    except Exception as exc:
        logger.info("MCP_TOOL tool=%s status=connection_error kind=%s", label, type(exc).__name__)
        raise ModeError("mcp_connection") from None


def _tool_summary(tool):
    """Reduce one fastmcp Tool to name, description and input schema (either spelling of the schema attribute)."""
    input_schema = getattr(tool, "input_schema", None)
    if input_schema is None:
        input_schema = getattr(tool, "inputSchema", None)
    return {"name": tool.name, "description": tool.description or "", "input_schema": input_schema or {}}


def list_tools():
    """Return [{"name", "description", "input_schema"}] from the server; ModeError when disabled or failing."""
    if not config.MCP_ENABLED:
        raise ModeError("mcp_disabled")

    async def operation(client):
        return await client.list_tools()

    tools = _session(operation, "list_tools")
    if not isinstance(tools, list):
        raise ModeError("mcp_invalid_result")
    try:
        return [_tool_summary(tool) for tool in tools]
    except AttributeError:
        raise ModeError("mcp_invalid_result") from None


def call_tool(name, arguments):
    """Call an allow-listed tool and return (result.data, duration_ms); ModeError on every failure."""
    if not config.MCP_ENABLED:
        raise ModeError("mcp_disabled")
    if name not in config.MCP_ALLOWED_TOOLS:
        raise ModeError("tool_not_allowed")

    async def operation(client):
        return await client.call_tool(name, arguments=arguments or {})

    started = time.perf_counter()
    result = _session(operation, name)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    data = getattr(result, "data", None)
    if not isinstance(data, (list, dict)):
        raise ModeError("mcp_invalid_result")
    items = len(data["results"]) if isinstance(data, dict) and isinstance(data.get("results"), list) else len(data)
    logger.info("MCP_TOOL tool=%s status=ok items=%s duration_ms=%s", name, items, duration_ms)
    return data, duration_ms
