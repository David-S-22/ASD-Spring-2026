"""Requests to the anomalies database related to transaction lifecycle."""

import logging

import requests

from .. import config


def delete_anomaly_by_transaction_id(transaction_id: int) -> None:
    """Remove the anomaly associated with a deleted transaction if present."""
    try:
        response = requests.delete(
            f"{config.ANOMALIES_DB_URL}/by-transaction/{transaction_id}",
            timeout=config.ANOMALIES_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        logging.getLogger(__name__).warning(
            "Anomaly cleanup request failed for transaction %s: %s",
            transaction_id,
            error,
        )
        return

    if response.status_code >= 400:
        logging.getLogger(__name__).warning(
            "Anomaly cleanup returned %s for transaction %s: %s",
            response.status_code,
            transaction_id,
            response.text,
        )
