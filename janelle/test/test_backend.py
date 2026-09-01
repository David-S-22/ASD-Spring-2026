from unittest.mock import Mock

import requests
from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark

import janelle.backend.app as backend_app
import janelle.backend.services.transactions_api as transactions_api


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
            "date": "Mon, 31 Aug 2026 14:30:00 GMT",
            "merchant": "<script>alert('xss')</script>",
            "description": "Lunch",
            "amount": 18.5,
            "category_id": 80,
        }
    ])
    category_response = response_with_json([
        {
            "id": 80,
            "name": "Dining",
            "type": "want",
        }
    ])
    get = Mock(side_effect=[database_response, category_response])
    monkeypatch.setattr(transactions_api.requests, "get", get)

    response = client.get("/ui/transactions")

    assert response.status_code == 200
    assert "<td>1</td>" not in response.text
    assert "<td>Mon, 31 Aug 2026</td>" in response.text
    assert "14:30:00 GMT" not in response.text
    assert "<td>18.50</td>" in response.text
    assert "Lunch" in response.text
    assert "Dining" in response.text
    assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in response.text
    assert get.call_args_list == [
        ((f"{transactions_api.config.TRANSACTIONS_DB_URL}/transactions",), {"timeout": 20}),
        ((f"{transactions_api.config.TRANSACTIONS_DB_URL}/categories",), {"timeout": 20}),
    ]


def test_transaction_rows_show_empty_state(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        transactions_api.requests,
        "get",
        Mock(side_effect=[response_with_json([]), response_with_json([])]),
    )

    response = client.get("/ui/transactions")

    assert response.status_code == 200
    assert "No transactions found." in response.text


def test_transaction_rows_report_database_failure(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        transactions_api.requests,
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
        transactions_api.requests,
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
        transactions_api.requests,
        "get",
        Mock(return_value=response_with_json(payload)),
    )

    response = client.get("/ui/transactions")

    assert response.status_code == 502
    assert "database response was invalid" in response.text
