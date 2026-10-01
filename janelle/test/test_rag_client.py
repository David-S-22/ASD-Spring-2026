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


def retrieve():
    return rag_client.retrieve("transactions", "question")


def refresh():
    return rag_client.refresh("transactions-records", [], [])


@fixture(autouse=True)
def rag_enabled(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    monkeypatch.setattr(config, "RAG_SERVER_URL", "http://rag.test")
    monkeypatch.setattr(config, "RAG_TIMEOUT_SECONDS", 7)


@fixture
def post(monkeypatch: MonkeyPatch):
    post = Mock()
    monkeypatch.setattr(rag_client.requests, "post", post)
    return post


def test_refresh_posts_documents_and_returns_total(post):
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


def test_retrieve_posts_question_and_returns_results(post):
    item = {"id": "tx-7", "text": "Gym", "metadata": {"category_id": 3}}
    post.return_value = response_with_json({
        "results": [{**item, "distance": 1}],
    })

    results = rag_client.retrieve(
        "transactions-records",
        "Anytime Fitness",
        k=6,
        where={"kind": "transaction"},
    )

    assert results == [{**item, "distance": 1.0}]
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

    post.return_value = response_with_json({"results": []})
    assert retrieve() == []
    assert post.call_args.kwargs["json"] == {
        "feature": "transactions",
        "question": "question",
        "k": 3,
    }


def test_disabled_mode_short_circuits_without_request(
    monkeypatch: MonkeyPatch,
    post,
):
    monkeypatch.setattr(config, "RAG_ENABLED", False)

    with raises(RAGError) as caught:
        retrieve()

    assert caught.value.code == "rag_disabled"
    post.assert_not_called()


@mark.parametrize("error, code", [
    (requests.Timeout, "rag_timeout"),
    (requests.ConnectionError, "rag_connection"),
])
def test_transport_errors_map_to_safe_codes(post, error, code):
    post.side_effect = error(LEAK_MARKER)

    with raises(RAGError) as caught:
        retrieve()

    assert caught.value.code == code
    assert LEAK_MARKER not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_non_2xx_maps_to_rag_http_error(post):
    post.return_value = response_with_json({"error": LEAK_MARKER}, 500)

    with raises(RAGError) as caught:
        refresh()

    assert caught.value.code == "rag_http_error"
    assert LEAK_MARKER not in str(caught.value)


@mark.parametrize("operation, body", [
    (retrieve, ValueError(LEAK_MARKER)),
    (retrieve, []),
    (retrieve, {"results": [{"id": "x", "text": "t", "metadata": {}}]}),
    (refresh, {"feature": "transactions-records", "total": "2"}),
])
def test_invalid_body_maps_to_rag_invalid_response(post, operation, body):
    post.return_value = response_with_json(body)
    if isinstance(body, Exception):
        post.return_value.json.side_effect = body

    with raises(RAGError) as caught:
        operation()

    assert caught.value.code == "rag_invalid_response"
    assert LEAK_MARKER not in str(caught.value)
