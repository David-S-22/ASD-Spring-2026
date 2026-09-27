from datetime import date, timedelta
from unittest.mock import Mock, call
import importlib
import json

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


def test_health_reports_backend_liveness(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(backend_app.config, "MCP_ENABLED", True)
    monkeypatch.setattr(backend_app.config, "RAG_ENABLED", True)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "container": "transactions-backend",
        "modes": {"ai": "enabled", "mcp": "enabled", "rag": "enabled"},
    }


@mark.parametrize("mcp_enabled", [True, False])
@mark.parametrize("rag_enabled", [True, False])
def test_health_reports_mcp_and_rag_modes_without_network(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    mcp_enabled,
    rag_enabled,
):
    monkeypatch.setattr(backend_app.config, "MCP_ENABLED", mcp_enabled)
    monkeypatch.setattr(backend_app.config, "RAG_ENABLED", rag_enabled)
    for method in ("get", "post", "request"):
        monkeypatch.setattr(
            backend_app.requests,
            method,
            Mock(side_effect=AssertionError("no network")),
        )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["modes"] == {
        "ai": "enabled",
        "mcp": "enabled" if mcp_enabled else "disabled",
        "rag": "enabled" if rag_enabled else "disabled",
    }
    body = response.get_data(as_text=True)
    mcp_mode = "enabled" if mcp_enabled else "disabled"
    rag_mode = "enabled" if rag_enabled else "disabled"
    assert f'"mcp":"{mcp_mode}"' in body
    assert f'"rag":"{rag_mode}"' in body


def test_mcp_tools_lists_registered_tools(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    tools = [{
        "name": "search_transactions",
        "description": "Search transactions",
        "input_schema": {"type": "object"},
    }]
    monkeypatch.setattr(
        backend_app.mcp_client,
        "list_tools",
        Mock(return_value=tools),
    )

    response = client.get("/mcp/tools")

    assert response.status_code == 200
    assert response.get_json() == {"tools": tools}


def test_mcp_tools_refuses_when_disabled(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(backend_app.config, "MCP_ENABLED", False)

    response = client.get("/mcp/tools")

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "MCP mode is disabled.",
        "code": "mcp_disabled",
    }


@mark.parametrize("code", [
    "mcp_connection",
    "mcp_timeout",
    "mcp_tool_error",
    "mcp_invalid_result",
])
def test_mcp_tools_reports_unavailable_server(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    code,
):
    monkeypatch.setattr(
        backend_app.mcp_client,
        "list_tools",
        Mock(side_effect=backend_app.mcp_client.MCPError(code)),
    )

    response = client.get("/mcp/tools")

    assert response.status_code == 502
    assert response.get_json() == {
        "error": "The MCP server is unavailable.",
        "code": "mcp_unavailable",
    }


def test_rag_refresh_refuses_when_disabled(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(backend_app.config, "RAG_ENABLED", False)
    post = Mock()
    monkeypatch.setattr(backend_app.rag_client.requests, "post", post)

    response = client.post("/rag/refresh")

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "RAG mode is disabled.",
        "code": "rag_disabled",
    }
    post.assert_not_called()


def test_rag_refresh_pushes_empty_records_collection_when_enabled(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(backend_app.config, "RAG_ENABLED", True)
    monkeypatch.setattr(
        backend_app.config,
        "RAG_RECORDS_COLLECTION",
        "transactions-records",
    )
    refresh = Mock(return_value={
        "feature": "transactions-records",
        "total": 0,
    })
    monkeypatch.setattr(backend_app.rag_client, "refresh", refresh)

    response = client.post("/rag/refresh")

    assert response.status_code == 200
    body = response.get_json()
    assert body["feature"] == "transactions-records"
    assert body["total"] == 0
    assert body["kinds"] == {}
    assert isinstance(body["duration_ms"], float)
    refresh.assert_called_once_with("transactions-records", [], [], None)


@mark.parametrize("code", [
    "rag_connection",
    "rag_timeout",
    "rag_http_error",
    "rag_invalid_response",
])
def test_rag_refresh_reports_unavailable_server(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    code,
):
    monkeypatch.setattr(
        backend_app.rag_client,
        "refresh",
        Mock(side_effect=backend_app.rag_client.RAGError(code)),
    )

    response = client.post("/rag/refresh")

    assert response.status_code == 502
    assert response.get_json() == {
        "error": "The RAG server is unavailable.",
        "code": "rag_unavailable",
    }


MODE_ENVIRONMENT = (
    "MCP_ENABLED",
    "MCP_SERVER_URL",
    "MCP_TIMEOUT_SECONDS",
    "MCP_ALLOWED_TOOLS",
    "MCP_FALLBACK_TO_DATABASE",
    "RAG_ENABLED",
    "RAG_SERVER_URL",
    "RAG_RECORDS_COLLECTION",
    "RAG_GUIDE_COLLECTION",
    "RAG_TOP_K",
    "RAG_GUIDE_TOP_K",
    "RAG_TIMEOUT_SECONDS",
    "RAG_REFRESH_ON_START",
    "RAG_REFRESH_AFTER_WRITE",
    "RAG_INSUFFICIENT_ABOVE",
    "RAG_HIGH_BELOW",
    "RAG_MEDIUM_BELOW",
    "RAG_MODEL",
)


@fixture
def reload_config(monkeypatch: MonkeyPatch):
    for name in MODE_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    def reload(**environment):
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(backend_app.config)

    yield reload
    monkeypatch.undo()
    importlib.reload(backend_app.config)


def test_config_mode_defaults_match_design(reload_config):
    config = reload_config()

    assert config.MCP_ENABLED is True
    assert config.MCP_SERVER_URL == "http://host.docker.internal:8000/mcp"
    assert config.MCP_TIMEOUT_SECONDS == 30.0
    assert config.MCP_ALLOWED_TOOLS == frozenset({"search_transactions"})
    assert config.MCP_FALLBACK_TO_DATABASE is True
    assert config.RAG_ENABLED is True
    assert config.RAG_SERVER_URL == "http://host.docker.internal:5003"
    assert config.RAG_RECORDS_COLLECTION == "transactions-records"
    assert config.RAG_GUIDE_COLLECTION == "transactions"
    assert config.RAG_TOP_K == 6
    assert config.RAG_GUIDE_TOP_K == 3
    assert config.RAG_TIMEOUT_SECONDS == 15.0
    assert config.RAG_REFRESH_ON_START is True
    assert config.RAG_REFRESH_AFTER_WRITE is True
    assert config.RAG_INSUFFICIENT_ABOVE == 1.2
    assert config.RAG_HIGH_BELOW == 0.6
    assert config.RAG_MEDIUM_BELOW == 0.9
    assert config.RAG_MODEL == "qwen2.5:3b"


def test_config_reads_mode_overrides(reload_config):
    config = reload_config(
        MCP_ENABLED="false",
        MCP_SERVER_URL="http://mcp.local:9000/mcp/",
        MCP_TIMEOUT_SECONDS="4.5",
        MCP_ALLOWED_TOOLS=" search_transactions , retrieve_context ,,",
        MCP_FALLBACK_TO_DATABASE="no",
        RAG_ENABLED="off",
        RAG_SERVER_URL="http://rag.local:5003/",
        RAG_RECORDS_COLLECTION="records",
        RAG_GUIDE_COLLECTION="guide",
        RAG_TOP_K="4",
        RAG_GUIDE_TOP_K="2",
        RAG_TIMEOUT_SECONDS="3",
        RAG_REFRESH_ON_START="0",
        RAG_REFRESH_AFTER_WRITE="false",
        RAG_INSUFFICIENT_ABOVE="1.5",
        RAG_HIGH_BELOW="0.5",
        RAG_MEDIUM_BELOW="1.0",
        RAG_MODEL="llama3.2:3b",
    )

    assert config.MCP_ENABLED is False
    assert config.MCP_SERVER_URL == "http://mcp.local:9000/mcp"
    assert config.MCP_TIMEOUT_SECONDS == 4.5
    assert config.MCP_ALLOWED_TOOLS == frozenset({
        "search_transactions",
        "retrieve_context",
    })
    assert config.MCP_FALLBACK_TO_DATABASE is False
    assert config.RAG_ENABLED is False
    assert config.RAG_SERVER_URL == "http://rag.local:5003"
    assert config.RAG_RECORDS_COLLECTION == "records"
    assert config.RAG_GUIDE_COLLECTION == "guide"
    assert config.RAG_TOP_K == 4
    assert config.RAG_GUIDE_TOP_K == 2
    assert config.RAG_TIMEOUT_SECONDS == 3.0
    assert config.RAG_REFRESH_ON_START is False
    assert config.RAG_REFRESH_AFTER_WRITE is False
    assert config.RAG_INSUFFICIENT_ABOVE == 1.5
    assert config.RAG_HIGH_BELOW == 0.5
    assert config.RAG_MEDIUM_BELOW == 1.0
    assert config.RAG_MODEL == "llama3.2:3b"


@mark.parametrize("value, expected", [
    ("true", True),
    ("1", True),
    ("yes", True),
    ("ON", True),
    ("false", False),
    ("0", False),
    ("", False),
])
def test_config_mode_switches_parse_flags(reload_config, value, expected):
    config = reload_config(MCP_ENABLED=value, RAG_ENABLED=value)

    assert config.MCP_ENABLED is expected
    assert config.RAG_ENABLED is expected


@mark.parametrize("environment", [
    {"RAG_HIGH_BELOW": "0.95"},
    {"RAG_MEDIUM_BELOW": "1.3"},
    {"RAG_HIGH_BELOW": "0"},
    {"RAG_HIGH_BELOW": "-0.1"},
    {"RAG_INSUFFICIENT_ABOVE": "not-a-number"},
])
def test_invalid_rag_thresholds_fall_back_to_defaults_with_warning(
    reload_config,
    caplog,
    environment,
):
    with caplog.at_level("WARNING"):
        config = reload_config(**environment)

    assert (
        config.RAG_INSUFFICIENT_ABOVE,
        config.RAG_HIGH_BELOW,
        config.RAG_MEDIUM_BELOW,
    ) == (1.2, 0.6, 0.9)
    warnings = [
        record for record in caplog.records
        if "Invalid RAG distance thresholds" in record.getMessage()
    ]
    assert len(warnings) == 1


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
    assert post.call_args_list[0] == call(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions",
        json=payload,
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )
    assert post.call_args_list[1] == call(
        f"{backend_app.config.ANOMALIES_BACKEND_URL}/check-transaction",
        json={"id": 43, **payload},
        timeout=backend_app.config.ANOMALIES_TIMEOUT_SECONDS,
    )


def test_create_transaction_rejects_agent_only_suggestion_field(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    post = Mock()
    monkeypatch.setattr(backend_app.requests, "post", post)

    response = client.post("/transactions", json={
        "date": "2026-09-01",
        "merchant": "Merivale",
        "description": "Lunch",
        "amount": 42,
        "category_id": 81,
        "suggested_category_id": 80,
    })

    assert response.status_code == 422
    assert response.get_json()["code"] == "unsupported_fields"
    post.assert_not_called()


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
    categories = [
        {"id": 80, "name": "Dining", "type": "want"},
        {"id": 90, "name": "Education", "type": "saving"},
    ]
    create_payload = {"name": "Education", "type": "saving"}
    update_payload = {"name": "Learning", "type": "want"}
    get = Mock(side_effect=[
        response_with_json(categories),
        response_with_json(categories[1]),
    ])
    post = Mock(return_value=response_with_json(
        {"id": 90, **create_payload},
        status=201,
    ))
    patch = Mock(return_value=response_with_json({
        "id": 90,
        **update_payload,
    }))
    delete = Mock(return_value=response_with_json(None, status=204))
    monkeypatch.setattr(backend_app.requests, "get", get)
    monkeypatch.setattr(backend_app.requests, "post", post)
    monkeypatch.setattr(backend_app.requests, "patch", patch)
    monkeypatch.setattr(backend_app.requests, "delete", delete)

    list_response = client.get("/categories")
    get_response = client.get("/categories/90")
    create_response = client.post(
        "/categories",
        json=create_payload,
    )
    update_response = client.patch(
        "/categories/90",
        json=update_payload,
    )
    delete_response = client.delete("/categories/90")

    assert list_response.status_code == 200
    assert list_response.get_json() == categories
    assert get_response.status_code == 200
    assert get_response.get_json() == categories[1]
    assert create_response.status_code == 201
    assert update_response.status_code == 200
    assert delete_response.status_code == 204
    assert get.call_args_list == [
        call(
            f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
            timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
        ),
        call(
            f"{backend_app.config.TRANSACTIONS_DB_URL}/categories/90",
            timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
        ),
    ]
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
    assert response.headers["HX-Trigger"] == json.dumps({"transaction-created": 90})
    assert post.call_args_list[0] == call(
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
    assert post.call_args_list[1] == call(
        f"{backend_app.config.ANOMALIES_BACKEND_URL}/check-transaction",
        json={
            "id": 90,
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category_id": 80,
        },
        timeout=backend_app.config.ANOMALIES_TIMEOUT_SECONDS,
    )
    get.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/categories",
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )
