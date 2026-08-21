"""Client for the transactions service, falling back to a local stub fixture."""
import json
import os

import requests

from sophia.backend import config

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "transactions_stub.json"
)


def _normalise(row):
    """Map a transactions-service row onto the columns this app relies on.

    A single function so a differing upstream contract is a one-function change.
    """
    return {
        "date": row.get("date"),
        "merchant": row.get("merchant"),
        "description": row.get("description"),
        "amount": row.get("amount"),
        "category_id": row.get("category_id"),
        "ai_confidence": row.get("ai_confidence"),
    }


def _load_stub(merchant=None, since=None):
    with open(FIXTURE_PATH, encoding="utf-8") as handle:
        rows = json.load(handle)
    if merchant:
        rows = [r for r in rows if r.get("merchant", "").lower() == merchant.lower()]
    if since:
        rows = [r for r in rows if r.get("date", "") >= since]
    return rows


def list_transactions(merchant=None, since=None):
    """Return (rows, source) where source is "up" or "stub"."""
    if not config.TRANSACTIONS_DB_API_URL:
        return [_normalise(r) for r in _load_stub(merchant, since)], "stub"
    try:
        params = {}
        if merchant:
            params["merchant"] = merchant
        if since:
            params["since"] = since
        response = requests.get(f"{config.TRANSACTIONS_DB_API_URL}/transactions", params=params, timeout=10)
        response.raise_for_status()
        return [_normalise(r) for r in response.json()], "up"
    except requests.RequestException:
        return [_normalise(r) for r in _load_stub(merchant, since)], "stub"
