from datetime import date, timedelta
from unittest.mock import Mock

import requests
from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark

import janelle.backend.app as backend_app


TRANSACTION = {
    "id": 42,
    "date": "Mon, 31 Aug 2026 00:00:00 GMT",
    "merchant": "Merivale",
    "description": "Dinner",
    "amount": 84.5,
    "category_id": 80,
}


@fixture
def client():
    with backend_app.app.test_client() as test_client:
        yield test_client


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
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
    monkeypatch.setattr(backend_app.requests, "get", get)

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
        (
            (
                f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions",
            ),
            {"timeout": 20},
        ),
        (
            (
                f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
            ),
            {"timeout": 20},
        ),
    ]


@mark.parametrize("page_size", [5, 10, 15, 20])
def test_transaction_rows_support_allowed_page_sizes(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    page_size,
):
    transactions = [
        {
            "id": transaction_id,
            "date": "Mon, 31 Aug 2026 14:30:00 GMT",
            "merchant": f"Merchant {transaction_id}",
            "description": "Purchase",
            "amount": transaction_id,
            "category_id": 80,
        }
        for transaction_id in range(1, 22)
    ]
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(transactions),
            response_with_json([]),
        ]),
    )

    response = client.get(f"/ui/transactions?page_size={page_size}")

    assert response.status_code == 200
    assert response.text.count("<td>Merchant ") == page_size
    assert f'<option value="{page_size}" selected>' in response.text


def test_transaction_rows_can_move_between_pages(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    transactions = [
        {
            "id": transaction_id,
            "date": "Mon, 31 Aug 2026 14:30:00 GMT",
            "merchant": f"Merchant {transaction_id}",
            "description": "Purchase",
            "amount": transaction_id,
            "category_id": 80,
        }
        for transaction_id in range(1, 13)
    ]
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(transactions),
            response_with_json([]),
        ]),
    )

    response = client.get("/ui/transactions?page=2&page_size=5")

    assert response.status_code == 200
    for transaction_id in range(6, 11):
        assert f"<td>Merchant {transaction_id}</td>" in response.text
    assert "<td>Merchant 5</td>" not in response.text
    assert "<td>Merchant 11</td>" not in response.text
    assert "Showing 6-10 of 12 transactions" in response.text
    assert "Page 2 of 3" in response.text
    assert (
        'hx-get="/transactions-backend/ui/transactions?page=1"'
        in response.text
    )
    assert (
        'hx-get="/transactions-backend/ui/transactions?page=3"'
        in response.text
    )


def test_transaction_rows_apply_search_category_and_date_filters(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    today = date.today()
    transactions = [
        {
            "id": 1,
            "date": today.isoformat(),
            "merchant": "Fresh Market",
            "description": "Weekly groceries",
            "amount": 42,
            "category_id": 80,
        },
        {
            "id": 2,
            "date": today.isoformat(),
            "merchant": "Market Cafe",
            "description": "Lunch",
            "amount": 18,
            "category_id": 81,
        },
        {
            "id": 3,
            "date": (today - timedelta(days=45)).isoformat(),
            "merchant": "Old Market",
            "description": "Groceries",
            "amount": 30,
            "category_id": 80,
        },
        {
            "id": 4,
            "date": today.isoformat(),
            "merchant": "Corner Store",
            "description": "Groceries",
            "amount": 20,
            "category_id": 80,
        },
    ]
    categories = [
        {"id": 80, "name": "Groceries", "type": "need"},
        {"id": 81, "name": "Dining", "type": "want"},
    ]
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(transactions),
            response_with_json(categories),
        ]),
    )

    response = client.get(
        "/ui/transactions"
        "?search=market"
        "&category_id=80"
        "&date_range=last_30_days"
    )

    assert response.status_code == 200
    assert "<td>Fresh Market</td>" in response.text
    assert "<td>Market Cafe</td>" not in response.text
    assert "<td>Old Market</td>" not in response.text
    assert "<td>Corner Store</td>" not in response.text
    assert "Showing 1-1 of 1 transactions" in response.text


def test_transaction_rows_show_empty_state(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[response_with_json([]), response_with_json([])]),
    )

    response = client.get("/ui/transactions")

    assert response.status_code == 200
    assert "No transactions found." in response.text


def test_transaction_rows_show_filtered_empty_state(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json([]),
            response_with_json([]),
        ]),
    )

    response = client.get("/ui/transactions?search=missing")

    assert response.status_code == 200
    assert "No transactions match your filters." in response.text


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


def test_create_transaction_forwards_request(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    payload = {
        "date": "2026-09-01",
        "merchant": "Merivale",
        "description": "Lunch",
        "amount": 42,
        "category_id": 80,
    }
    post = Mock(return_value=response_with_json(
        {"id": 43, **payload},
        status=201,
    ))
    monkeypatch.setattr(backend_app.requests, "post", post)

    response = client.post("/transactions", json=payload)

    assert response.status_code == 201
    assert response.get_json() == {"id": 43, **payload}
    post.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions",
        json=payload,
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_update_transaction_forwards_request(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    payload = {"merchant": "Woolworths", "category_id": 81}
    patch = Mock(return_value=response_with_json({
        **TRANSACTION,
        **payload,
    }))
    monkeypatch.setattr(backend_app.requests, "patch", patch)

    response = client.patch("/transactions/42", json=payload)

    assert response.status_code == 200
    assert response.get_json()["merchant"] == "Woolworths"
    patch.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions/42",
        json=payload,
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_get_and_delete_transaction_forward_requests(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = Mock(return_value=response_with_json(TRANSACTION))
    delete = Mock(return_value=response_with_json(None, status=204))
    monkeypatch.setattr(backend_app.requests, "get", get)
    monkeypatch.setattr(backend_app.requests, "delete", delete)

    get_response = client.get("/transactions/42")
    delete_response = client.delete("/transactions/42")

    assert get_response.status_code == 200
    assert get_response.get_json() == TRANSACTION
    assert delete_response.status_code == 204
    get.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions/42",
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )
    delete.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions/42",
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_transaction_filters_are_forwarded(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = Mock(return_value=response_with_json([]))
    monkeypatch.setattr(backend_app.requests, "get", get)

    response = client.get(
        "/transactions?merchant=Merivale&min_amount=20&max_amount=90"
    )

    assert response.status_code == 200
    call = get.call_args
    assert call.args == (
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions",
    )
    assert call.kwargs["params"].to_dict() == {
        "merchant": "Merivale",
        "min_amount": "20",
        "max_amount": "90",
    }


def test_database_validation_error_is_preserved(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    error = {
        "error": "missing required fields: category_id",
        "code": "missing_fields",
    }
    monkeypatch.setattr(
        backend_app.requests,
        "post",
        Mock(return_value=response_with_json(error, status=422)),
    )

    response = client.post("/transactions", json={
        "date": "2026-09-01",
        "merchant": "Merivale",
        "description": "Dinner",
        "amount": 84.5,
    })

    assert response.status_code == 422
    assert response.get_json() == error


def test_category_routes_forward_requests(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    create_payload = {"name": "Education", "type": "saving"}
    update_payload = {"name": "Learning", "type": "want"}
    post = Mock(return_value=response_with_json(
        {"id": 90, **create_payload},
        status=201,
    ))
    patch = Mock(return_value=response_with_json({
        "id": 90,
        **update_payload,
    }))
    delete = Mock(return_value=response_with_json(None, status=204))
    monkeypatch.setattr(backend_app.requests, "post", post)
    monkeypatch.setattr(backend_app.requests, "patch", patch)
    monkeypatch.setattr(backend_app.requests, "delete", delete)

    create_response = client.post(
        "/categories",
        json=create_payload,
    )
    update_response = client.patch(
        "/categories/90",
        json=update_payload,
    )
    delete_response = client.delete("/categories/90")

    assert create_response.status_code == 201
    assert update_response.status_code == 200
    assert delete_response.status_code == 204
    post.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
        json=create_payload,
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )
    patch.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories/90",
        json=update_payload,
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )
    delete.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories/90",
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_new_transaction_form_loads_categories_from_database(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = Mock(return_value=response_with_json([
        {"id": 80, "name": "Dining", "type": "want"},
        {"id": 81, "name": "Groceries", "type": "need"},
    ]))
    monkeypatch.setattr(backend_app.requests, "get", get)

    response = client.get("/ui/transactions/new")

    assert response.status_code == 200
    assert "Add a transaction" in response.text
    assert '<option value="80"' in response.text
    assert "Dining" in response.text
    assert 'hx-post="/transactions-backend/ui/transactions"' in response.text
    assert 'hx-get="/transactions-backend/ui/transactions/page"' in response.text
    get.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_new_category_form_contains_category_fields(client: FlaskClient):
    response = client.get("/ui/categories/new")

    assert response.status_code == 200
    assert "Add a category" in response.text
    assert 'id="category-name"' in response.text
    assert 'name="name"' in response.text
    assert 'id="category-type"' in response.text
    assert 'name="type"' in response.text
    assert 'hx-post="/transactions-backend/ui/categories"' in response.text


def test_ui_create_category_posts_payload_and_returns_page(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    post = Mock(return_value=response_with_json(
        {
            "id": 90,
            "name": "Education",
            "type": "saving",
        },
        status=201,
    ))
    get = Mock(return_value=response_with_json([
        {"id": 90, "name": "Education", "type": "saving"},
    ]))
    monkeypatch.setattr(backend_app.requests, "post", post)
    monkeypatch.setattr(backend_app.requests, "get", get)

    response = client.post(
        "/ui/categories",
        data={
            "name": "Education",
            "type": "saving",
        },
    )

    assert response.status_code == 200
    assert "Category saved." in response.text
    assert '<option value="90">Education</option>' in response.text
    post.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
        json={
            "name": "Education",
            "type": "saving",
        },
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )
    get.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_ui_create_category_preserves_database_error(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "post",
        Mock(return_value=response_with_json(
            {
                "error": "category name already exists",
                "code": "category_name_conflict",
            },
            status=409,
        )),
    )

    response = client.post(
        "/ui/categories",
        data={
            "name": "Dining",
            "type": "want",
        },
    )

    assert response.status_code == 200
    assert "category name already exists" in response.text
    assert 'value="Dining"' in response.text
    assert '<option value="want"' in response.text
    assert "selected" in response.text


def test_transactions_page_loads_category_filter_options(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = Mock(return_value=response_with_json([
        {"id": 80, "name": "Dining", "type": "want"},
        {"id": 81, "name": "Groceries", "type": "need"},
    ]))
    monkeypatch.setattr(backend_app.requests, "get", get)

    response = client.get("/ui/transactions/page")

    assert response.status_code == 200
    assert 'id="transaction-search"' in response.text
    assert '<option value="80">Dining</option>' in response.text
    assert '<option value="81">Groceries</option>' in response.text
    assert 'value="last_30_days"' in response.text
    get.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_ui_create_transaction_posts_typed_payload_and_returns_page(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    post = Mock(return_value=response_with_json(
        {
            "id": 90,
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category_id": 80,
        },
        status=201,
    ))
    get = Mock(return_value=response_with_json([
        {"id": 80, "name": "Dining", "type": "want"},
    ]))
    monkeypatch.setattr(backend_app.requests, "post", post)
    monkeypatch.setattr(backend_app.requests, "get", get)

    response = client.post(
        "/ui/transactions",
        data={
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": "24.50",
            "category_id": "80",
        },
    )

    assert response.status_code == 200
    assert "Transaction saved." in response.text
    assert 'id="add-transaction-button"' in response.text
    assert '<option value="80">Dining</option>' in response.text
    post.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions",
        json={
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category_id": 80,
        },
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )
    get.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )
