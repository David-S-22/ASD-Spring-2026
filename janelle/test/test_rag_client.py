from unittest.mock import Mock

import requests
from pytest import MonkeyPatch, fixture, mark, raises

from janelle.backend import config
from janelle.backend.services import rag_client
from janelle.backend.services.rag_client import RAGError


LEAK_MARKER = "internal error detail that must not leak"


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload
    response.text = LEAK_MARKER
    return response


@fixture(autouse=True)
def rag_enabled(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    monkeypatch.setattr(config, "RAG_SERVER_URL", "http://rag.test")
    monkeypatch.setattr(config, "RAG_TIMEOUT_SECONDS", 7)


@fixture
def http(monkeypatch: MonkeyPatch):
    get = Mock()
    post = Mock()
    monkeypatch.setattr(rag_client.requests, "get", get)
    monkeypatch.setattr(rag_client.requests, "post", post)
    return get, post


def test_health_returns_body(http):
    get, _ = http
    get.return_value = response_with_json({
        "ok": True,
        "collections": ["transactions"],
    })

    assert rag_client.health() == {"ok": True, "collections": ["transactions"]}
    get.assert_called_once_with("http://rag.test/health", timeout=7)


def test_refresh_posts_documents_and_returns_total(http):
    _, post = http
    post.return_value = response_with_json({
        "feature": "transactions-records",
        "total": 2,
    })

    result = rag_client.refresh(
        "transactions-records",
        ["a", "b"],
        ["doc a", "doc b"],
        [{"kind": "transaction"}, {"kind": "correction"}],
    )

    assert result == {"feature": "transactions-records", "total": 2}
    post.assert_called_once_with(
        "http://rag.test/refresh",
        json={
            "feature": "transactions-records",
            "ids": ["a", "b"],
            "documents": ["doc a", "doc b"],
            "metadatas": [{"kind": "transaction"}, {"kind": "correction"}],
        },
        timeout=7,
    )


def test_retrieve_posts_question_and_returns_results(http):
    _, post = http
    post.return_value = response_with_json({"results": [
        {
            "id": "transaction-7",
            "text": "Anytime Fitness",
            "metadata": {"category_id": 3},
            "distance": 0.4,
        },
        {
            "id": "transaction-8",
            "text": "Gym",
            "metadata": {},
            "distance": 1,
        },
    ]})

    results = rag_client.retrieve(
        "transactions-records",
        "Anytime Fitness",
        k=6,
        where={"kind": "transaction"},
    )

    assert results == [
        {
            "id": "transaction-7",
            "text": "Anytime Fitness",
            "metadata": {"category_id": 3},
            "distance": 0.4,
        },
        {
            "id": "transaction-8",
            "text": "Gym",
            "metadata": {},
            "distance": 1.0,
        },
    ]
    post.assert_called_once_with(
        "http://rag.test/retrieve",
        json={
            "feature": "transactions-records",
            "question": "Anytime Fitness",
            "k": 6,
            "where": {"kind": "transaction"},
        },
        timeout=7,
    )


def test_retrieve_omits_where_when_not_given(http):
    _, post = http
    post.return_value = response_with_json({"results": []})

    assert rag_client.retrieve("transactions", "question") == []
    assert post.call_args.kwargs["json"] == {
        "feature": "transactions",
        "question": "question",
        "k": 3,
    }


OPERATIONS = [
    lambda: rag_client.health(),
    lambda: rag_client.refresh("transactions-records", [], [], None),
    lambda: rag_client.retrieve("transactions", "question"),
]


@mark.parametrize("operation", OPERATIONS)
def test_disabled_mode_short_circuits_without_request(
    monkeypatch: MonkeyPatch,
    http,
    operation,
):
    get, post = http
    monkeypatch.setattr(config, "RAG_ENABLED", False)

    with raises(RAGError) as caught:
        operation()

    assert caught.value.code == "rag_disabled"
    get.assert_not_called()
    post.assert_not_called()


@mark.parametrize("operation", OPERATIONS)
@mark.parametrize("error, code", [
    (requests.Timeout(LEAK_MARKER), "rag_timeout"),
    (requests.ConnectTimeout(LEAK_MARKER), "rag_timeout"),
    (requests.ConnectionError(LEAK_MARKER), "rag_connection"),
    (requests.RequestException(LEAK_MARKER), "rag_connection"),
])
def test_transport_errors_map_to_safe_codes(http, operation, error, code):
    get, post = http
    get.side_effect = error
    post.side_effect = error

    with raises(RAGError) as caught:
        operation()

    assert caught.value.code == code
    assert LEAK_MARKER not in caught.value.message
    assert LEAK_MARKER not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


@mark.parametrize("operation", OPERATIONS)
@mark.parametrize("status", [500, 404, 400, 302])
def test_non_2xx_maps_to_rag_http_error(http, operation, status):
    get, post = http
    get.return_value = response_with_json({"error": LEAK_MARKER}, status)
    post.return_value = response_with_json({"error": LEAK_MARKER}, status)

    with raises(RAGError) as caught:
        operation()

    assert caught.value.code == "rag_http_error"
    assert LEAK_MARKER not in caught.value.message


@mark.parametrize("operation", OPERATIONS)
def test_non_json_body_is_invalid(http, operation):
    get, post = http
    for method in (get, post):
        method.return_value = response_with_json(None)
        method.return_value.json.side_effect = ValueError(LEAK_MARKER)

    with raises(RAGError) as caught:
        operation()

    assert caught.value.code == "rag_invalid_response"
    assert LEAK_MARKER not in caught.value.message


@mark.parametrize("body", [
    {},
    {"results": None},
    {"results": {"id": "x"}},
    {"results": ["text"]},
    {"results": [{"id": "x", "text": "t", "metadata": {}}]},
    {"results": [{"id": "x", "text": "t", "metadata": {}, "distance": "0.1"}]},
    {"results": [{"id": "x", "text": "t", "metadata": {}, "distance": True}]},
    {"results": [{"id": "x", "text": "t", "metadata": None, "distance": 0.1}]},
    {"results": [{"id": 1, "text": "t", "metadata": {}, "distance": 0.1}]},
    {"results": [{"id": "x", "text": None, "metadata": {}, "distance": 0.1}]},
    [],
])
def test_malformed_retrieve_body_is_invalid(http, body):
    _, post = http
    post.return_value = response_with_json(body)

    with raises(RAGError) as caught:
        rag_client.retrieve("transactions", "question")

    assert caught.value.code == "rag_invalid_response"


@mark.parametrize("body", [
    {},
    {"feature": "transactions-records"},
    {"feature": "transactions-records", "total": "2"},
    {"feature": "transactions-records", "total": True},
    {"total": 2},
])
def test_malformed_refresh_body_is_invalid(http, body):
    _, post = http
    post.return_value = response_with_json(body)

    with raises(RAGError) as caught:
        rag_client.refresh("transactions-records", [], [], None)

    assert caught.value.code == "rag_invalid_response"


def test_health_without_collections_is_invalid(http):
    get, _ = http
    get.return_value = response_with_json({"ok": True})

    with raises(RAGError) as caught:
        rag_client.health()

    assert caught.value.code == "rag_invalid_response"
