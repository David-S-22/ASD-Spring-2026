"""AI chat orchestration for transactions."""

import base64
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.utils import parsedate_to_datetime

import requests

from .. import config
from . import ollama_service


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
    from .transaction_orchestrator import orchestrate_transaction_request

    return orchestrate_transaction_request(message, db_url)


def apply_preview(payload, db_url):
    preview = payload.get("preview") if "preview" in payload else payload
    return execute_confirmed_write(preview, db_url)


def execute_confirmed_write(
    preview,
    db_url,
    *,
    allow_suggested_category=False,
):
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

    _categories_list, names, ids = build_category_lookup(
        database_request("get", f"{db_url}/categories", list)
    )
    if operation == "create":
        clean = validate_write_fields(fields, names, ids, create=True)
        expected = build_after_row(None, clean, names)
        if preview.get("transaction_id") is not None or preview.get("before") is not None:
            raise ChatError("invalid create preview", "invalid_preview", 422)
        require_matching_row(preview.get("after"), expected)
        payload = dict(clean)
        suggested_category_id = preview.get("suggested_category_id")
        if suggested_category_id is not None:
            if not allow_suggested_category:
                raise ChatError(
                    "suggested category metadata is not trusted",
                    "invalid_preview",
                    422,
                )
            if (
                not is_positive_integer(suggested_category_id)
                or suggested_category_id not in names
                or suggested_category_id == clean["category_id"]
            ):
                raise ChatError(
                    "suggested category metadata is invalid",
                    "invalid_preview",
                    422,
                )
            payload["suggested_category_id"] = suggested_category_id
        try:
            transaction = database_request(
                "post",
                f"{db_url}/transactions",
                dict,
                json=payload,
            )
        except ChatError as error:
            if error.status < 500:
                raise
            return unverified_write_result(operation, error)
        try:
            observed = transaction_row(transaction, names)
        except ChatError as error:
            return unverified_write_result(
                operation,
                error,
                transaction=transaction,
            )
        if not verify_write(operation, expected, observed):
            return unverified_write_result(
                operation,
                write_verification_error(),
                transaction=transaction,
            )
        return {
            "operation": operation,
            "transaction": transaction,
            "verified": True,
        }

    transaction_id = require_positive_id(preview.get("transaction_id"))
    try:
        current = transaction_row(
            database_request(
                "get",
                f"{db_url}/transactions/{transaction_id}",
                dict,
                params={"_include_version": "true"},
            ),
            names,
            require_version=True,
        )
    except ChatError as error:
        if error.code == "transaction_not_found":
            raise stale_preview_error() from error
        raise
    if not rows_match(preview.get("before"), current):
        raise stale_preview_error()

    if operation == "delete":
        if fields or preview.get("after") is not None:
            raise ChatError("invalid delete preview", "invalid_preview", 422)
        precondition = expected_transaction_header(current)
        try:
            database_request(
                "delete",
                f"{db_url}/transactions/{transaction_id}",
                headers={"X-Expected-Transaction": precondition},
            )
        except ChatError as error:
            if error.status < 500:
                raise
            return unverified_write_result(
                operation,
                error,
                deleted=current,
            )
        try:
            database_request(
                "get",
                f"{db_url}/transactions/{transaction_id}",
                dict,
            )
        except ChatError as error:
            if error.code != "transaction_not_found":
                return unverified_write_result(
                    operation,
                    error,
                    deleted=current,
                )
        else:
            return unverified_write_result(
                operation,
                write_verification_error(),
                deleted=current,
            )
        return {
            "operation": operation,
            "deleted": current,
            "verified": True,
        }

    clean = validate_write_fields(fields, names, ids)
    if not clean:
        raise ChatError("update fields are required", "invalid_preview", 422)
    require_matching_row(
        preview.get("after"),
        build_after_row(current, clean, names),
    )
    expected = build_after_row(current, clean, names)
    precondition = expected_transaction_header(current)
    try:
        transaction = database_request(
            "patch",
            f"{db_url}/transactions/{transaction_id}",
            dict,
            json=clean,
            headers={"X-Expected-Transaction": precondition},
        )
    except ChatError as error:
        if error.status < 500:
            raise
        return unverified_write_result(
            operation,
            error,
            transaction=current,
        )
    try:
        observed = transaction_row(transaction, names)
    except ChatError as error:
        return unverified_write_result(
            operation,
            error,
            transaction=transaction,
        )
    if not verify_write(operation, expected, observed):
        return unverified_write_result(
            operation,
            write_verification_error(),
            transaction=transaction,
        )
    return {
        "operation": operation,
        "transaction": transaction,
        "verified": True,
    }


def execute_read_plan(plan, db_url, context):
    return build_read_response(
        plan,
        db_url,
        context["category_names"],
        context["category_ids"],
        context.get("available_transactions", []),
    )


def execute_write_preview(plan, db_url, context):
    return build_write_preview(
        plan,
        db_url,
        context["category_names"],
        context["category_ids"],
        context.get("available_transactions", []),
    )


def build_read_response(result, db_url, names, ids, available_transactions):
    filters = resolve_search_filters(
        validate_filters(result["filters"], names, ids),
        available_transactions,
    )
    if result["transaction_id"] is not None:
        if filters:
            raw_rows = [
                item
                for item in query_transactions(db_url, filters)
                if item.get("id") == result["transaction_id"]
            ]
        else:
            try:
                raw_rows = [database_request(
                    "get",
                    f"{db_url}/transactions/{result['transaction_id']}",
                    dict,
                )]
            except ChatError as error:
                if error.code != "transaction_not_found":
                    raise
                raw_rows = []
    else:
        raw_rows = query_transactions(db_url, filters)

    transactions = [transaction_row(item, names) for item in raw_rows]
    calculations = normalize_calculations(result["calculation"])
    metrics = calculate_analytics(transactions)
    if "largest" in calculations:
        transactions = sorted(
            transactions,
            key=lambda transaction: transaction["amount"],
            reverse=True,
        )[:5]
    return {
        **build_base_response(result),
        "filters": filters,
        "analytics": {**metrics, "calculations": calculations},
        "transactions": transactions,
        "reply": build_analytics_reply(metrics, calculations, filters),
    }


def build_write_preview(result, db_url, names, ids, available_transactions):
    operation = result["operation"]
    if operation == "create":
        fields = validate_write_fields(
            result["fields"],
            names,
            ids,
            create=True,
        )
        return build_preview_response(result, {
            "operation": operation,
            "transaction_id": None,
            "fields": fields,
            "before": None,
            "after": build_after_row(None, fields, names),
            "changes": {
                key: {"before": None, "after": value}
                for key, value in fields.items()
            },
        })

    matches = find_matching_transactions(
        result,
        db_url,
        names,
        ids,
        available_transactions,
    )
    if len(matches) != 1:
        return build_clarification_response(operation, matches)

    before = matches[0]
    if operation == "delete":
        return build_preview_response(result, {
            "operation": operation,
            "transaction_id": before["id"],
            "fields": {},
            "before": before,
            "after": None,
            "changes": {},
        })

    requested = validate_write_fields(result["fields"], names, ids)
    changed = {
        key: value
        for key, value in requested.items()
        if not values_match(before.get(key), value)
    }
    if not changed:
        return {
            **build_base_response(result),
            "reply": "The matching transaction already has those values.",
        }
    return build_preview_response(result, {
        "operation": operation,
        "transaction_id": before["id"],
        "fields": changed,
        "before": before,
        "after": build_after_row(before, changed, names),
        "changes": {
            key: {"before": before.get(key), "after": value}
            for key, value in changed.items()
        },
    })


def find_matching_transactions(
    result,
    db_url,
    names,
    ids,
    available_transactions,
):
    transaction_id = result["transaction_id"]
    if transaction_id is not None:
        filters = resolve_search_filters(
            validate_filters(result["filters"], names, ids),
            available_transactions,
        )
        if filters:
            return [
                transaction_row(item, names, require_version=True)
                for item in query_transactions(
                    db_url,
                    filters,
                    include_version=True,
                )
                if item.get("id") == transaction_id
            ]
        try:
            item = database_request(
                "get",
                f"{db_url}/transactions/{transaction_id}",
                dict,
                params={"_include_version": "true"},
            )
        except ChatError as error:
            if error.code == "transaction_not_found":
                return []
            raise
        return [transaction_row(item, names, require_version=True)]

    filters = resolve_search_filters(
        validate_filters(result["filters"], names, ids),
        available_transactions,
    )
    if not filters:
        return []
    return [
        transaction_row(item, names, require_version=True)
        for item in query_transactions(
            db_url,
            filters,
            include_version=True,
        )
    ]


def query_transactions(db_url, filters, include_version=False):
    dates = filters.get("dates")
    if dates is None:
        params = dict(filters)
        if include_version:
            params["_include_version"] = "true"
        options = {"params": params} if params else {}
        return database_request(
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
        for item in database_request(
            "get",
            f"{db_url}/transactions",
            list,
            params=date_filters,
        ):
            try:
                rows[item["id"]] = item
            except (KeyError, TypeError) as error:
                raise invalid_database_error() from error
    try:
        return sorted(
            rows.values(),
            key=lambda item: (
                parse_transaction_date(item["date"]),
                item["id"],
            ),
            reverse=True,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise invalid_database_error() from error


def database_request(method, url, expected=None, **options):
    try:
        response = getattr(requests, method)(
            url,
            timeout=config.DATABASE_TIMEOUT_SECONDS,
            **options,
        )
    except requests.RequestException as error:
        raise ChatError(
            "transactions database is unavailable",
            "database_unavailable",
            503,
        ) from error
    if response.status_code == 204:
        if expected is None:
            return None
        raise invalid_database_error()
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
        raise invalid_database_error() from error
    if expected is not None and (
        not isinstance(data, expected)
        or (
            expected is list
            and not all(isinstance(item, dict) for item in data)
        )
    ):
        raise invalid_database_error()
    return data


def build_category_lookup(rows):
    categories = []
    names = {}
    ids = {}
    for item in rows:
        category_id = item.get("id")
        name = item.get("name")
        if not is_positive_integer(category_id) or not isinstance(name, str):
            raise invalid_database_error()
        category = {"id": category_id, "name": name, "type": item.get("type")}
        categories.append(category)
        names[category_id] = name
        ids[name.casefold()] = category_id
    return categories, names, ids


def transaction_row(item, names, *, require_version=False):
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
        version = item.get("version")
        if require_version:
            if not isinstance(version, str) or not version:
                raise invalid_database_error()
            row["version"] = version
        elif version is not None:
            if not isinstance(version, str):
                raise invalid_database_error()
            row["version"] = version
    except (KeyError, TypeError, ValueError) as error:
        raise invalid_database_error() from error
    if not is_positive_integer(transaction_id):
        raise invalid_database_error()
    return row


def validate_write_fields(
    fields,
    names,
    ids,
    create=False,
    require_category=True,
):
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
        if "amount" in clean and not values_match(clean["amount"], cents_amount):
            raise ChatError(
                "amount and amount_cents do not match",
                "invalid_amount",
                422,
            )
        clean["amount"] = cents_amount

    category_id = fields.get("category_id")
    category_name = fields.get("category")
    if category_id is not None or category_name is not None:
        clean["category_id"] = resolve_category_id(
            category_id,
            category_name,
            names,
            ids,
        )
    if create:
        missing = [
            key
            for key in ("date", "merchant", "description", "amount")
            if key not in clean
        ]
        if require_category and "category_id" not in clean:
            missing.append("category_id")
        if missing:
            raise ChatError(
                f"missing required fields: {', '.join(missing)}",
                "missing_fields",
                422,
                missing_fields=missing,
            )
    return clean


def validate_filters(filters, names, ids):
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
        clean["category_id"] = resolve_category_id(
            filters.get("category_id"),
            filters.get("category"),
            names,
            ids,
        )
    return clean


def resolve_search_filters(filters, transactions):
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


def resolve_category_id(
    category_id,
    category_name,
    names,
    ids,
):
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
    raise ChatError("category is required", "category_required", 422)


def calculate_analytics(transactions):
    try:
        cents = [int(Decimal(str(item["amount"])) * 100) for item in transactions]
    except (InvalidOperation, ValueError) as error:
        raise invalid_database_error() from error
    total = sum(cents)
    count = len(cents)
    average = (
        (Decimal(total) / count / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if count
        else None
    )
    dates = sorted(
        parse_transaction_date(item["date"])
        for item in transactions
    )
    return {
        "count": count,
        "sum": float(Decimal(total) / 100),
        "sum_cents": total,
        "average": float(average) if average is not None else None,
        "average_cents": int(average * 100) if average is not None else None,
        "date_from": dates[0].isoformat() if dates else None,
        "date_to": dates[-1].isoformat() if dates else None,
    }


def build_analytics_reply(metrics, calculations, filters):
    count = metrics["count"]
    if not count:
        period = analytics_period(metrics, filters)
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
        parts.append(f"a total of {format_money(metrics['sum_cents'])}")
    if "average" in calculations:
        parts.append(
            f"an average spend of {format_money(metrics['average_cents'])}"
        )
    detail = (
        "I calculated " + ", and ".join(parts)
        if parts
        else f"I found {count} matching transaction{'s' if count != 1 else ''}"
    )
    return f"{detail}{analytics_period(metrics, filters)}."


def analytics_period(metrics, filters):
    dates = filters.get("dates")
    if dates:
        labels = [date_label(value) for value in dates]
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
        if (
            parse_transaction_date(date_from)
            == parse_transaction_date(date_to)
        ):
            return f" on {date_label(date_from)}"
        return f" from {date_label(date_from)} to {date_label(date_to)}"
    if date_from:
        return f" since {date_label(date_from)}"
    if date_to:
        return f" up to {date_label(date_to)}"
    return ""


def date_label(value):
    parsed = parse_transaction_date(value)
    return f"{parsed.day} {parsed:%b %Y}"


def build_base_response(result, operation=None, fallback=False):
    return {
        "reply": result["reply"],
        "operation": result["operation"] if operation is None and not fallback else operation,
        "handoff": "none",
        "requires_confirmation": False,
        "requires_clarification": False,
        "preview": None,
        "fallback": fallback,
    }


def build_preview_response(result, preview):
    return {
        **build_base_response(result),
        "requires_confirmation": True,
        "preview": preview,
    }


def build_clarification_response(operation, matches):
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


def build_after_row(before, fields, names):
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


def rows_match(candidate, expected):
    return (
        isinstance(candidate, dict)
        and all(
            key in candidate
            and values_match(candidate[key], expected[key])
            for key in ROW_FIELDS
        )
        and (
            "version" not in expected
            or candidate.get("version") == expected["version"]
        )
    )


def require_matching_row(candidate, expected):
    if not rows_match(candidate, expected):
        raise ChatError(
            "preview fields do not match the displayed after row",
            "invalid_preview",
            422,
        )


def values_match(left, right):
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return Decimal(str(left)) == Decimal(str(right))
    return left == right


def verify_write(operation, expected, actual):
    if operation == "delete":
        return actual is None
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False
    for key in ROW_FIELDS:
        if key == "id" and expected.get(key) is None:
            continue
        if key not in expected or key not in actual:
            return False
        if key == "date":
            try:
                if parse_transaction_date(expected[key]) != parse_transaction_date(
                    actual[key]
                ):
                    return False
            except ChatError:
                return False
        elif not values_match(expected[key], actual[key]):
            return False
    return True


def unverified_write_result(
    operation,
    error,
    *,
    transaction=None,
    deleted=None,
):
    result = {
        "operation": operation,
        "verified": False,
        "write_outcome_unknown": True,
        "verification_error": {
            "message": error.message,
            "code": error.code,
        },
    }
    if transaction is not None:
        result["transaction"] = transaction
    if deleted is not None:
        result["deleted"] = deleted
    return result


def expected_transaction_header(transaction):
    payload = {
        "id": transaction["id"],
        "version": transaction.get("version"),
    }
    if not isinstance(payload["version"], str) or not payload["version"]:
        raise invalid_database_error()
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii")


def validate_message(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 1000:
        raise ChatError("message is invalid", "invalid_message", 422)
    return value.strip()


def parse_transaction_date(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (AttributeError, ValueError):
        try:
            return parsedate_to_datetime(value).date()
        except (TypeError, ValueError, OverflowError) as error:
            raise invalid_database_error() from error


def normalize_calculations(value):
    if value == "none":
        return []
    return [value] if isinstance(value, str) else list(value)


def format_money(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"


def is_positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def require_positive_id(value):
    if not is_positive_integer(value):
        raise ChatError("invalid transaction ID", "invalid_preview", 422)
    return value


def invalid_database_error():
    return ChatError(
        "transactions database returned an invalid response",
        "invalid_database_response",
        502,
    )


def stale_preview_error():
    return ChatError(
        "the transaction changed or no longer exists; request a new preview",
        "stale_preview",
        409,
    )


def write_verification_error():
    return ChatError(
        "the transaction write could not be verified",
        "write_verification_failed",
        502,
    )
