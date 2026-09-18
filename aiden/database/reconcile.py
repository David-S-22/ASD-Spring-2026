"""Startup reconciliation for orphaned anomalies.

When the container starts, the transactions database is polled for the full set
of transaction IDs. Any anomaly that references a transaction which no longer
exists is deleted, keeping the two independent databases logically consistent.
"""

import logging
import threading
import time
from typing import Optional, Set

import requests
from flask import Flask
from sqlalchemy import select

from .app import app
from .config import config
from .models import Anomaly, db


logger = logging.getLogger(__name__)


def _fetch_transaction_ids(base_url: str, timeout: float) -> Set[int]:
    response = requests.get(f"{base_url}/transactions", timeout=timeout)
    response.raise_for_status()

    return {int(item["id"]) for item in response.json()}


def fetch_transaction_ids_with_retry(
    base_url: str,
    timeout: float,
    retries: int,
    retry_delay: float,
) -> Optional[Set[int]]:
    """Poll the transactions database until it responds or retries are exhausted.

    Returns the set of transaction IDs, or None if the database could not be
    reached. An empty set is a valid result meaning there are no transactions.
    """

    for attempt in range(1, retries + 1):
        try:
            return _fetch_transaction_ids(base_url, timeout)
        except requests.RequestException as error:
            logger.warning(
                "Could not reach transactions database (attempt %s/%s): %s",
                attempt,
                retries,
                error,
            )

            if attempt < retries:
                time.sleep(retry_delay)

    return None


def remove_orphaned_anomalies(transaction_ids: Set[int]) -> int:
    """Delete anomalies whose transaction no longer exists. Returns the count removed."""

    with app.app_context():
        anomalies = db.session.scalars(select(Anomaly)).all()
        orphaned = [a for a in anomalies if a.transaction_id not in transaction_ids]

        for anomaly in orphaned:
            db.session.delete(anomaly)

        if orphaned:
            db.session.commit()

        return len(orphaned)


def reconcile_anomalies() -> None:
    """Best-effort removal of orphaned anomalies at startup.

    Failures to reach the transactions database are logged and skipped rather
    than crashing the container.
    """

    base_url = config.TRANSACTIONS_DB_URL.rstrip("/")
    timeout = config.TRANSACTIONS_TIMEOUT_SECONDS
    retries = config.RECONCILE_MAX_RETRIES
    retry_delay = config.RECONCILE_RETRY_DELAY_SECONDS

    transaction_ids = fetch_transaction_ids_with_retry(
        base_url, timeout, retries, retry_delay
    )

    if transaction_ids is None:
        logger.error(
            "Skipping anomaly reconciliation; transactions database unreachable"
        )
        return

    removed = remove_orphaned_anomalies(transaction_ids)
    logger.info(
        "Anomaly reconciliation complete; removed %s orphaned anomalies", removed
    )


def start_reconcile(app: Flask) -> threading.Thread:
    thread = threading.Thread(
        target=reconcile_anomalies, name="anomaly-reconcile", daemon=True
    )
    thread.start()
    app.logger.info("Started anomaly reconciliation thread %r", thread.name)
    return thread
