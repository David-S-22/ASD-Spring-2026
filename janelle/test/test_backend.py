from unittest.mock import Mock

import requests
from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark

import janelle.backend.app as backend_app


@fixture
def client():
    with backend_app.app.test_client() as test_client:
        yield test_client


def response_with_json(payload):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def test_index_identifies_backend(client: FlaskClient):
    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {"container": "transactions-backend"}


def test_transaction_rows_are_loaded_from_database(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    database_response = response_with_json([
        {
            "id": 1,
            "date": "2026-08-31",
            "merchant": "<script>alert('xss')</script>",
            "description": "Lunch",
            "amount": 18.5,
            "category_name": "Dining",
        }
    ])
    get = Mock(return_value=database_response)
    monkeypatch.setattr(backend_app.requests, "get", get)

    response = client.get("/ui/transactions")

    assert response.status_code == 200
    assert "2026-08-31" in response.text
    assert "Lunch" in response.text
    assert "Dining" in response.text
    assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in response.text
    get.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions",
        timeout=20,
    )


def test_transaction_rows_show_empty_state(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(return_value=response_with_json([])),
    )

    response = client.get("/ui/transactions")

    assert response.status_code == 200
    assert "No transactions found." in response.text


def test_transaction_rows_report_database_failure(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=requests.ConnectionError("database unavailable")),
    )

    response = client.get("/ui/transactions")

    assert response.status_code == 502
    assert "database service is unavailable" in response.text


def test_transaction_rows_reject_invalid_json(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    database_response = response_with_json([])
    database_response.json.side_effect = requests.exceptions.JSONDecodeError(
        "invalid JSON",
        "",
        0,
    )
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(return_value=database_response),
    )

    response = client.get("/ui/transactions")

    assert response.status_code == 502
    assert "database response was invalid" in response.text


@mark.parametrize("payload", [{}, ["not a transaction"], [None]])
def test_transaction_rows_reject_invalid_shape(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    payload,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(return_value=response_with_json(payload)),
    )

    response = client.get("/ui/transactions")

    assert response.status_code == 502
    assert "database response was invalid" in response.text
