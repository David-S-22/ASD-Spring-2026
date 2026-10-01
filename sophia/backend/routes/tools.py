"""JSON API and HTMX fragment routes for the MCP tool calls the Bills backend makes."""
import re
from datetime import timedelta
from email.utils import parsedate_to_datetime

from flask import Blueprint, jsonify, render_template, request

from sophia.backend import config
from sophia.backend.clients import bills_db, mcp_server
from sophia.backend.engine.money import format_actual
from sophia.backend.fragment_errors import register_fragment_error_handlers
from sophia.backend.json_body import json_body
from sophia.backend.services.errors import NotFound, ServiceError
from sophia.backend.services.tools import call_allowed_tool

BILLS_DB_TOOLS = {"get_bill_payments": "payments", "compare_bill_with_bank_charges": "charges"}
COMPARE_WINDOW_DAYS = 90

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
register_fragment_error_handlers(ui)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


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
    """Normalise one row for the table: ISO or HTTP date, amount in dollars (from cents when the row carries cents), and the difference from the bill when the tool reports one."""
    amount = format_actual(row["amount_cents"]) if "amount_cents" in row else _display_amount(row.get("amount"))
    delta = row.get("differs_from_bill_cents") or 0
    note = f"{'+' if delta > 0 else '-'}{format_actual(abs(delta))} vs bill" if delta else ""
    return {"date": _display_date(row.get("date")), "description": row.get("description") or "", "amount": amount, "note": note}


def _arguments_from_form(name, form):
    """Turn the card's form into tool arguments: the selected bill's merchant for search_transactions, its id for the bills-db tools, plus a 90-day window ending today for the comparison."""
    if name != "search_transactions" and name not in BILLS_DB_TOOLS:
        raise ServiceError("tool not allowed")
    bill_id = form.get("bill_id", type=int)
    bill = bills_db.get_bill(bill_id) if bill_id is not None else None
    if bill is None:
        raise NotFound("bill not found")
    if name == "search_transactions":
        return {"merchant": bill["merchant"]}
    if name == "get_bill_payments":
        return {"bill_id": bill["id"]}
    today = config.DEMO_TODAY
    return {"bill_id": bill["id"], "start_date": (today - timedelta(days=COMPARE_WINDOW_DAYS)).isoformat(), "end_date": today.isoformat()}


@ui.get("")
def tools_panel():
    """Render the card from config and the bills list; the MCP server is not contacted on load."""
    return render_template("tools_panel.html", bills=bills_db.list_bills(), enabled=config.MCP_ENABLED)


@ui.post("/<name>")
def run_tool(name):
    arguments = _arguments_from_form(name, request.form)
    data, duration_ms = call_allowed_tool(name, arguments)
    items = data.get(BILLS_DB_TOOLS.get(name), []) if isinstance(data, dict) else data
    rows = [_display_row(r) for r in items] if isinstance(items, list) else []
    return render_template("tool_result.html", name=name, arguments=arguments, rows=rows, duration_ms=duration_ms, noted=any(r["note"] for r in rows))
