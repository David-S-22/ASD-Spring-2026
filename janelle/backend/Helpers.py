"""Shared helpers for the Transactions Flask application."""

from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from flask import jsonify, render_template, request
from werkzeug.exceptions import BadRequest

from . import config
from .services.chat_service import ChatError


def align_transactions_with_corresponding_category_names(
    transactions,
    categories,
):
    category_names = {
        category["id"]: category["name"]
        for category in categories
        if isinstance(category.get("id"), int)
        and isinstance(category.get("name"), str)
    }
    return [
        {
            **transaction,
            "category_name": category_names.get(
                transaction.get("category_id")
            ),
        }
        for transaction in transactions
    ]


def format_transaction_date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            return str(value)
    return parsed.strftime("%d %b %Y").lstrip("0")


def format_currency(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def get_form_categories(db_url):
    response = requests.get(
        f"{db_url}/categories",
        timeout=config.DATABASE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    categories = response.json()
    if (
        not isinstance(categories, list)
        or not all(isinstance(category, dict) for category in categories)
    ):
        raise ValueError("invalid categories response")
    return categories


def render_transaction_form(db_url, error=None, values=None):
    values = values or {
        "date": datetime.now().date().isoformat(),
        "amount": "",
        "merchant": "",
        "description": "",
        "category_id": "",
    }
    try:
        categories = get_form_categories(db_url)
    except (requests.RequestException, ValueError, RecursionError):
        categories = []
        error = error or (
            "Categories are unavailable. Return to transactions and try again."
        )
    return render_template(
        "transaction_form.jinja",
        categories=categories,
        error=error,
        values=values,
    )


def render_transaction_table(transactions, error=None):
    TRANSACTION_PAGE_SIZES = (5, 10, 15, 20)
    DEFAULT_TRANSACTION_PAGE_SIZE = TRANSACTION_PAGE_SIZES[0]
    requested_page_size = request.args.get("page_size", type=int)
    page_size = (
        requested_page_size
        if requested_page_size in TRANSACTION_PAGE_SIZES
        else DEFAULT_TRANSACTION_PAGE_SIZE
    )
    requested_page = request.args.get("page", default=1, type=int)
    page = max(requested_page or 1, 1)
    total_transactions = len(transactions)
    total_pages = max(
        1,
        (total_transactions + page_size - 1) // page_size,
    )
    page = min(page, total_pages)
    first_index = (page - 1) * page_size
    last_index = min(first_index + page_size, total_transactions)

    return render_template(
        "transactions_table.jinja",
        transactions=transactions[first_index:last_index],
        error=error,
        page=page,
        page_size=page_size,
        page_sizes=TRANSACTION_PAGE_SIZES,
        total_pages=total_pages,
        total_transactions=total_transactions,
        first_transaction=first_index + 1 if total_transactions else 0,
        last_transaction=last_index,
        has_previous=page > 1,
        has_next=page < total_pages,
    )


def json_response(response):
    if response.status_code == 204:
        return "", 204
    try:
        payload = response.json()
    except (ValueError, RecursionError):
        return jsonify({
            "error": "transactions database returned invalid JSON",
            "code": "invalid_database_response",
        }), 502
    return jsonify(payload), response.status_code


def json_object():
    if not request.is_json:
        raise ChatError(
            "request body must be a JSON object",
            "invalid_json",
            400,
        )
    try:
        payload = request.get_json()
    except (BadRequest, RecursionError) as error:
        raise ChatError(
            "request body contains invalid JSON",
            "invalid_json",
            400,
        ) from error
    if not isinstance(payload, dict):
        raise ChatError(
            "request body must be a JSON object",
            "invalid_json",
            400,
        )
    return payload
