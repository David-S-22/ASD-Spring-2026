"""Serve Tally's transaction reads from the shared MCP tool or the database.

``query_transactions`` is the one seam every transaction read passes through.
Write previews and confirmed writes ask for row versions, which the tool does
not return, so they always take the database path. Read plans take the MCP
path while ``MCP_ENABLED`` is on, and fall back to the database when the
server is unreachable and ``MCP_FALLBACK_TO_DATABASE`` allows it.

Every dispatch records one call dict on ``context["tool_calls"]`` and emits
one ``MCP_TOOL`` workflow record. The record carries validated plan filter
values only: the user message, the planner prompt and the model output never
reach it.
"""
import time

from .. import config
from . import mcp_client
from .mcp_client import MCPError


TOOL_NAME = "search_transactions"
MAX_TOOL_DATES = 7
MAX_ROWS = 500
EXTENDED_FILTERS = ("merchant", "search_text", "min_amount", "max_amount")
ROW_KEYS = ("id", "date", "merchant", "description", "amount", "category_id")


def query_transactions(db_url, filters, include_version=False, context=None):
    """Return the rows matching ``filters`` from the MCP tool or database."""
    if include_version or not config.MCP_ENABLED:
        rows = _database_query(db_url, filters, include_version)
        if not include_version:
            # No call was made, so the record carries no arguments.
            _record(context, _call_record(
                status="skipped_disabled",
                rows=len(rows),
            ))
        return rows

    calls = []
    started = time.perf_counter()
    try:
        rows = _mcp_query(filters, context, calls)
    except MCPError as error:
        duration_ms = _elapsed_ms(started)
        arguments = _tool_arguments(filters, context)
        residual = _residual_filter_names(filters)
        if not config.MCP_FALLBACK_TO_DATABASE:
            calls.append(_call_record(
                arguments=arguments,
                status="failed",
                duration_ms=duration_ms,
                error=error.code,
                residual_filters=residual,
            ))
            _record_all(context, calls)
            raise _chat_service().ChatError(
                "the transaction tool service is unavailable",
                "mcp_unavailable",
                503,
            ) from None
        rows = _database_query(db_url, filters, include_version)
        calls.append(_call_record(
            arguments=arguments,
            status="fallback_database",
            rows=len(rows),
            duration_ms=duration_ms,
            error=error.code,
            residual_filters=residual,
        ))
    _record_all(context, calls)
    return rows


def _database_query(db_url, filters, include_version=False):
    chat_service = _chat_service()
    dates = filters.get("dates")
    if dates is None:
        params = dict(filters)
        if include_version:
            params["_include_version"] = "true"
        options = {"params": params} if params else {}
        return chat_service.database_request(
            "get",
            f"{db_url}/transactions",
            list,
            **options,
        )

    base_filters = {
        key: value
        for key, value in filters.items()
        if key != "dates"
    }
    rows = {}
    for transaction_date in dates:
        date_filters = {
            **base_filters,
            "date_from": transaction_date,
            "date_to": transaction_date,
        }
        if include_version:
            date_filters["_include_version"] = "true"
        for item in chat_service.database_request(
            "get",
            f"{db_url}/transactions",
            list,
            params=date_filters,
        ):
            try:
                rows[item["id"]] = item
            except (KeyError, TypeError) as error:
                raise chat_service.invalid_database_error() from error
    return _sorted_rows(rows.values())


def _mcp_query(filters, context, calls):
    """Call the tool once per plan, or once per date, and merge the rows.

    Succeeded calls are appended to ``calls`` as they happen, so a failure
    part way through a ``dates`` plan still reports the calls that worked.
    """
    dates = filters.get("dates")
    if dates is None:
        rows, call = _call_tool(_tool_arguments(filters, context), filters)
        calls.append(call)
        merged = _apply_residual_filters(rows, filters)
    else:
        merged_by_id = {}
        for transaction_date in list(dates)[:MAX_TOOL_DATES]:
            rows, call = _call_tool(
                _tool_arguments(filters, context, date=transaction_date),
                filters,
            )
            calls.append(call)
            for item in _apply_residual_filters(rows, filters):
                merged_by_id[item["id"]] = item
        merged = _sorted_rows(merged_by_id.values())

    if len(merged) > MAX_ROWS:
        merged = merged[:MAX_ROWS]
        calls[-1]["truncated"] = True
    return merged


def _call_tool(arguments, filters):
    data, duration_ms = mcp_client.call_tool(TOOL_NAME, arguments)
    rows = _validated_rows(data)
    return rows, _call_record(
        arguments=arguments,
        status="succeeded",
        rows=len(rows),
        duration_ms=duration_ms,
        residual_filters=_residual_filter_names(filters),
    )


def _tool_arguments(filters, context, date=None):
    """Map validated plan filters onto ``search_transactions`` arguments."""
    arguments = {}
    if date is not None:
        arguments["start_date"] = date
        arguments["end_date"] = date
    else:
        start_date = filters.get("date_from") or filters.get("since")
        if start_date is not None:
            arguments["start_date"] = start_date
        if filters.get("date_to") is not None:
            arguments["end_date"] = filters["date_to"]

    category_id = filters.get("category_id")
    if category_id is not None:
        # An unknown id would already have failed plan validation, so the
        # missing-name branch below is defensive only.
        category_name = (context or {}).get("category_names", {}).get(
            category_id
        )
        if category_name is not None:
            arguments["category_name"] = category_name

    if config.MCP_TOOL_SUPPORTS_EXTENDED_FILTERS:
        for name in EXTENDED_FILTERS:
            if filters.get(name) is not None:
                arguments[name] = filters[name]
    return arguments


def _residual_filter_names(filters):
    """Return the filters this module has to apply to the returned rows."""
    if config.MCP_TOOL_SUPPORTS_EXTENDED_FILTERS:
        return []
    return [name for name in EXTENDED_FILTERS if filters.get(name) is not None]


def _apply_residual_filters(rows, filters):
    """Apply the filters the tool did not receive, as the database would.

    ``merchant`` is a case-insensitive exact match, ``search_text`` a
    case-insensitive substring of the merchant or description, and the
    amount bounds are inclusive.
    """
    residual = _residual_filter_names(filters)
    if not residual:
        return list(rows)

    kept = list(rows)
    if "merchant" in residual:
        query = filters["merchant"].casefold()
        kept = [row for row in kept if row["merchant"].casefold() == query]
    if "search_text" in residual:
        query = filters["search_text"].casefold()
        kept = [
            row
            for row in kept
            if query in row["merchant"].casefold()
            or query in row["description"].casefold()
        ]
    if "min_amount" in residual:
        minimum = float(filters["min_amount"])
        kept = [row for row in kept if float(row["amount"]) >= minimum]
    if "max_amount" in residual:
        maximum = float(filters["max_amount"])
        kept = [row for row in kept if float(row["amount"]) <= maximum]
    return kept


def _validated_rows(data):
    """Return ``data`` when it is a list of rows shaped like a transaction."""
    if not isinstance(data, list):
        raise MCPError("mcp_invalid_result")
    for item in data:
        if not isinstance(item, dict) or any(
            key not in item for key in ROW_KEYS
        ):
            raise MCPError("mcp_invalid_result")
    return data


def _sorted_rows(rows):
    chat_service = _chat_service()
    try:
        return sorted(
            rows,
            key=lambda item: (
                chat_service.parse_transaction_date(item["date"]),
                item["id"],
            ),
            reverse=True,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise chat_service.invalid_database_error() from error


def _call_record(
    arguments=None,
    *,
    status,
    rows=0,
    duration_ms=0.0,
    error=None,
    residual_filters=(),
    truncated=False,
):
    return {
        "server": config.MCP_SERVER_URL,
        "tool": TOOL_NAME,
        "arguments": dict(arguments or {}),
        "residual_filters": list(residual_filters),
        "status": status,
        "rows": rows,
        "truncated": truncated,
        "duration_ms": duration_ms,
        "error": error,
    }


def _record_all(context, calls):
    for call in calls:
        _record(context, call)


def _record(context, call):
    from .transaction_orchestrator import log_tool_call

    if isinstance(context, dict):
        context.setdefault("tool_calls", []).append(call)
    else:
        context = {}
    log_tool_call(
        context.get("request_id"),
        context.get("phase", "initial"),
        context.get("iteration", 1),
        call,
    )


def _elapsed_ms(started):
    return round((time.perf_counter() - started) * 1000, 1)


def _chat_service():
    from . import chat_service

    return chat_service
