"""JSON API and HTMX fragment routes for the MCP tool calls the Bills backend makes."""
import re
from email.utils import parsedate_to_datetime

from flask import Blueprint, jsonify, render_template, request

from sophia.backend import config
from sophia.backend.clients import bills_db, mcp_server
from sophia.backend.json_body import json_body
from sophia.backend.services.errors import NotFound, ServiceError
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


ui = Blueprint("tools_ui", __name__, url_prefix="/ui/tools")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@ui.errorhandler(ServiceError)
def handle_ui_error(error):
    status = error.status if error.status >= 500 else 422
    return render_template("error_fragment.html", message=error.message), status


@ui.errorhandler(Exception)
def handle_unexpected_ui_error(error):
    if isinstance(error, ServiceError):
        raise error
    return render_template("error_fragment.html", message="Something went wrong — try again."), 500


def _display_date(value):
    text = str(value or "")
    if ISO_DATE.match(text):
        return text[:10]
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        return text


def _display_amount(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return ""


def _display_row(row):
    """Normalise one transactions row for the table: ISO or HTTP date, amount as dollars."""
    return {"date": _display_date(row.get("date")), "description": row.get("description") or "", "amount": _display_amount(row.get("amount"))}


def _arguments_from_form(name, form):
    """Turn the card's form into tool arguments: the selected bill's merchant for search_transactions."""
    if name == "search_transactions":
        bill_id = form.get("bill_id", type=int)
        bill = bills_db.get_bill(bill_id) if bill_id is not None else None
        if bill is None:
            raise NotFound("bill not found")
        return {"merchant": bill["merchant"]}
    raise ServiceError("tool not allowed")


@ui.get("")
def tools_panel():
    """Render the card from config and the bills list; the MCP server is not contacted on load."""
    return render_template("tools_panel.html", bills=bills_db.list_bills(), enabled=config.MCP_ENABLED)


@ui.post("/<name>")
def run_tool(name):
    arguments = _arguments_from_form(name, request.form)
    data, duration_ms = call_allowed_tool(name, arguments)
    rows = [_display_row(r) for r in data] if isinstance(data, list) else []
    return render_template("tool_result.html", name=name, arguments=arguments, rows=rows, duration_ms=duration_ms)
