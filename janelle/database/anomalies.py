"""Cross-database cleanup of anomalies tied to a transaction lifecycle."""

import logging
import os

import requests


ANOMALIES_DB_URL = os.environ.get(
	"ANOMALIES_DB_URL",
	"http://anomalies-db:6004/anomalies",
).rstrip("/")
ANOMALIES_TIMEOUT_SECONDS = float(
	os.environ.get("ANOMALIES_TIMEOUT_SECONDS", "10")
)


def delete_anomaly_by_transaction_id(transaction_id):
	"""Remove the anomaly associated with a deleted transaction if present.

	Cleanup is best-effort: failures are logged and never propagated, so a
	problem reaching the anomalies database cannot fail a transaction delete.
	"""

	try:
		response = requests.delete(
			f"{ANOMALIES_DB_URL}/by-transaction/{transaction_id}",
			timeout=ANOMALIES_TIMEOUT_SECONDS,
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
