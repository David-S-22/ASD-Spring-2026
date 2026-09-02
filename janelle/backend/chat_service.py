"""AI chat orchestration for transactions."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.utils import parsedate_to_datetime

import requests

from . import config, ollama_service


DB_FIELDS = {"date", "merchant", "description", "amount", "category_id"}
MODEL_FIELDS = DB_FIELDS | {"amount_cents", "category"}
FILTER_FIELDS = {
    "q", "date_from", "date_to", "since", "merchant", "category_id",
    "min_amount", "max_amount",
}
ROW_FIELDS = (
    "id", "date", "merchant", "description", "amount", "category_id",
    "category_name",
)


class ChatError(Exception):
    def __init__(self, message, code, status, **details):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details

    def to_dict(self):
        return {"error": self.message, "code": self.code, **self.details}


def handle_message(message, db_url):
    message = _message(message)
    raw_transactions = _db("get", f"{db_url}/transactions", list)
    raw_categories = _db("get", f"{db_url}/categories", list)
    categories, names, ids = _categories(raw_categories)
    transactions = [_row(item, names) for item in raw_transactions]
    result = ollama_service.parse_chat(message, transactions, categories)

    if result["fallback"]:
        return _base_response(result, operation=None, fallback=True)
    if result["operation"] == "read":
        return _read_response(
            result,
            db_url,
            names,
            ids,
            transactions,
        )
    return _write_preview(result, db_url, names, ids, transactions)


def apply_preview(payload, db_url):
    preview = payload.get("preview") if "preview" in payload else payload
    if not isinstance(preview, dict):
        raise ChatError("preview must be a JSON object", "invalid_preview", 400)

    operation = preview.get("operation")
    fields = preview.get("fields")
    if operation not in {"create", "update", "delete"}:
        raise ChatError("invalid preview operation", "invalid_preview", 422)
    if not isinstance(fields, dict):
        raise ChatError("preview fields must be an object", "invalid_preview", 422)
    unknown = sorted(set(fields) - DB_FIELDS)
    if unknown:
        raise ChatError(
            f"unsupported fields: {', '.join(unknown)}",
            "unsupported_fields",
            422,
        )

    _categories_list, names, ids = _categories(
        _db("get", f"{db_url}/categories", list)
    )
    if operation == "create":
        clean = _write_fields(fields, names, ids, create=True)
        expected = _after(None, clean, names)
        if preview.get("transaction_id") is not None or preview.get("before") is not None:
            raise ChatError("invalid create preview", "invalid_preview", 422)
        _require_row(preview.get("after"), expected)
        transaction = _db(
            "post", f"{db_url}/transactions", dict, json=clean
        )
        return {"operation": operation, "transaction": transaction}

    transaction_id = _positive_id(preview.get("transaction_id"))
    try:
        current = _row(
            _db("get", f"{db_url}/transactions/{transaction_id}", dict),
            names,
        )
    except ChatError as error:
        if error.code == "transaction_not_found":
            raise _stale() from error
        raise
    if not _same_row(preview.get("before"), current):
        raise _stale()

    if operation == "delete":
        if fields or preview.get("after") is not None:
            raise ChatError("invalid delete preview", "invalid_preview", 422)
        _db("delete", f"{db_url}/transactions/{transaction_id}")
        return {"operation": operation, "deleted": current}

    clean = _write_fields(fields, names, ids)
    if not clean:
        raise ChatError("update fields are required", "invalid_preview", 422)
    _require_row(preview.get("after"), _after(current, clean, names))
    transaction = _db(
        "patch", f"{db_url}/transactions/{transaction_id}", dict, json=clean
    )
    return {"operation": operation, "transaction": transaction}


def _read_response(result, db_url, names, ids, available_transactions):
    filters = _resolve_search_filters(
        _filters(result["filters"], names, ids),
        available_transactions,
    )
    if result["transaction_id"] is not None:
        try:
            raw_rows = [_db(
                "get",
                f"{db_url}/transactions/{result['transaction_id']}",
                dict,
            )]
        except ChatError as error:
            if error.code != "transaction_not_found":
                raise
            raw_rows = []
    else:
        raw_rows = _query_transactions(db_url, filters)

    transactions = [_row(item, names) for item in raw_rows]
    calculations = _calculations(result["calculation"])
    metrics = _analytics(transactions)
    if "largest" in calculations:
        transactions = sorted(
            transactions,
            key=lambda transaction: transaction["amount"],
            reverse=True,
        )[:5]
    return {
        **_base_response(result),
        "filters": filters,
        "analytics": {**metrics, "calculations": calculations},
        "transactions": transactions,
        "reply": _analytics_reply(metrics, calculations, filters),
    }


def _write_preview(result, db_url, names, ids, available_transactions):
    operation = result["operation"]
    if operation == "create":
        fields = _write_fields(result["fields"], names, ids, create=True)
        return _preview_response(result, {
            "operation": operation,
            "transaction_id": None,
            "fields": fields,
            "before": None,
            "after": _after(None, fields, names),
            "changes": {
                key: {"before": None, "after": value}
                for key, value in fields.items()
            },
        })

    matches = _matches(
        result,
        db_url,
        names,
        ids,
        available_transactions,
    )
    if len(matches) != 1:
        return _clarification(operation, matches)

    before = matches[0]
    if operation == "delete":
        return _preview_response(result, {
            "operation": operation,
            "transaction_id": before["id"],
            "fields": {},
            "before": before,
            "after": None,
            "changes": {},
        })

    requested = _write_fields(result["fields"], names, ids)
    changed = {
        key: value
        for key, value in requested.items()
        if not _same_value(before.get(key), value)
    }
    if not changed:
        return {
            **_base_response(result),
            "reply": "The matching transaction already has those values.",
        }
    return _preview_response(result, {
        "operation": operation,
        "transaction_id": before["id"],
        "fields": changed,
        "before": before,
        "after": _after(before, changed, names),
        "changes": {
            key: {"before": before.get(key), "after": value}
            for key, value in changed.items()
        },
    })


def _matches(result, db_url, names, ids, available_transactions):
    transaction_id = result["transaction_id"]
    if transaction_id is not None:
        try:
            item = _db("get", f"{db_url}/transactions/{transaction_id}", dict)
        except ChatError as error:
            if error.code == "transaction_not_found":
                return []
            raise
        return [_row(item, names)]

    filters = _resolve_search_filters(
        _filters(result["filters"], names, ids),
        available_transactions,
    )
    if not filters:
        return []
    return [
        _row(item, names)
        for item in _query_transactions(db_url, filters)
    ]


def _query_transactions(db_url, filters):
    dates = filters.get("dates")
    if dates is None:
        options = {"params": filters} if filters else {}
        return _db("get", f"{db_url}/transactions", list, **options)

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
        for item in _db(
            "get",
            f"{db_url}/transactions",
            list,
            params=date_filters,
        ):
            try:
                rows[item["id"]] = item
            except (KeyError, TypeError) as error:
                raise _invalid_database() from error
    try:
        return sorted(
            rows.values(),
            key=lambda item: (_date(item["date"]), item["id"]),
            reverse=True,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise _invalid_database() from error


def _db(method, url, expected=None, **options):
    response = getattr(requests, method)(
        url,
        timeout=config.DATABASE_TIMEOUT_SECONDS,
        **options,
    )
    if response.status_code == 204:
        if expected is None:
            return None
        raise _invalid_database()
    if response.status_code >= 400:
        if response.status_code >= 500:
            raise ChatError(
                "transactions database is unavailable",
                "database_unavailable",
                503,
            )
        try:
            error = response.json()
        except (ValueError, RecursionError):
            error = {}
        if not isinstance(error, dict):
            error = {}
        raise ChatError(
            error.get("error", "transactions database rejected the request"),
            error.get("code", "database_request_rejected"),
            response.status_code,
        )
    try:
        data = response.json()
    except (ValueError, RecursionError) as error:
        raise _invalid_database() from error
    if expected is not None and (
        not isinstance(data, expected)
        or (
            expected is list
            and not all(isinstance(item, dict) for item in data)
        )
    ):
        raise _invalid_database()
    return data


def _categories(rows):
    categories = []
    names = {}
    ids = {}
    for item in rows:
        category_id = item.get("id")
        name = item.get("name")
        if not _positive_integer(category_id) or not isinstance(name, str):
            raise _invalid_database()
        category = {"id": category_id, "name": name, "type": item.get("type")}
        categories.append(category)
        names[category_id] = name
        ids[name.casefold()] = category_id
    return categories, names, ids


def _row(item, names):
    try:
        transaction_id = item["id"]
        category_id = item["category_id"]
        row = {
            "id": transaction_id,
            "date": item["date"],
            "merchant": item["merchant"],
            "description": item["description"],
            "amount": float(item["amount"]),
            "category_id": category_id,
            "category_name": names[category_id],
        }
    except (KeyError, TypeError, ValueError) as error:
        raise _invalid_database() from error
    if not _positive_integer(transaction_id):
        raise _invalid_database()
    return row


def _write_fields(fields, names, ids, create=False):
    if not isinstance(fields, dict):
        raise ChatError("fields must be an object", "invalid_preview", 422)
    unknown = sorted(set(fields) - MODEL_FIELDS)
    if unknown:
        raise ChatError(
            f"unsupported fields: {', '.join(unknown)}",
            "unsupported_fields",
            422,
        )

    clean = {
        key: fields[key]
        for key in DB_FIELDS - {"category_id"}
        if key in fields and fields[key] is not None
    }
    if fields.get("amount_cents") is not None:
        cents = fields["amount_cents"]
        if not isinstance(cents, int) or isinstance(cents, bool):
            raise ChatError("amount_cents is invalid", "invalid_amount", 422)
        cents_amount = float(Decimal(cents) / 100)
        if "amount" in clean and not _same_value(clean["amount"], cents_amount):
            raise ChatError(
                "amount and amount_cents do not match",
                "invalid_amount",
                422,
            )
        clean["amount"] = cents_amount

    category_id = fields.get("category_id")
    category_name = fields.get("category")
    if category_id is not None or category_name is not None or create:
        clean["category_id"] = _category_id(
            category_id, category_name, names, ids, use_default=create
        )
    if create:
        missing = [
            key
            for key in ("date", "merchant", "description", "amount", "category_id")
            if key not in clean
        ]
        if missing:
            raise ChatError(
                f"missing required fields: {', '.join(missing)}",
                "missing_fields",
                422,
            )
    return clean


def _filters(filters, names, ids):
    unknown = sorted(
        set(filters) - (FILTER_FIELDS | {"category", "date", "dates"})
    )
    if unknown:
        raise ChatError(
            f"unsupported filters: {', '.join(unknown)}",
            "unsupported_fields",
            422,
        )
    clean = {
        key: value
        for key, value in filters.items()
        if key in FILTER_FIELDS and key != "category_id" and value is not None
    }
    if filters.get("date") is not None:
        clean["date_from"] = filters["date"]
        clean["date_to"] = filters["date"]
    if filters.get("dates") is not None:
        dates = filters["dates"]
        if (
            not isinstance(dates, list)
            or not dates
            or any(not isinstance(value, str) for value in dates)
        ):
            raise ChatError(
                "dates filter is invalid",
                "invalid_filter",
                422,
            )
        clean["dates"] = list(dates)
    if filters.get("category_id") is not None or filters.get("category") is not None:
        clean["category_id"] = _category_id(
            filters.get("category_id"),
            filters.get("category"),
            names,
            ids,
        )
    return clean


def _resolve_search_filters(filters, transactions):
    merchant = filters.get("merchant")
    if merchant is None or filters.get("q") is not None:
        return filters

    fragment = merchant.strip()
    query = fragment.casefold()
    if any(
        transaction["merchant"].casefold() == query
        for transaction in transactions
    ):
        return filters
    if not any(
        query in transaction["merchant"].casefold()
        or query in transaction["description"].casefold()
        for transaction in transactions
    ):
        return filters

    resolved = {
        key: value
        for key, value in filters.items()
        if key != "merchant"
    }
    resolved["q"] = fragment
    return resolved


def _category_id(category_id, category_name, names, ids, use_default=False):
    named_id = None
    if category_name is not None:
        if not isinstance(category_name, str):
            raise ChatError("category is invalid", "invalid_category", 422)
        named_id = ids.get(category_name.strip().casefold())
        if named_id is None:
            raise ChatError("category not found", "category_not_found", 422)
    if category_id is not None:
        if category_id not in names:
            raise ChatError("category not found", "category_not_found", 422)
        if named_id is not None and named_id != category_id:
            raise ChatError(
                "category and category_id do not match",
                "category_mismatch",
                422,
            )
        return category_id
    if named_id is not None:
        return named_id
    if use_default and "uncategorised" in ids:
        return ids["uncategorised"]
    raise ChatError("category is required", "category_required", 422)


def _analytics(transactions):
    try:
        cents = [int(Decimal(str(item["amount"])) * 100) for item in transactions]
    except (InvalidOperation, ValueError) as error:
        raise _invalid_database() from error
    total = sum(cents)
    count = len(cents)
    average = (
        (Decimal(total) / count / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if count
        else None
    )
    dates = sorted(_date(item["date"]) for item in transactions)
    return {
        "count": count,
        "sum": float(Decimal(total) / 100),
        "sum_cents": total,
        "average": float(average) if average is not None else None,
        "average_cents": int(average * 100) if average is not None else None,
        "date_from": dates[0].isoformat() if dates else None,
        "date_to": dates[-1].isoformat() if dates else None,
    }


def _analytics_reply(metrics, calculations, filters):
    count = metrics["count"]
    if not count:
        period = _analytics_period(metrics, filters)
        return f"I found no matching transactions{period}."
    if calculations == ["largest"]:
        shown = min(count, 5)
        return (
            f"Here are your {shown} biggest matching "
            f"purchase{'s' if shown != 1 else ''}."
        )
    parts = []
    if "count" in calculations:
        parts.append(f"{count} matching transaction{'s' if count != 1 else ''}")
    if "sum" in calculations:
        parts.append(f"a total of {_format_money(metrics['sum_cents'])}")
    if "average" in calculations:
        parts.append(
            f"an average spend of {_format_money(metrics['average_cents'])}"
        )
    detail = (
        "I calculated " + ", and ".join(parts)
        if parts
        else f"I found {count} matching transaction{'s' if count != 1 else ''}"
    )
    return f"{detail}{_analytics_period(metrics, filters)}."


def _analytics_period(metrics, filters):
    dates = filters.get("dates")
    if dates:
        labels = [_date_label(value) for value in dates]
        if len(labels) == 1:
            return f" on {labels[0]}"
        return f" on {', '.join(labels[:-1])} and {labels[-1]}"
    date_from = (
        filters.get("date_from")
        or filters.get("since")
        or metrics["date_from"]
    )
    date_to = filters.get("date_to") or metrics["date_to"]
    if date_from and date_to:
        if _date(date_from) == _date(date_to):
            return f" on {_date_label(date_from)}"
        return f" from {_date_label(date_from)} to {_date_label(date_to)}"
    if date_from:
        return f" since {_date_label(date_from)}"
    if date_to:
        return f" up to {_date_label(date_to)}"
    return ""


def _date_label(value):
    parsed = _date(value)
    return f"{parsed.day} {parsed:%b %Y}"


def _base_response(result, operation=None, fallback=False):
    return {
        "reply": result["reply"],
        "operation": result["operation"] if operation is None and not fallback else operation,
        "handoff": "none",
        "requires_confirmation": False,
        "requires_clarification": False,
        "preview": None,
        "fallback": fallback,
    }


def _preview_response(result, preview):
    return {
        **_base_response(result),
        "requires_confirmation": True,
        "preview": preview,
    }


def _clarification(operation, matches):
    reply = (
        f"I found {len(matches)} matching transactions. Choose a transaction ID before confirming a change."
        if matches
        else "I could not find a matching transaction. No changes were made."
    )
    return {
        "reply": reply,
        "operation": operation,
        "handoff": "none",
        "requires_confirmation": False,
        "requires_clarification": True,
        "matches": matches[:10],
        "preview": None,
        "fallback": False,
    }


def _after(before, fields, names):
    row = (
        {
            "id": None,
            "date": fields.get("date"),
            "merchant": fields.get("merchant"),
            "description": fields.get("description"),
            "amount": fields.get("amount"),
            "category_id": fields.get("category_id"),
        }
        if before is None
        else {**before, **fields}
    )
    row["category_name"] = names[row["category_id"]]
    return row


def _same_row(candidate, expected):
    return isinstance(candidate, dict) and all(
        key in candidate and _same_value(candidate[key], expected[key])
        for key in ROW_FIELDS
    )


def _require_row(candidate, expected):
    if not _same_row(candidate, expected):
        raise ChatError(
            "preview fields do not match the displayed after row",
            "invalid_preview",
            422,
        )


def _same_value(left, right):
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return Decimal(str(left)) == Decimal(str(right))
    return left == right


def _message(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 1000:
        raise ChatError("message is invalid", "invalid_message", 422)
    return value.strip()


def _date(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (AttributeError, ValueError):
        try:
            return parsedate_to_datetime(value).date()
        except (TypeError, ValueError, OverflowError) as error:
            raise _invalid_database() from error


def _calculations(value):
    if value == "none":
        return []
    return [value] if isinstance(value, str) else list(value)


def _format_money(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"


def _positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_id(value):
    if not _positive_integer(value):
        raise ChatError("invalid transaction ID", "invalid_preview", 422)
    return value


def _invalid_database():
    return ChatError(
        "transactions database returned an invalid response",
        "invalid_database_response",
        502,
    )


def _stale():
    return ChatError(
        "the transaction changed or no longer exists; request a new preview",
        "stale_preview",
        409,
    )
