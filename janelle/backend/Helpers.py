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
