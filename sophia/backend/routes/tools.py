"""JSON API routes for the MCP tool calls the Bills backend makes."""
from flask import Blueprint, jsonify

from sophia.backend.clients import mcp_server
from sophia.backend.json_body import json_body
from sophia.backend.services.errors import ServiceError
from sophia.backend.services.tools import call_allowed_tool

bp = Blueprint("tools", __name__, url_prefix="/api/tools")


@bp.get("")
def list_tools():
    """List the tools the MCP server registers; 503 mcp_disabled when the switch is off."""
    return jsonify({"tools": mcp_server.list_tools()})


@bp.post("/<name>")
def call_tool(name):
    """Call one allow-listed tool with the JSON body as its arguments; failures map to 400/502/503."""
    arguments = json_body()
    if not isinstance(arguments, dict):
        raise ServiceError("expected a JSON object of tool arguments")
    data, duration_ms = call_allowed_tool(name, arguments)
    return jsonify({"tool": name, "arguments": arguments, "result": data, "count": len(data) if isinstance(data, list) else None, "duration_ms": duration_ms})
