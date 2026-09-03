import re
import threading
import time

from datetime import datetime
from types import SimpleNamespace
from pytest import MonkeyPatch, fixture
from flask import Flask
from flask.testing import FlaskClient
from requests import PreparedRequest
from responses import RequestsMock

from backend.app import app
from backend.services import review_queue
from backend.services import anomalies_api
from backend.services.review_queue import transaction_queue
from backend.helpers import serialise
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

def test_check_transaction_accepts_and_queues(client: FlaskClient, monkeypatch: MonkeyPatch):
    intercept_ollama(monkeypatch, '{"is_suspicious": true, "justification": "Mock response from ollama"}')

    transaction = dto.Transaction(
        id=5,
        amount=9999999,
        merchant="Slim Shady ATMs",
        date=datetime.now(),
        description="we are going to steal your money",
        category_id=0
    )

    resp = client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()

    assert resp.status_code == 202
    assert resp.json is not None
    assert resp.json["status"] == "queued"
    assert resp.json["transaction_id"] == 5

def test_check_transaction_creates_anomaly_and_persists_it(client: FlaskClient, monkeypatch: MonkeyPatch):
    intercept_ollama(monkeypatch, '{"is_suspicious": true, "justification": "Mock response from ollama"}')

    transaction = dto.Transaction(
        id=42,
        amount=9999999,
        merchant="Slim Shady ATMs",
        date=datetime.now(),
        description="we are going to steal your money",
        category_id=0,
    )

    before = client.get("/anomalies").text.count("<tr>")
    resp = client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()

    assert resp.status_code == 202
    anomalies = client.get("/anomalies").text
    assert anomalies.count("<tr>") == before + 1
    assert "Mock response from ollama" in anomalies


def test_check_transaction_no_anomaly_persists_nothing(client: FlaskClient, monkeypatch: MonkeyPatch):
    intercept_ollama(monkeypatch, '{"is_suspicious": false, "justification": "Looks like a routine purchase."}')

    transaction = dto.Transaction(
        id=99,
        amount=42.50,
        merchant="Corner Store",
        date=datetime.now(),
        description="milk and bread",
        category_id=2,
    )

    before = client.get("/anomalies").text.count("<tr>")
    resp = client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()

    assert resp.status_code == 202
    assert client.get("/anomalies").text.count("<tr>") == before


def test_create_dummy_anomaly_increases_anomaly_list(client: FlaskClient):
    before = client.get("/anomalies").text.count("<tr>")

    client.post("/dummy-anomaly")
    client.post("/dummy-anomaly")

    assert client.get("/anomalies").text.count("<tr>") == before + 2


def test_check_transaction_retries_on_invalid_ollama_json(client: FlaskClient, monkeypatch: MonkeyPatch):
    transaction = dto.Transaction(
        id=77,
        amount=5000,
        merchant="Cash Advance",
        date=datetime.now(),
        description="retry test",
        category_id=1,
    )

    before = client.get("/anomalies").text.count("<tr>")

    intercept_ollama(monkeypatch, '{not valid json')
    first = client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()
    assert first.status_code == 202
    assert client.get("/anomalies").text.count("<tr>") == before

    intercept_ollama(monkeypatch, '{"is_suspicious": true, "justification": "Retry worked"}')
    second = client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()

    assert second.status_code == 202
    anomalies = client.get("/anomalies").text
    assert anomalies.count("<tr>") == before + 1
    assert "Retry worked" in anomalies


def test_check_transaction_invalid_model_json_persists_nothing(client: FlaskClient, monkeypatch: MonkeyPatch):
    intercept_ollama(monkeypatch, '{"is_suspicious": true}')

    transaction = dto.Transaction(
        id=88,
        amount=10,
        merchant="Nope",
        date=datetime.now(),
        description="bad json shape",
        category_id=0,
    )

    before = client.get("/anomalies").text.count("<tr>")
    resp = client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()

    assert resp.status_code == 202
    assert client.get("/anomalies").text.count("<tr>") == before


def test_check_transaction_non_bool_is_suspicious_persists_nothing(client: FlaskClient, monkeypatch: MonkeyPatch):
    intercept_ollama(monkeypatch, '{"is_suspicious": "yes", "justification": "not valid"}')

    transaction = dto.Transaction(
        id=89,
        amount=30,
        merchant="Questionable Merchant",
        date=datetime.now(),
        description="bad type",
        category_id=0,
    )

    before = client.get("/anomalies").text.count("<tr>")
    resp = client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()

    assert resp.status_code == 202
    assert client.get("/anomalies").text.count("<tr>") == before


def test_check_transaction_persists_exact_anomaly_fields(client: FlaskClient, monkeypatch: MonkeyPatch):
    intercept_ollama(monkeypatch, '{"is_suspicious": true, "justification": "Persisted reason"}')

    transaction = dto.Transaction(
        id=90,
        amount=123456,
        merchant="Large Round Transfer",
        date=datetime.now(),
        description="persist fields",
        category_id=9,
    )

    client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()
    resp = client.get("/anomalies")

    assert resp.status_code == 200
    assert "Persisted reason" in resp.text
    assert "<td>90</td>" in resp.text


def test_check_transaction_rejects_invalid_payload(client: FlaskClient):
    resp = client.post("/check-transaction", json={"merchant": "Nope"})

    assert resp.status_code == 500
    assert "Schema mismatch between backend and database" in resp.text


def test_anomaly_alert_returns_alert_when_anomaly_created(client: FlaskClient, monkeypatch: MonkeyPatch):
    intercept_ollama(monkeypatch, '{"is_suspicious": true, "justification": "Long poll reason"}')

    transaction = dto.Transaction(
        id=123,
        amount=9999999,
        merchant="Slim Shady ATMs",
        date=datetime.now(),
        description="we are going to steal your money",
        category_id=0,
    )

    client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()

    resp = client.get("/anomaly-alert?key=123")

    assert resp.status_code == 200
    assert "<strong>Possible suspicious transaction detected</strong>" in resp.text
    assert "Long poll reason" in resp.text


def test_anomaly_alert_returns_204_when_no_anomaly(client: FlaskClient, monkeypatch: MonkeyPatch):
    intercept_ollama(monkeypatch, '{"is_suspicious": false, "justification": "Looks fine."}')

    transaction = dto.Transaction(
        id=124,
        amount=42.50,
        merchant="Corner Store",
        date=datetime.now(),
        description="milk and bread",
        category_id=2,
    )

    client.post("/check-transaction", json=serialise(transaction))
    transaction_queue.join()

    resp = client.get("/anomaly-alert?key=124")

    assert resp.status_code == 204
    assert resp.data == b""


def test_anomaly_alert_times_out_while_pending(client: FlaskClient, monkeypatch: MonkeyPatch):
    monkeypatch.setattr("backend.app.ANOMALY_WAIT_SECONDS", 0.2)

    resp = client.get("/anomaly-alert?key=999")

    assert resp.status_code == 204
    assert resp.data == b""


def test_anomaly_alert_waits_when_polled_before_enqueue(monkeypatch: MonkeyPatch):
    # Regression: a client that polls for a result *before* the transaction has
    # been enqueued must block until the review completes, rather than treating
    # "not yet pending" as "already reviewed" and returning immediately.
    review_queue.reset()

    sentinel = dto.Anomaly(
        id=1, transaction_id=556, agent_reason_suspected="Raced ahead", is_confirmed_by_user=None)
    monkeypatch.setattr(
        review_queue, "_find_anomaly", lambda key: sentinel if key == 556 else None)

    result = {}

    def poll():
        with app.app_context():
            result["val"] = review_queue.wait_for_result(556, timeout=5)

    poller = threading.Thread(target=poll)
    poller.start()

    # The item is not enqueued yet, so the poll must still be blocking here.
    time.sleep(0.3)
    assert poller.is_alive()
    assert "val" not in result

    # Simulate the transaction being enqueued and then finishing review.
    review_queue._mark_reviewed(556)

    poller.join(timeout=5)
    assert not poller.is_alive()
    assert result["val"] is sentinel


def test_anomaly_alert_requires_key(client: FlaskClient):
    resp = client.get("/anomaly-alert")

    assert resp.status_code == 400


def test_get_anomaly_by_transaction_id_returns_created_anomaly(client: FlaskClient):
    with app.app_context():
        created = anomalies_api.create_anomaly(
            dto.Anomaly(id=0, transaction_id=911, agent_reason_suspected="beans", is_confirmed_by_user=False))

        found = anomalies_api.get_anomaly_by_transaction_id(911)

    assert found is not None
    assert found.id == created.id
    assert found.transaction_id == 911
    assert found.agent_reason_suspected == "beans"


def test_get_anomaly_by_transaction_id_returns_none_when_missing(client: FlaskClient):
    with app.app_context():
        assert anomalies_api.get_anomaly_by_transaction_id(999999) is None


def test_find_anomaly_uses_transaction_lookup(client: FlaskClient):
    with app.app_context():
        created = anomalies_api.create_anomaly(
            dto.Anomaly(id=0, transaction_id=912, agent_reason_suspected="beans", is_confirmed_by_user=False))

        found = review_queue._find_anomaly(912)
        missing = review_queue._find_anomaly(888888)

    assert found is not None
    assert found.id == created.id
    assert missing is None



def test_confirm_anomaly_sets_status(client: FlaskClient):
    with app.app_context():
        created = anomalies_api.create_anomaly(
            dto.Anomaly(id=0, transaction_id=2001, agent_reason_suspected="review me", is_confirmed_by_user=None))

    resp = client.post(f"/anomalies/{created.id}/confirm")

    assert resp.status_code == 200
    assert "Confirmed" in resp.text

    with app.app_context():
        assert anomalies_api.get_anomaly_by_transaction_id(2001).is_confirmed_by_user is True


def test_dismiss_anomaly_sets_status(client: FlaskClient):
    with app.app_context():
        created = anomalies_api.create_anomaly(
            dto.Anomaly(id=0, transaction_id=2002, agent_reason_suspected="review me", is_confirmed_by_user=None))

    resp = client.post(f"/anomalies/{created.id}/dismiss")

    assert resp.status_code == 200
    assert "Dismissed" in resp.text

    with app.app_context():
        assert anomalies_api.get_anomaly_by_transaction_id(2002).is_confirmed_by_user is False


def test_review_button_only_renders_when_unreviewed(client: FlaskClient):
    with app.app_context():
        unreviewed = anomalies_api.create_anomaly(
            dto.Anomaly(id=0, transaction_id=2003, agent_reason_suspected="pending", is_confirmed_by_user=None))

    rows = client.get("/anomalies").text
    assert f'openReviewModal({unreviewed.id})' in rows

    client.post(f"/anomalies/{unreviewed.id}/confirm")

    rows = client.get("/anomalies").text
    assert f'openReviewModal({unreviewed.id})' not in rows


def test_confirm_missing_anomaly_returns_404(client: FlaskClient):
    resp = client.post("/anomalies/999999/confirm")

    assert resp.status_code == 404


# Pytest fixtures
@fixture
def client():
    setup_database(":memory:")
    review_queue.reset()

    with app.test_client() as client:
        yield client

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

    dburl = re.compile(r"^http://mock-database-url/anomalies(/.*)?$")
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

def intercept_ollama(monkeypatch: MonkeyPatch, model_response: str):
    create=lambda **kwargs: SimpleNamespace(output_text=model_response)
    responses=SimpleNamespace(create=create)
    fake_client = SimpleNamespace(responses=responses)

    # Monkeypatch ollama api
    monkeypatch.setattr("backend.services.ollama_api._get_client", lambda: fake_client)
