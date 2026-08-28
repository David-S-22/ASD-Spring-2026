"""Contract tests for the transactions client: stub fixture shape, live-path normalisation, fallback."""
import re

import requests

from sophia.backend import config
from sophia.backend.clients import transactions

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_stub_rows_normalise_to_the_documented_shape(monkeypatch):
    monkeypatch.setattr(config, "TRANSACTIONS_DB_API_URL", None)
    rows, source = transactions.list_transactions()
    assert source == "stub"
    assert rows
    for row in rows:
        assert DATE_RE.match(row["date"])
        assert isinstance(row["amount"], (int, float))
        assert row["merchant"]


def test_live_path_normalises_rows_and_reports_up(monkeypatch):
    monkeypatch.setattr(config, "TRANSACTIONS_DB_API_URL", "http://transactions:6003")
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse([{"date": "2026-08-01", "merchant": "Beem", "amount": 5.99, "surprise_field": "dropped"}])

    monkeypatch.setattr(transactions.requests, "get", fake_get)
    rows, source = transactions.list_transactions(merchant="Beem", since="2026-07-01")
    assert source == "up"
    assert captured["url"] == "http://transactions:6003/transactions"
    assert captured["params"] == {"merchant": "Beem", "since": "2026-07-01"}
    assert rows == [
        {
            "date": "2026-08-01", "merchant": "Beem", "description": None,
            "amount": 5.99, "category_id": None, "ai_confidence": None,
        }
    ]


def test_live_path_falls_back_to_stub_when_service_errors(monkeypatch):
    monkeypatch.setattr(config, "TRANSACTIONS_DB_API_URL", "http://transactions:6003")

    def fake_get(url, params=None, timeout=None):
        raise requests.ConnectionError("service down")

    monkeypatch.setattr(transactions.requests, "get", fake_get)
    rows, source = transactions.list_transactions()
    assert source == "stub"
    assert rows


def test_stub_path_applies_merchant_and_since_filters(monkeypatch):
    monkeypatch.setattr(config, "TRANSACTIONS_DB_API_URL", None)
    all_rows, _source = transactions.list_transactions()

    merchant_rows, _source = transactions.list_transactions(merchant="netflix")
    assert merchant_rows
    assert all(row["merchant"] == "Netflix" for row in merchant_rows)

    since_rows, _source = transactions.list_transactions(since="2026-07-01")
    assert since_rows
    assert all(row["date"] >= "2026-07-01" for row in since_rows)
    assert len(since_rows) < len(all_rows)
