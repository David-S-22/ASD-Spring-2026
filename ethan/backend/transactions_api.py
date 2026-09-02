from __future__ import annotations

from datetime import date

import requests

from . import config
from .db_api import ServiceError


def _url(path: str) -> str:
    return f"{config.TRANSACTIONS_API_URL}{path}"


def _service_unavailable(message: str = "transactions API is unavailable") -> ServiceError:
    return ServiceError(message, 503, "transactions_unavailable")


def _raise_for_status(response: requests.Response) -> requests.Response:
    if 400 <= response.status_code < 500:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        raise ServiceError(
            payload.get("error", response.text or f"transactions API returned {response.status_code}"),
            response.status_code,
            payload.get("code"),
        )
    response.raise_for_status()
    return response


def _json(response: requests.Response):
    try:
        _raise_for_status(response)
    except ServiceError:
        raise
    except requests.RequestException as error:
        raise _service_unavailable() from error
    try:
        return response.json()
    except (ValueError, RecursionError) as error:
        raise ServiceError(
            "transactions API returned invalid JSON",
            502,
            "invalid_transactions_response",
        ) from error


def list_transactions(params: dict | None = None):
    try:
        response = requests.get(
            _url("/transactions"),
            params=params,
            timeout=config.TRANSACTIONS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise _service_unavailable() from error
    data = _json(response)
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ServiceError(
            "transactions API returned invalid transaction data",
            502,
            "invalid_transactions_response",
        )
    return data


def list_transactions_for_month(month: str):
    start = date.fromisoformat(f"{month}-01")
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    end = next_month.fromordinal(next_month.toordinal() - 1)
    return list_transactions({"date_from": start.isoformat(), "date_to": end.isoformat()})


def list_categories():
    try:
        response = requests.get(
            _url("/categories"),
            timeout=config.TRANSACTIONS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise _service_unavailable() from error
    data = _json(response)
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ServiceError(
            "transactions API returned invalid category data",
            502,
            "invalid_transactions_response",
        )
    return data
