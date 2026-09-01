import re

from datetime import datetime
from types import SimpleNamespace
from pytest import MonkeyPatch, fixture
from flask import Flask
from flask.testing import FlaskClient
from requests import PreparedRequest
from responses import RequestsMock

from backend.app import app
from database.app import app as dbapp, setup_database
from janelle.database.app import setup_app as setup_transactions
from shared.backend import dto


# Tests
def test_index(client: FlaskClient):
    resp = client.get("/")

    assert resp.status_code == 200
    assert isinstance(resp.json, dict)
    assert resp.json["container"] == "anomalies-backend"

def test_create_anomaly(client: FlaskClient):
    resp = client.post("/dummy-anomaly")
    assert resp.text.count("<tr>") == 1

    resp = client.post("/dummy-anomaly")
    assert resp.text.count("<tr>") == 2

    resp = client.post("/dummy-anomaly")
    assert resp.text.count("<tr>") == 3

def test_check_transaction_html(client: FlaskClient):
    transaction = dto.Transaction(
        id=5,
        amount=9999999,
        merchant="Slim Shady ATMs",
        date=datetime.now(),
        description="we are going to steal your money",
        category_id=0
    )

    resp = client.post("check-transaction", json=transaction)
    assert resp.status_code == 200
    assert "<strong>Possible suspicious transaction detected</strong>" in resp.text
    assert "<p>Mock response from ollama</p>" in resp.text
    assert "<small>Head to the Anomalies tab to check it out</small>" in resp.text

def test_check_transaction_creates_anomaly(client: Flask):
    ...


# Pytest fixtures
@fixture
def client():
    setup_database(":memory:")

    with app.test_client() as client:
        yield client

@fixture(autouse=True)
def mock_ollama_api(monkeypatch: MonkeyPatch):
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                output_text='{"is_suspicious": true, "justification": "Mock response from ollama"}'
            )
        )
    )

    # Monkeypatch ollama api
    monkeypatch.setattr("backend.services.ollama_api._get_client", lambda: fake_client)

@fixture(autouse=True)
def integrate_services(monkeypatch: MonkeyPatch):
    # In order to get the backend client to send requests
    # to the actual database server, we have to intercept
    # the requests via responses and redirect them to the
    # test_client instance. Same with the transactions db

    transactionsapp = setup_transactions()

    monkeypatch.setenv("ANOMALIES_DB_URL", "http://mock-database-url/anomalies")
    monkeypatch.setenv("TRANSACTIONS_DB_URL", "http://mock-transactions-url")
    monkeypatch.setenv("OLLAMA_MODEL", "billy")
    monkeypatch.setenv("OLLAMA_URL", "http://mock-ollama-url")

    dburl = re.compile(r"^http://mock-database-url/anomalies/?$")
    transactionsurl = re.compile(r"^http://mock-transactions-url/.+$")

    with RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(RequestsMock.GET, dburl, lambda r: intercept(dbapp, r))
        rsps.add_callback(RequestsMock.POST, dburl, lambda r: intercept(dbapp, r))
        rsps.add_callback(RequestsMock.PATCH, dburl, lambda r: intercept(dbapp, r))
        rsps.add_callback(RequestsMock.DELETE, dburl, lambda r: intercept(dbapp, r))
        rsps.add_callback(RequestsMock.OPTIONS, dburl, lambda r: intercept(dbapp, r))

        rsps.add_callback(RequestsMock.GET, transactionsurl, lambda r: intercept(transactionsapp, r))
        rsps.add_callback(RequestsMock.OPTIONS, transactionsurl, lambda r: intercept(transactionsapp, r))

        yield

def intercept(app_to_inject: Flask, request: PreparedRequest):
    with app_to_inject.test_client() as client:
        resp = client.open(
            path=request.path_url,
            method=request.method,
            headers=dict(request.headers),
            data=request.body)

        return resp.status_code, dict(resp.headers), resp.get_data()
