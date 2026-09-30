from unittest.mock import Mock, call

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
        "merchant": "Spotify AU",
        "description": "Monthly subscription",
        "previous_category_name": "Uncategorised",
        "user_category_id": 40,
        "user_category_name": "Music subscriptions",
        "corrected_at": "2026-08-20T09:15:00.000000",
    },
]
IDS = ["tx-7", "tx-8", "corr-3"]
KINDS = {"transaction": 2, "correction": 1}


def use_database(monkeypatch: MonkeyPatch):
    request = Mock(side_effect=[TRANSACTIONS, CATEGORIES, CORRECTIONS])
    monkeypatch.setattr(rag_corpus.chat_service, "database_request", request)
    return request


def test_build_documents_texts_and_stable_ids():
    ids, documents, metadatas = rag_corpus.build_documents(
        TRANSACTIONS,
        CATEGORIES,
        CORRECTIONS,
    )

    assert ids == IDS
    assert documents == [
        "Transaction 7 on 2026-06-24: Anytime Fitness Ultimo charged $17.50 "
        "for 'Direct debit membership fee'. Category: Fitness (want).",
        "Transaction 8 on 2026-07-01: Mystery Shop charged $12.00 "
        "for 'Card purchase'. Category: Uncategorised.",
        "Transaction 26 (Spotify AU, 'Monthly subscription') was "
        "recategorised from Uncategorised to Music subscriptions on "
        "2026-08-20.",
    ]
    assert len(metadatas) == 3


def test_fetch_and_build_uses_database_request_and_counts_kinds(
    monkeypatch: MonkeyPatch,
):
    request = use_database(monkeypatch)

    ids, documents, metadatas, kinds = rag_corpus.fetch_and_build(
        "http://db.test/",
    )

    assert [args.args[1] for args in request.call_args_list] == [
        "http://db.test/transactions",
        "http://db.test/categories",
        "http://db.test/category-corrections",
    ]
    assert ids == IDS
    assert len(documents) == len(metadatas) == 3
    assert kinds == KINDS


def test_refresh_records_pushes_documents_and_returns_summary(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(config, "RAG_RECORDS_COLLECTION", "transactions-records")
    use_database(monkeypatch)
    refresh = Mock(return_value={"feature": "transactions-records", "total": 3})
    monkeypatch.setattr(rag_corpus.rag_client, "refresh", refresh)

    summary = rag_corpus.refresh_records("http://db.test", "manual")

    assert summary["feature"] == "transactions-records"
    assert summary["total"] == 3
    assert summary["kinds"] == KINDS
    assert isinstance(summary["duration_ms"], float)
    assert refresh.call_args.args[0] == "transactions-records"
    assert refresh.call_args.args[1] == IDS


def test_refresh_with_retries_never_raises_and_returns_first_success(
    monkeypatch: MonkeyPatch,
):
    refresh = Mock(side_effect=[
        RAGError("rag_connection"),
        chat_service.ChatError("db down", "database_unavailable", 503),
        {"total": 1},
    ])
    monkeypatch.setattr(rag_corpus, "refresh_records", refresh)
    sleep = Mock()
    monkeypatch.setattr(rag_corpus.time, "sleep", sleep)

    result = rag_corpus.refresh_with_retries(
        "http://db.test",
        "startup",
        attempts=3,
        delay_seconds=3,
    )

    assert result == {"total": 1}
    assert refresh.call_count == 3
    assert sleep.call_args_list == [call(3), call(3)]

    refresh.side_effect = RAGError("rag_connection")
    assert rag_corpus.refresh_with_retries("http://db.test", "startup", 2) is None
    assert refresh.call_count == 5


def test_start_background_refresh_is_skipped_when_disabled(
    monkeypatch: MonkeyPatch,
):
    thread_class = Mock()
    monkeypatch.setattr(rag_corpus.threading, "Thread", thread_class)

    assert rag_corpus.start_background_refresh("http://db.test", "x") is None
    thread_class.assert_not_called()
