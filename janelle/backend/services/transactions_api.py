import requests

from .. import config


class InvalidDatabaseResponse(Exception):
	pass


def get_all_transactions():
	return _get_database_list("/transactions")


def get_all_categories():
	return _get_database_list("/categories")


def _get_database_list(path):
	response = requests.get(
		f"{config.TRANSACTIONS_DB_URL}{path}",
		timeout=config.DATABASE_TIMEOUT_SECONDS,
	)
	response.raise_for_status()
	try:
		payload = response.json()
	except requests.exceptions.JSONDecodeError as error:
		raise InvalidDatabaseResponse from error
	if not isinstance(payload, list) or not all(
		isinstance(item, dict) for item in payload
	):
		raise InvalidDatabaseResponse
	return payload
