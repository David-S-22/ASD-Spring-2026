from unittest.mock import Mock

from pytest import MonkeyPatch

from janelle.backend import config
from janelle.backend.services import chat_service, rag_corpus
from janelle.backend.services.rag_client import RAGError


CATEGORIES = [
    {"id": 1, "name": "Uncategorised", "type": None},
    {"id": 31, "name": "Fitness", "type": "want"},
    {"id": 40, "name": "Music subscriptions", "type": "want"},
]
TRANSACTIONS = [
    {
        "id": 7,
        "date": "2026-06-24T00:00:00",
        "merchant": "Anytime Fitness Ultimo",
        "description": "Direct debit membership fee",
        "amount": 17.5,
        "category_id": 31,
    },
    {
        "id": 8,
        "date": "2026-07-01T00:00:00",
        "merchant": "Mystery Shop",
        "description": "Card purchase",
        "amount": "12.00",
        "category_id": 1,
    },
]
CORRECTIONS = [
    {
        "id": 3,
        "transaction_id": 26,
        "date": "2026-08-19T00:00:00",
        "merchant": "Spotify AU",
        "description": "Monthly subscription",
        "previous_category_id": 1,
        "previous_category_name": "Uncategorised",
        "user_category_id": 40,
        "user_category_name": "Music subscriptions",
        "corrected_at": "2026-08-20T09:15:00.000000",
    },
]


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload
    return response


def test_build_documents_texts_and_stable_ids():
    ids, documents, metadatas = rag_corpus.build_documents(
        TRANSACTIONS,
        CATEGORIES,
        CORRECTIONS,
    )

    assert ids == ["tx-7", "tx-8", "corr-3"]
    assert documents[0] == (
        "Transaction 7 on 2026-06-24: Anytime Fitness Ultimo charged $17.50 "
        "for 'Direct debit membership fee'. Category: Fitness (want)."
    )
    assert documents[1] == (
        "Transaction 8 on 2026-07-01: Mystery Shop charged $12.00 "
        "for 'Card purchase'. Category: Uncategorised."
    )
    assert documents[2] == (
        "Transaction 26 (Spotify AU, 'Monthly subscription') was "
        "recategorised from Uncategorised to Music subscriptions on "
        "2026-08-20."
    )
    assert len(metadatas) == 3


def test_fetch_and_build_uses_database_request_and_counts_kinds(
    monkeypatch: MonkeyPatch,
):
    calls = []

    def database_request(method, url, expected=None, **options):
        calls.append((method, url))
        return {
            "http://db.test/transactions": TRANSACTIONS,
            "http://db.test/categories": CATEGORIES,
            "http://db.test/category-corrections": CORRECTIONS,
        }[url]

    monkeypatch.setattr(
        rag_corpus.chat_service,
        "database_request",
        database_request,
    )

    ids, documents, metadatas, kinds = rag_corpus.fetch_and_build(
        "http://db.test/",
    )

    assert [url for _, url in calls] == [
        "http://db.test/transactions",
        "http://db.test/categories",
        "http://db.test/category-corrections",
    ]
    assert ids == ["tx-7", "tx-8", "corr-3"]
    assert len(documents) == len(metadatas) == 3
    assert kinds == {"transaction": 2, "correction": 1}


def test_refresh_records_pushes_documents_and_returns_summary(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    monkeypatch.setattr(config, "RAG_RECORDS_COLLECTION", "transactions-records")
    monkeypatch.setattr(
        rag_corpus.chat_service,
        "database_request",
        Mock(side_effect=[TRANSACTIONS, CATEGORIES, CORRECTIONS]),
    )
    refresh = Mock(return_value={"feature": "transactions-records", "total": 3})
    monkeypatch.setattr(rag_corpus.rag_client, "refresh", refresh)

    summary = rag_corpus.refresh_records("http://db.test", "manual")

    assert summary["feature"] == "transactions-records"
    assert summary["total"] == 3
    assert summary["kinds"] == {"transaction": 2, "correction": 1}
    assert isinstance(summary["duration_ms"], float)
    ids, documents, metadatas = refresh.call_args.args[1:]
    assert ids == ["tx-7", "tx-8", "corr-3"]
    assert len(documents) == len(metadatas) == 3


def test_refresh_with_retries_never_raises_and_stops_after_attempts(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    refresh = Mock(side_effect=RAGError("rag_connection"))
    monkeypatch.setattr(rag_corpus, "refresh_records", refresh)
    sleep = Mock()
    monkeypatch.setattr(rag_corpus.time, "sleep", sleep)

    result = rag_corpus.refresh_with_retries(
        "http://db.test",
        "startup",
        attempts=3,
        delay_seconds=3,
    )

    assert result is None
    assert refresh.call_count == 3
    assert sleep.call_count == 2
    sleep.assert_called_with(3)


def test_refresh_with_retries_returns_on_first_success(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(config, "RAG_ENABLED", True)
    refresh = Mock(side_effect=[
        chat_service.ChatError("db down", "database_unavailable", 503),
        {"feature": "transactions-records", "total": 1},
    ])
    monkeypatch.setattr(rag_corpus, "refresh_records", refresh)
    monkeypatch.setattr(rag_corpus.time, "sleep", Mock())

    result = rag_corpus.refresh_with_retries(
        "http://db.test",
        "startup",
        attempts=10,
        delay_seconds=0,
    )

    assert result == {"feature": "transactions-records", "total": 1}
    assert refresh.call_count == 2


def test_start_background_refresh_is_skipped_when_disabled(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    thread_class = Mock()
    monkeypatch.setattr(rag_corpus.threading, "Thread", thread_class)

    assert rag_corpus.start_background_refresh("http://db.test", "x") is None
    thread_class.assert_not_called()
