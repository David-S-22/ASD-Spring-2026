from datetime import date, timedelta
from unittest.mock import Mock, call
import importlib
import json
import re

import requests
from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark

import janelle.backend.app as backend_app


DB_URL = backend_app.config.TRANSACTIONS_DB_URL
DB_TIMEOUT = backend_app.config.DATABASE_TIMEOUT_SECONDS
ANOMALIES_URL = backend_app.config.ANOMALIES_BACKEND_URL
CATEGORIES = [
    {"id": 80, "name": "Dining", "type": "want"},
    {"id": 81, "name": "Groceries", "type": "need"},
]


def transaction(transaction_id, **overrides):
    return {
        "id": transaction_id,
        "date": "Mon, 31 Aug 2026 14:30:00 GMT",
        "merchant": f"Merchant {transaction_id}",
        "description": "Purchase",
        "amount": transaction_id,
        "category_id": 80,
        **overrides,
    }


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def merchant_rows(response):
    return re.findall(r"<td>Merchant (\d+)</td>", response.text)


@fixture
def client():
    with backend_app.app.test_client() as test_client:
        yield test_client


@fixture
def fake_request(monkeypatch: MonkeyPatch):
    """Replace one ``requests`` method with a canned JSON response."""
    def install(method, payload=None, status=200):
        mock = Mock(return_value=response_with_json(payload, status))
        monkeypatch.setattr(backend_app.requests, method, mock)
        return mock
    return install


@fixture
def database(monkeypatch: MonkeyPatch):
    """Serve fake ``/transactions`` and ``/categories`` rows via requests.get."""
    def install(transactions=(), categories=CATEGORIES):
        rows = {
            "transactions": list(transactions),
            "categories": list(categories),
        }

        def get(url, **_):
            return response_with_json(rows[url.rsplit("/", 1)[1]])

        mock = Mock(side_effect=get)
        monkeypatch.setattr(backend_app.requests, "get", mock)
        return mock
    return install


# --- health, MCP and RAG routes -------------------------------------------


@mark.parametrize("enabled, mode", [(True, "enabled"), (False, "disabled")])
def test_health_reports_mcp_and_rag_modes(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    enabled,
    mode,
):
    monkeypatch.setattr(backend_app.config, "MCP_ENABLED", enabled)
    monkeypatch.setattr(backend_app.config, "RAG_ENABLED", enabled)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "container": "transactions-backend",
        "modes": {"ai": "enabled", "mcp": mode, "rag": mode},
    }


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
    assert response.get_json()["code"] == "mcp_disabled"


def test_mcp_tools_reports_unavailable_server(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.mcp_client,
        "list_tools",
        Mock(side_effect=backend_app.mcp_client.MCPError("mcp_connection")),
    )

    response = client.get("/mcp/tools")

    assert response.status_code == 502
    assert response.get_json() == {
        "error": "The MCP server is unavailable.",
        "code": "mcp_unavailable",
    }


@fixture
def rag_corpus(monkeypatch: MonkeyPatch):
    """Enable RAG and return the (ids, documents, metadatas) it will push."""
    monkeypatch.setattr(backend_app.config, "RAG_ENABLED", True)
    corpus = (
        ["tx-7", "corr-3"],
        ["Transaction 7 ...", "Transaction 26 ... recategorised ..."],
        [{"kind": "transaction"}, {"kind": "correction"}],
    )
    monkeypatch.setattr(
        backend_app.rag_corpus,
        "fetch_and_build",
        Mock(return_value=(*corpus, {"transaction": 1, "correction": 1})),
    )
    return corpus


def test_rag_refresh_pushes_corpus_and_reports_kinds(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_corpus,
):
    refresh = Mock(return_value={"feature": "transactions-records", "total": 2})
    monkeypatch.setattr(backend_app.rag_client, "refresh", refresh)

    response = client.post("/rag/refresh")

    assert response.status_code == 200
    body = response.get_json()
    assert body["feature"] == "transactions-records"
    assert body["total"] == 2
    assert body["kinds"] == {"transaction": 1, "correction": 1}
    assert isinstance(body["duration_ms"], float)
    refresh.assert_called_once_with(
        backend_app.config.RAG_RECORDS_COLLECTION,
        *rag_corpus,
    )


def test_rag_refresh_refuses_when_disabled(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(backend_app.config, "RAG_ENABLED", False)
    refresh = Mock()
    monkeypatch.setattr(backend_app.rag_client, "refresh", refresh)

    response = client.post("/rag/refresh")

    assert response.status_code == 503
    assert response.get_json()["code"] == "rag_disabled"
    refresh.assert_not_called()


def test_rag_refresh_reports_unavailable_server(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_corpus,
):
    monkeypatch.setattr(
        backend_app.rag_client,
        "refresh",
        Mock(side_effect=backend_app.rag_client.RAGError("rag_connection")),
    )

    response = client.post("/rag/refresh")

    assert response.status_code == 502
    assert response.get_json() == {
        "error": "The RAG server is unavailable.",
        "code": "rag_unavailable",
    }


# --- config ----------------------------------------------------------------


MODE_ENVIRONMENT = (
    "MCP_ENABLED", "MCP_SERVER_URL", "MCP_TIMEOUT_SECONDS",
    "MCP_ALLOWED_TOOLS", "MCP_FALLBACK_TO_DATABASE",
    "RAG_ENABLED", "RAG_SERVER_URL", "RAG_RECORDS_COLLECTION",
    "RAG_GUIDE_COLLECTION", "RAG_TOP_K", "RAG_GUIDE_TOP_K",
    "RAG_TIMEOUT_SECONDS", "RAG_REFRESH_ON_START", "RAG_REFRESH_AFTER_WRITE",
    "RAG_HIGH", "RAG_MEDIUM", "RAG_LOW", "RAG_MODEL",
)


@fixture
def reload_config(monkeypatch: MonkeyPatch):
    """Reload config with a clean mode environment plus the given overrides."""
    for name in MODE_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    def reload(**environment):
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(backend_app.config)

    yield reload
    monkeypatch.undo()
    importlib.reload(backend_app.config)


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
        RAG_HIGH="0.5",
        RAG_MEDIUM="1.0",
        RAG_LOW="1.5",
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
    assert (config.RAG_HIGH, config.RAG_MEDIUM, config.RAG_LOW) == (0.5, 1.0, 1.5)
    assert config.RAG_MODEL == "llama3.2:3b"


@mark.parametrize("value, expected", [
    ("true", True),
    ("0", False),
    (None, True),  # unset: both modes default on
])
def test_config_mode_switches_parse_flags(reload_config, value, expected):
    environment = (
        {} if value is None else {"MCP_ENABLED": value, "RAG_ENABLED": value}
    )

    config = reload_config(**environment)

    assert config.MCP_ENABLED is expected
    assert config.RAG_ENABLED is expected


@mark.parametrize("environment", [
    {"RAG_HIGH": "0.95"},  # breaks high < medium
    {"RAG_LOW": "not-a-number"},
])
def test_invalid_rag_thresholds_fall_back_to_defaults_with_warning(
    reload_config,
    caplog,
    environment,
):
    with caplog.at_level("WARNING"):
        config = reload_config(**environment)

    assert (config.RAG_HIGH, config.RAG_MEDIUM, config.RAG_LOW) == (0.6, 0.9, 1.2)
    warnings = [
        record for record in caplog.records
        if "Invalid RAG distance thresholds" in record.getMessage()
    ]
    assert len(warnings) == 1


# --- HTMX transaction table -------------------------------------------------


def test_transaction_rows_are_loaded_from_database(
    client: FlaskClient,
    database,
):
    get = database(transactions=[transaction(
        1,
        merchant="<script>alert('xss')</script>",
        description="Lunch",
        amount=18.5,
    )])

    response = client.get("/ui/transactions")

    assert response.status_code == 200
    assert "<td>Mon, 31 Aug 2026</td>" in response.text
    assert "<td>Lunch</td>" in response.text
    assert "<td>18.50</td>" in response.text
    assert "<td>Dining</td>" in response.text
    assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in response.text
    assert [c.args[0] for c in get.call_args_list] == [
        f"{DB_URL}/transactions",
        f"{DB_URL}/categories",
    ]


def test_transaction_rows_paginate_with_allowed_page_sizes(
    client: FlaskClient,
    database,
):
    database(transactions=[transaction(i) for i in range(1, 13)])

    second_page = client.get("/ui/transactions?page=2&page_size=5")
    assert second_page.status_code == 200
    assert merchant_rows(second_page) == ["6", "7", "8", "9", "10"]
    assert "Showing 6-10 of 12 transactions" in second_page.text
    assert "Page 2 of 3" in second_page.text
    assert (
        'hx-get="/transactions-backend/ui/transactions?page=1"'
        in second_page.text
    )
    assert (
        'hx-get="/transactions-backend/ui/transactions?page=3"'
        in second_page.text
    )

    large_page = client.get("/ui/transactions?page_size=20")
    assert len(merchant_rows(large_page)) == 12
    assert '<option value="20" selected>' in large_page.text

    rejected_size = client.get("/ui/transactions?page_size=7")
    assert len(merchant_rows(rejected_size)) == 5
    assert '<option value="5" selected>' in rejected_size.text


def test_transaction_rows_apply_search_category_and_date_filters(
    client: FlaskClient,
    database,
):
    today = date.today().isoformat()
    old = (date.today() - timedelta(days=45)).isoformat()
    database(transactions=[
        transaction(1, date=today, merchant="Fresh Market"),
        transaction(2, date=today, merchant="Market Cafe", category_id=81),
        transaction(3, date=old, merchant="Old Market"),
        transaction(4, date=today, merchant="Corner Store"),
    ])

    response = client.get(
        "/ui/transactions?search=market&category_id=80&date_range=last_30_days"
    )

    assert response.status_code == 200
    assert "<td>Fresh Market</td>" in response.text
    assert "<td>Market Cafe</td>" not in response.text
    assert "<td>Old Market</td>" not in response.text
    assert "<td>Corner Store</td>" not in response.text
    assert "Showing 1-1 of 1 transactions" in response.text


def test_transaction_rows_show_empty_state(client: FlaskClient, database):
    database()

    unfiltered = client.get("/ui/transactions")
    filtered = client.get("/ui/transactions?search=missing")

    assert "No transactions found." in unfiltered.text
    assert "No transactions match your filters." in filtered.text


@mark.parametrize("json_result", [
    {"side_effect": requests.exceptions.JSONDecodeError("invalid", "", 0)},
    {"return_value": {"not": "a list of rows"}},
], ids=["invalid_json", "invalid_shape"])
def test_transaction_rows_reject_invalid_database_response(
    client: FlaskClient,
    fake_request,
    json_result,
):
    fake_request("get").return_value.json = Mock(**json_result)

    response = client.get("/ui/transactions")

    assert response.status_code == 502
    assert "database response was invalid" in response.text


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


# --- JSON proxy routes ------------------------------------------------------


def test_get_proxy_forwards_query_and_relays_response(
    client: FlaskClient,
    fake_request,
):
    rows = [transaction(42)]
    get = fake_request("get", rows)

    response = client.get("/transactions?merchant=Merivale&min_amount=20")

    assert response.status_code == 200
    assert response.get_json() == rows
    assert get.call_args.args == (f"{DB_URL}/transactions",)
    assert get.call_args.kwargs["timeout"] == DB_TIMEOUT
    assert get.call_args.kwargs["params"].to_dict() == {
        "merchant": "Merivale",
        "min_amount": "20",
    }


def test_write_proxy_forwards_body_and_relays_validation_error(
    client: FlaskClient,
    fake_request,
):
    error = {"error": "invalid category type", "code": "invalid_type"}
    patch = fake_request("patch", error, status=422)

    response = client.patch("/categories/90", json={"type": "bogus"})

    assert response.status_code == 422
    assert response.get_json() == error
    patch.assert_called_once_with(
        f"{DB_URL}/categories/90",
        json={"type": "bogus"},
        timeout=DB_TIMEOUT,
    )


def test_delete_proxy_relays_no_content(client: FlaskClient, fake_request):
    delete = fake_request("delete", status=204)

    response = client.delete("/transactions/42")

    assert response.status_code == 204
    assert response.data == b""
    delete.assert_called_once_with(
        f"{DB_URL}/transactions/42",
        timeout=DB_TIMEOUT,
    )


def test_create_transaction_relays_row_and_queues_anomaly_check(
    client: FlaskClient,
    fake_request,
):
    payload = {
        "date": "2026-09-01",
        "merchant": "Merivale",
        "description": "Lunch",
        "amount": 42,
        "category_id": 80,
    }
    created = {"id": 43, **payload}
    post = fake_request("post", created, status=201)

    response = client.post("/transactions", json=payload)

    assert response.status_code == 201
    assert response.get_json() == created
    assert post.call_args_list == [
        call(f"{DB_URL}/transactions", json=payload, timeout=DB_TIMEOUT),
        call(
            f"{ANOMALIES_URL}/check-transaction",
            json=created,
            timeout=backend_app.config.ANOMALIES_TIMEOUT_SECONDS,
        ),
    ]


def test_create_transaction_rejects_agent_only_suggestion_field(
    client: FlaskClient,
    fake_request,
):
    post = fake_request("post")

    response = client.post("/transactions", json={
        **transaction(1),
        "suggested_category_id": 80,
    })

    assert response.status_code == 422
    assert response.get_json()["code"] == "unsupported_fields"
    post.assert_not_called()


# --- HTMX forms and pages ---------------------------------------------------


def test_transactions_page_loads_category_filter_options(
    client: FlaskClient,
    database,
):
    get = database()

    response = client.get("/ui/transactions/page")

    assert response.status_code == 200
    assert '<option value="80">Dining</option>' in response.text
    assert '<option value="81">Groceries</option>' in response.text
    get.assert_called_once_with(f"{DB_URL}/categories", timeout=DB_TIMEOUT)


def test_new_transaction_form_loads_categories_from_database(
    client: FlaskClient,
    database,
):
    database()

    response = client.get("/ui/transactions/new")

    assert response.status_code == 200
    assert '<option value="80"' in response.text
    assert "Dining" in response.text
    assert 'hx-post="/transactions-backend/ui/transactions"' in response.text


def test_new_category_form_renders_category_fields(client: FlaskClient):
    response = client.get("/ui/categories/new")

    assert response.status_code == 200
    assert 'name="name"' in response.text
    assert 'name="type"' in response.text
    assert 'hx-post="/transactions-backend/ui/categories"' in response.text


def test_ui_create_transaction_posts_typed_payload_and_returns_page(
    client: FlaskClient,
    database,
    fake_request,
):
    database()
    payload = {
        "date": "2026-09-02",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 80,
    }
    created = {"id": 90, **payload}
    post = fake_request("post", created, status=201)

    response = client.post("/ui/transactions", data={
        **payload,
        "amount": "24.50",
        "category_id": "80",
    })

    assert response.status_code == 200
    assert "Transaction saved." in response.text
    assert '<option value="80">Dining</option>' in response.text
    assert response.headers["HX-Trigger"] == json.dumps(
        {"transaction-created": 90}
    )
    assert post.call_args_list == [
        call(f"{DB_URL}/transactions", json=payload, timeout=DB_TIMEOUT),
        call(
            f"{ANOMALIES_URL}/check-transaction",
            json=created,
            timeout=backend_app.config.ANOMALIES_TIMEOUT_SECONDS,
        ),
    ]


def test_ui_create_category_posts_payload_and_returns_page(
    client: FlaskClient,
    database,
    fake_request,
):
    payload = {"name": "Education", "type": "saving"}
    database(categories=[{"id": 90, **payload}])
    post = fake_request("post", {"id": 90, **payload}, status=201)

    response = client.post("/ui/categories", data=payload)

    assert response.status_code == 200
    assert "Category saved." in response.text
    assert "<td>Education</td>" in response.text
    post.assert_called_once_with(
        f"{DB_URL}/categories",
        json=payload,
        timeout=DB_TIMEOUT,
    )


def test_ui_create_category_preserves_database_error_and_values(
    client: FlaskClient,
    fake_request,
):
    fake_request(
        "post",
        {"error": "category name already exists", "code": "category_name_conflict"},
        status=409,
    )

    response = client.post("/ui/categories", data={"name": "Dining", "type": "want"})

    assert response.status_code == 200
    assert "category name already exists" in response.text
    assert 'value="Dining"' in response.text
    assert re.search(r'value="want"\s+selected', response.text)
