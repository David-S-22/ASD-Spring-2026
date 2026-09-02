"""Asynchronous transaction review queue.

Callers (e.g. the transactions backend) enqueue a transaction and get an
immediate acknowledgement, while a background worker performs the slow LLM
review and persists any anomaly it produces.
"""
import queue
import threading
from typing import Optional

from flask import Flask, current_app

from shared.backend import dto
from .services import anomalies_api, agent_api, transaction_api


transaction_queue: "queue.Queue[dto.Transaction]" = queue.Queue()


def enqueue(transaction: dto.Transaction) -> None:
    """Queue a transaction for asynchronous anomaly review."""
    transaction_queue.put(transaction)


def _process_transaction(transaction: dto.Transaction) -> Optional[dto.Anomaly]:
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
                _process_transaction(transaction)
        except Exception:
            app.logger.exception(
                "Failed to review queued transaction %s",
                getattr(transaction, "id", "unknown"))
        finally:
            transaction_queue.task_done()


def start_worker(app: Flask) -> threading.Thread:
    thread = threading.Thread(target=_worker, args=(app,), name="anomaly-worker", daemon=True)
    thread.start()
    return thread
