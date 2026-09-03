"""Asynchronous transaction review queue.

Callers (e.g. the transactions backend) enqueue a transaction and get an
immediate acknowledgement, while a background worker performs the slow LLM
review and persists any anomaly it produces.

Each queued item is tracked by a key (its transaction id). A client can wait on
that key until the item has been reviewed and then find out whether it produced
an anomaly by looking it up in the anomalies database.
"""
import queue
import threading
from typing import Optional, Set

from flask import Flask, current_app

from shared.backend import dto
from . import anomalies_api, agent_api, transaction_api


transaction_queue: "queue.Queue[dto.Transaction]" = queue.Queue()

_state = threading.Condition()
# Keys (transaction ids) currently queued or being processed.
_pending: Set[int] = set()


def enqueue(transaction: dto.Transaction) -> int:
    """Queue a transaction for asynchronous review.

    Returns the item's key (its transaction id), which a client can later pass
    to ``wait_for_result`` / the ``/anomaly-alert`` endpoint.
    """
    key = transaction.id
    with _state:
        _pending.add(key)
    transaction_queue.put(transaction)
    return key


def is_pending(key: int) -> bool:
    """Return True if an item with this key is queued or still processing."""
    with _state:
        return key in _pending


def wait_for_result(key: int, timeout: float) -> Optional[dto.Anomaly]:
    """Wait until the item for ``key`` has been reviewed, then return its anomaly.

    Blocks until the transaction leaves the queue (or ``timeout`` elapses), then
    looks the transaction up in the anomalies database. Returns the anomaly that
    was created for it, or ``None`` if the review produced no anomaly, the key is
    unknown, or the wait timed out while the item was still being processed (the
    caller can re-poll).
    """
    with _state:
        _state.wait_for(lambda: key not in _pending, timeout=timeout)
    return _find_anomaly(key)


def _find_anomaly(key: int) -> Optional[dto.Anomaly]:
    return anomalies_api.get_anomaly_by_transaction_id(key)


def _mark_reviewed(key: int) -> None:
    with _state:
        _pending.discard(key)
        _state.notify_all()


def reset() -> None:
    """Clear queued state (used when the DB is reset in tests)."""
    with _state:
        _pending.clear()
        _state.notify_all()


def process_transaction(transaction: dto.Transaction) -> Optional[dto.Anomaly]:
    """Review a single transaction and persist any anomaly it produces.

    Must be called within an application context.
    """
    all_anomalies = anomalies_api.get_all_anomalies()
    all_transactions = transaction_api.get_all_transactions()

    current_app.logger.info(
        "Reviewing transaction %s (merchant=%r, amount=%s)",
        transaction.id, transaction.merchant, transaction.amount)
    anomaly = agent_api.review_new_transaction(transaction, all_anomalies, all_transactions)

    if anomaly is None:
        current_app.logger.info("Transaction %s cleared (no anomaly)", transaction.id)
        return None

    current_app.logger.warning(
        "Transaction %s flagged as anomalous: %s",
        transaction.id, anomaly.agent_reason_suspected)

    return anomalies_api.create_anomaly(anomaly)


def _worker(app: Flask) -> None:
    while True:
        transaction = transaction_queue.get()
        try:
            with app.app_context():
                process_transaction(transaction)
        except Exception:
            app.logger.exception(
                "Failed to review queued transaction %s",
                getattr(transaction, "id", "unknown"))
        finally:
            _mark_reviewed(transaction.id)
            transaction_queue.task_done()


def start_worker(app: Flask) -> threading.Thread:
    thread = threading.Thread(target=_worker, args=(app,), name="anomaly-worker", daemon=True)
    thread.start()
    return thread
