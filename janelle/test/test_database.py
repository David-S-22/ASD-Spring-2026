import sqlite3
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from flask.testing import FlaskClient
from pytest import fixture, mark, raises
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import janelle.database.seed as database_seed
from janelle.backend.services.chat_service import expected_transaction_header
from janelle.database.app import setup_app
from janelle.database.models import Category, CategoryCorrection, Transaction, db
from shared.backend import dto


SEED_CATEGORY_COUNT = 15
SEED_TRANSACTION_COUNT = 34
SEED_CORRECTION_COUNT = 3
MISSING_CATEGORY_ID = 9999


@fixture
def database_client(tmp_path: Path):
	database_path = tmp_path / "data" / "transactions.db"
	application = setup_app(str(database_path))
	application.config["TESTING"] = True

	with application.test_client() as client:
		yield client, database_path


def get_connection(database_path):
	connection = sqlite3.connect(database_path)
	connection.row_factory = sqlite3.Row
	connection.create_function(
		"casefold",
		1,
		lambda value: value.casefold() if isinstance(value, str) else value,
		deterministic=True,
	)
	connection.execute("PRAGMA foreign_keys = ON")
	return connection


def response_datetime(value):
	return parsedate_to_datetime(value).replace(tzinfo=None)


def transaction_payload(**overrides):
	payload = {
		"date": "2026-08-31T14:30:00",
		"merchant": "Atomic Cafe",
		"description": "Team lunch",
		"amount": 24.5,
		"category_id": 80,
	}
	payload.update(overrides)
	return payload


def test_index_identifies_database(database_client):
	client, _database_path = database_client

	response = client.get("/")

	assert response.status_code == 200
	assert response.get_json() == {"container": "transactions-db"}


def test_setup_creates_schema_indexes_and_foreign_keys(database_client):
	_client, database_path = database_client
	connection = get_connection(database_path)
	try:
		tables = {
			row["name"]
			for row in connection.execute(
				"SELECT name FROM sqlite_master WHERE type = 'table'"
			).fetchall()
		}
		indexes = {
			row["name"]
			for row in connection.execute(
				"SELECT name FROM sqlite_master WHERE type = 'index'"
			).fetchall()
		}
		transaction_columns = {
			row["name"]
			for row in connection.execute("PRAGMA table_info(transactions)").fetchall()
		}
		category_columns = {
			row["name"]
			for row in connection.execute("PRAGMA table_info(categories)").fetchall()
		}

		assert tables == {"categories", "transactions", "category_corrections"}
		assert {
			"idx_transactions_date",
			"idx_transactions_merchant_normalized",
			"idx_transactions_category_id",
			"idx_category_corrections_transaction_id",
			"idx_category_corrections_corrected_at",
			"uq_categories_name_normalized",
		} <= indexes
		assert transaction_columns == {
			"id",
			"date",
			"merchant",
			"description",
			"amount",
			"category_id",
			"created_at",
			"updated_at",
		}
		assert category_columns == {"id", "name", "type"}
		transaction_column_types = {
			row["name"]: row["type"]
			for row in connection.execute("PRAGMA table_info(transactions)").fetchall()
		}
		assert transaction_column_types["id"] == "INTEGER"
		assert transaction_column_types["date"] == "DATETIME"
		assert transaction_column_types["category_id"] == "INTEGER"
		assert transaction_column_types["created_at"] == "DATETIME"
		assert transaction_column_types["updated_at"] == "DATETIME"
		category_column_types = {
			row["name"]: row["type"]
			for row in connection.execute("PRAGMA table_info(categories)").fetchall()
		}
		assert category_column_types["id"] == "INTEGER"
		correction_column_types = {
			row["name"]: row["type"]
			for row in connection.execute(
				"PRAGMA table_info(category_corrections)"
			).fetchall()
		}
		assert correction_column_types["transaction_id"] == "INTEGER"
		assert correction_column_types["previous_category_id"] == "INTEGER"
		assert correction_column_types["user_category_id"] == "INTEGER"
		assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
	finally:
		connection.close()


def test_transactions_return_seeded_public_contract_in_newest_first_order(
	database_client,
):
	client, database_path = database_client

	response = client.get("/transactions")

	assert response.status_code == 200
	transactions = response.get_json()
	assert len(transactions) == SEED_TRANSACTION_COUNT
	connection = get_connection(database_path)
	try:
		expected_ids = [
			row["id"]
			for row in connection.execute(
				"""
				SELECT id
				FROM transactions
				ORDER BY date DESC, created_at DESC, id DESC
				"""
			).fetchall()
		]
	finally:
		connection.close()
	assert [row["id"] for row in transactions] == expected_ids
	assert all(isinstance(row["category_id"], int) for row in transactions)
	assert set(transactions[0]) == {
		"id",
		"date",
		"merchant",
		"description",
		"amount",
		"category_id",
	}
	assert transactions[0]["merchant"] == "Merivale"
	assert response_datetime(transactions[0]["date"]) == datetime(2026, 8, 30)
	assert database_path.is_file()


def test_seed_endpoint_is_not_exposed(database_client):
	client, _database_path = database_client

	assert client.post("/seed").status_code == 404


def test_startup_does_not_reseed_a_database_that_contains_data(database_client):
	client, database_path = database_client
	transactions = client.get("/transactions").get_json()
	deleted_ids = [
		next(
			row["id"]
			for row in transactions
			if row["merchant"] == merchant
		)
		for merchant in ("Sydney Trains", "Woolworths")
	]
	for transaction_id in deleted_ids:
		assert client.delete(f"/transactions/{transaction_id}").status_code == 204

	first_user_row = client.post(
		"/transactions",
		json=transaction_payload(merchant="Replacement One"),
	).get_json()
	second_user_row = client.post(
		"/transactions",
		json=transaction_payload(merchant="Replacement Two"),
	).get_json()
	assert isinstance(first_user_row["id"], int)
	assert isinstance(second_user_row["id"], int)
	assert first_user_row["id"] != second_user_row["id"]

	setup_app(str(database_path))

	for transaction_id in deleted_ids:
		assert client.get(f"/transactions/{transaction_id}").status_code == 404
	assert client.get(
		f"/transactions/{first_user_row['id']}"
	).get_json()["merchant"] == "Replacement One"
	assert client.get(
		f"/transactions/{second_user_row['id']}"
	).get_json()["merchant"] == "Replacement Two"
	connection = get_connection(database_path)
	try:
		assert connection.execute(
			"SELECT COUNT(*) FROM category_corrections WHERE transaction_id = ?",
			(deleted_ids[0],),
		).fetchone()[0] == 0
	finally:
		connection.close()


def test_startup_seed_skips_a_partially_populated_database(tmp_path):
	database_path = tmp_path / "partial-data" / "transactions.db"
	database_path.parent.mkdir(parents=True)
	category_id = 99
	engine = create_engine(f"sqlite:///{database_path.as_posix()}")
	try:
		db.metadata.create_all(engine)
		with engine.begin() as connection:
			connection.exec_driver_sql(
				"""
				INSERT INTO categories (id, name, type)
				VALUES (?, 'User category', 'want')
				""",
				(category_id,),
			)
	finally:
		engine.dispose()

	application = setup_app(str(database_path))
	with application.test_client() as client:
		assert client.get("/categories").get_json() == [
			{"id": category_id, "name": "User category", "type": "want"}
		]
		assert client.get("/transactions").get_json() == []
		assert client.get("/category-corrections").get_json() == []


def test_transaction_crud_round_trip(database_client):
	client, _database_path = database_client

	create_response = client.post("/transactions", json=transaction_payload())

	assert create_response.status_code == 201
	created = create_response.get_json()
	assert isinstance(created["id"], int)
	assert created["amount"] == 24.5
	assert response_datetime(created["date"]) == datetime(2026, 8, 31, 14, 30)
	assert created["category_id"] == 80
	assert set(created) == {
		"id",
		"amount",
		"merchant",
		"date",
		"description",
		"category_id",
	}

	get_response = client.get(f"/transactions/{created['id']}")
	assert get_response.status_code == 200
	assert get_response.get_json() == created

	update_response = client.patch(
		f"/transactions/{created['id']}",
		json={
			"merchant": "Atomic Coffee",
			"amount": 27.5,
		},
	)
	assert update_response.status_code == 200
	updated = update_response.get_json()
	assert updated["merchant"] == "Atomic Coffee"
	assert updated["amount"] == 27.5

	delete_response = client.delete(f"/transactions/{created['id']}")
	assert delete_response.status_code == 204
	assert client.get(f"/transactions/{created['id']}").status_code == 404


def test_transaction_datetime_uses_shared_dto_serialization(database_client):
	client, _database_path = database_client

	response = client.post(
		"/transactions",
		json=transaction_payload(date="2026-09-01T10:15:30+10:00"),
	)

	assert response.status_code == 201
	assert response_datetime(response.get_json()["date"]) == datetime(
		2026,
		9,
		1,
		0,
		15,
		30,
	)


def test_conditional_transaction_update_is_atomic(database_client):
	client, _database_path = database_client
	created = client.post(
		"/transactions",
		json=transaction_payload(
			date="2026-09-01T10:15:30.123456",
			merchant="Conditional update",
		),
	).get_json()
	versioned = client.get(
		f"/transactions/{created['id']}?_include_version=true"
	).get_json()
	header = expected_transaction_header(versioned)

	response = client.patch(
		f"/transactions/{created['id']}",
		json={"amount": 30},
		headers={"X-Expected-Transaction": header},
	)

	assert response.status_code == 200
	assert response.get_json()["amount"] == 30


def test_conditional_update_rejects_raced_transaction(database_client):
	client, _database_path = database_client
	created = client.post(
		"/transactions",
		json=transaction_payload(merchant="Raced update"),
	).get_json()
	versioned = client.get(
		f"/transactions/{created['id']}?_include_version=true"
	).get_json()
	stale_header = expected_transaction_header(versioned)
	assert client.patch(
		f"/transactions/{created['id']}",
		json={"amount": 30},
	).status_code == 200

	response = client.patch(
		f"/transactions/{created['id']}",
		json={"amount": 40},
		headers={"X-Expected-Transaction": stale_header},
	)

	assert response.status_code == 409
	assert response.get_json()["code"] == "stale_preview"
	assert client.get(
		f"/transactions/{created['id']}"
	).get_json()["amount"] == 30


def test_conditional_delete_rejects_raced_transaction(database_client):
	client, _database_path = database_client
	created = client.post(
		"/transactions",
		json=transaction_payload(merchant="Raced delete"),
	).get_json()
	versioned = client.get(
		f"/transactions/{created['id']}?_include_version=true"
	).get_json()
	stale_header = expected_transaction_header(versioned)
	assert client.patch(
		f"/transactions/{created['id']}",
		json={"description": "Changed after preview"},
	).status_code == 200

	response = client.delete(
		f"/transactions/{created['id']}",
		headers={"X-Expected-Transaction": stale_header},
	)

	assert response.status_code == 409
	assert response.get_json()["code"] == "stale_preview"
	assert client.get(f"/transactions/{created['id']}").status_code == 200


def test_transaction_create_records_ai_category_override_atomically(
	database_client,
):
	client, database_path = database_client

	response = client.post(
		"/transactions",
		json=transaction_payload(
			merchant="AI category override",
			category_id=81,
			suggested_category_id=80,
		),
	)

	assert response.status_code == 201
	created = response.get_json()
	assert created["category_id"] == 81
	assert "suggested_category_id" not in created

	connection = get_connection(database_path)
	try:
		correction = connection.execute(
			"""
			SELECT previous_category_id, user_category_id
			FROM category_corrections
			WHERE transaction_id = ?
			""",
			(created["id"],),
		).fetchone()
		assert dict(correction) == {
			"previous_category_id": 80,
			"user_category_id": 81,
		}
	finally:
		connection.close()


def test_transaction_create_does_not_record_accepted_ai_suggestion(
	database_client,
):
	client, database_path = database_client

	response = client.post(
		"/transactions",
		json=transaction_payload(suggested_category_id=80),
	)

	assert response.status_code == 201
	created = response.get_json()
	connection = get_connection(database_path)
	try:
		assert connection.execute(
			"""
			SELECT COUNT(*)
			FROM category_corrections
			WHERE transaction_id = ?
			""",
			(created["id"],),
		).fetchone()[0] == 0
	finally:
		connection.close()


def test_transaction_create_rejects_invalid_ai_suggestion_without_insert(
	database_client,
):
	client, database_path = database_client
	connection = get_connection(database_path)
	try:
		before = connection.execute(
			"SELECT COUNT(*) FROM transactions"
		).fetchone()[0]
	finally:
		connection.close()

	response = client.post(
		"/transactions",
		json=transaction_payload(
			merchant="Invalid AI suggestion",
			suggested_category_id=MISSING_CATEGORY_ID,
		),
	)

	assert response.status_code == 422
	assert response.get_json()["code"] == "category_not_found"
	connection = get_connection(database_path)
	try:
		assert connection.execute(
			"SELECT COUNT(*) FROM transactions"
		).fetchone()[0] == before
	finally:
		connection.close()


def test_transaction_update_rejects_create_only_ai_suggestion(
	database_client,
):
	client, _database_path = database_client
	created = client.post(
		"/transactions",
		json=transaction_payload(),
	).get_json()

	response = client.patch(
		f"/transactions/{created['id']}",
		json={"suggested_category_id": 81},
	)

	assert response.status_code == 422
	assert response.get_json()["code"] == "unsupported_fields"


def test_failed_ai_correction_insert_rolls_back_transaction(
	database_client,
	monkeypatch,
):
	client, database_path = database_client
	original_add = db.session.add

	def fail_correction_add(instance):
		if isinstance(instance, CategoryCorrection):
			raise SQLAlchemyError("correction insert failed")
		return original_add(instance)

	monkeypatch.setattr(db.session, "add", fail_correction_add)

	response = client.post(
		"/transactions",
		json=transaction_payload(
			merchant="Rolled back AI transaction",
			category_id=81,
			suggested_category_id=80,
		),
	)

	assert response.status_code == 503
	assert response.get_json()["code"] == "database_unavailable"
	connection = get_connection(database_path)
	try:
		assert connection.execute(
			"""
			SELECT COUNT(*)
			FROM transactions
			WHERE merchant = 'Rolled back AI transaction'
			"""
		).fetchone()[0] == 0
	finally:
		connection.close()


def test_transaction_model_uses_shared_transaction_dto(database_client):
	client, _database_path = database_client

	with client.application.app_context():
		transaction = db.session.get(Transaction, 1)
		assert isinstance(transaction.date, datetime)
		assert isinstance(transaction.created_at, datetime)
		assert isinstance(transaction.updated_at, datetime)
		transaction_dto = transaction.to_dto()

	assert isinstance(transaction_dto, dto.Transaction)
	assert transaction_dto.id == 1
	assert transaction_dto.date == datetime(2026, 6, 10)
	assert transaction_dto.amount == 1100.0
	assert transaction_dto.category_id == 30


def test_shared_transaction_dto_retains_original_constructor():
	transaction_id = 123
	category_id = 80

	transaction = dto.Transaction(
		transaction_id,
		12.5,
		"Legacy consumer",
		datetime(2026, 8, 31),
		"Purchase",
		category_id,
	)

	assert transaction.id == transaction_id
	assert transaction.amount == 12.5
	assert transaction.date == datetime(2026, 8, 31)
	assert transaction.description == "Purchase"
	assert transaction.category_id == category_id


@mark.parametrize(
	("payload", "code"),
	[
		(transaction_payload(date="31-08-2026"), "invalid_date"),
		(transaction_payload(amount=12.345), "invalid_amount"),
		(
			transaction_payload(category_id=MISSING_CATEGORY_ID),
			"category_not_found",
		),
		(transaction_payload(unexpected=True), "unsupported_fields"),
	],
)
def test_transaction_create_rejects_invalid_values(
	database_client,
	payload,
	code,
):
	client, _database_path = database_client

	response = client.post("/transactions", json=payload)

	assert response.status_code == 422
	assert response.get_json()["code"] == code


def test_transaction_create_rejects_removed_amount_cents_field(database_client):
	client, _database_path = database_client
	payload = transaction_payload(amount_cents=999)

	response = client.post("/transactions", json=payload)

	assert response.status_code == 422
	assert response.get_json()["code"] == "unsupported_fields"


def test_transaction_routes_return_json_for_malformed_requests(database_client):
	client, _database_path = database_client

	response = client.post(
		"/transactions",
		data="{",
		content_type="application/json",
	)

	assert response.status_code == 400
	assert response.get_json()["code"] == "invalid_json"


def test_transaction_routes_reject_excessively_nested_json(database_client):
	client, _database_path = database_client
	payload = ("[" * 5000) + "0" + ("]" * 5000)

	response = client.post(
		"/transactions",
		data=payload,
		content_type="application/json",
	)

	assert response.status_code == 400
	assert response.get_json()["code"] == "invalid_json"


def test_transaction_filters_work_alone_and_in_combination(database_client):
	client, _database_path = database_client

	spotify = client.get("/transactions?merchant=spotify au").get_json()
	assert len(spotify) == 3
	assert all(row["merchant"] == "Spotify AU" for row in spotify)

	search = client.get("/transactions?q=premium").get_json()
	assert len(search) == 2
	assert all("premium" in row["description"].lower() for row in search)

	date_range = client.get(
		"/transactions?date_from=2026-08-20&date_to=2026-08-26"
	).get_json()
	assert date_range
	assert all(
		datetime(2026, 8, 20)
		<= response_datetime(row["date"])
		<= datetime(2026, 8, 26, 23, 59, 59, 999999)
		for row in date_range
	)

	since = client.get("/transactions?since=2026-08-25").get_json()
	assert since
	assert all(
		response_datetime(row["date"]) >= datetime(2026, 8, 25)
		for row in since
	)

	dining = client.get("/transactions?category_id=80").get_json()
	assert len(dining) == 5
	assert all(row["category_id"] == 80 for row in dining)

	client.post(
		"/transactions",
		json=transaction_payload(merchant="Spotify AU Family"),
	)
	exact_spotify = client.get("/transactions?merchant=Spotify AU").get_json()
	assert len(exact_spotify) == 3
	assert all(row["merchant"] == "Spotify AU" for row in exact_spotify)

	client.post(
		"/transactions",
		json=transaction_payload(merchant="CAF\u00c9 Central"),
	)
	unicode_merchant = client.get(
		"/transactions",
		query_string={"merchant": "caf\u00e9 central"},
	).get_json()
	assert len(unicode_merchant) == 1
	assert unicode_merchant[0]["merchant"] == "CAF\u00c9 Central"

	amount_range = client.get(
		"/transactions?min_amount=20&max_amount=50"
	).get_json()
	assert amount_range
	assert all(20 <= row["amount"] <= 50 for row in amount_range)

	combined = client.get(
		"/transactions",
		query_string={
			"merchant": "MERIVALE",
			"category_id": 80,
			"date_from": "2026-08-10",
			"date_to": "2026-08-31",
			"min_amount": "50",
			"max_amount": "90",
		},
	).get_json()
	assert len(combined) == 1
	assert combined[0]["merchant"] == "Merivale"
	assert response_datetime(combined[0]["date"]) == datetime(2026, 8, 30)


def test_date_only_filter_includes_the_entire_day(database_client):
	client, _database_path = database_client
	created = client.post(
		"/transactions",
		json=transaction_payload(
			date="2026-09-01T23:59:59.999999",
			merchant="Late purchase",
		),
	).get_json()

	whole_day = client.get(
		"/transactions",
		query_string={
			"merchant": "Late purchase",
			"date_from": "2026-09-01",
			"date_to": "2026-09-01",
		},
	).get_json()
	before_purchase = client.get(
		"/transactions",
		query_string={
			"merchant": "Late purchase",
			"date_to": "2026-09-01T23:59:59",
		},
	).get_json()

	assert [row["id"] for row in whole_day] == [created["id"]]
	assert before_purchase == []


@mark.parametrize(
	"url",
	[
		"/transactions?date_from=not-a-date",
		"/transactions?date_from=2026-09-01&date_to=2026-08-01",
		"/transactions?category_id=abc",
		"/transactions?min_amount=20&max_amount=10",
		"/transactions?min_amount=1.001",
	],
)
def test_transaction_filters_reject_invalid_query_values(database_client, url):
	client, _database_path = database_client

	response = client.get(url)

	assert response.status_code == 400
	assert response.get_json()["code"] == "invalid_query"


def test_category_crud_round_trip_and_case_insensitive_uniqueness(database_client):
	client, _database_path = database_client

	create_response = client.post(
		"/categories",
		json={"name": "Education", "type": "saving"},
	)
	assert create_response.status_code == 201
	created = create_response.get_json()

	assert client.get(f"/categories/{created['id']}").get_json() == created

	update_response = client.patch(
		f"/categories/{created['id']}",
		json={"name": "Learning", "type": "want"},
	)
	assert update_response.status_code == 200
	assert update_response.get_json()["name"] == "Learning"
	assert update_response.get_json()["type"] == "want"

	conflict_response = client.post(
		"/categories",
		json={"name": "learning", "type": "want"},
	)
	assert conflict_response.status_code == 409
	assert conflict_response.get_json()["code"] == "category_name_conflict"

	delete_response = client.delete(f"/categories/{created['id']}")
	assert delete_response.status_code == 204
	assert client.get(f"/categories/{created['id']}").status_code == 404

	unicode_category = client.post(
		"/categories",
		json={"name": "CAF\u00c9", "type": "want"},
	)
	assert unicode_category.status_code == 201
	unicode_conflict = client.post(
		"/categories",
		json={"name": "caf\u00e9", "type": "want"},
	)
	assert unicode_conflict.status_code == 409
	assert unicode_conflict.get_json()["code"] == "category_name_conflict"


def test_category_model_uses_shared_category_dto(database_client):
	client, _database_path = database_client

	with client.application.app_context():
		category = db.session.get(Category, 80)
		category_dto = category.to_dto()

	assert isinstance(category_dto, dto.Category)
	assert category_dto == dto.Category(
		id=80,
		name="Dining",
		type="want",
	)


def test_categories_reject_invalid_type_and_unsafe_deletion(database_client):
	client, _database_path = database_client

	invalid_type = client.post(
		"/categories",
		json={"name": "Invalid", "type": "other"},
	)
	assert invalid_type.status_code == 422
	assert invalid_type.get_json()["code"] == "invalid_category_type"

	protected_category_id = 1
	protected_delete = client.delete(f"/categories/{protected_category_id}")
	assert protected_delete.status_code == 409
	assert protected_delete.get_json()["code"] == "protected_category"

	protected_patch = client.patch(
		f"/categories/{protected_category_id}",
		json={"name": "Other"},
	)
	assert protected_patch.status_code == 409
	assert protected_patch.get_json()["code"] == "protected_category"

	in_use = client.delete("/categories/80")
	assert in_use.status_code == 409
	assert in_use.get_json()["code"] == "category_in_use"


def test_database_constraint_conflicts_return_409(database_client):
	client, database_path = database_client
	category = client.post(
		"/categories",
		json={"name": "Concurrent category", "type": "want"},
	).get_json()
	connection = get_connection(database_path)
	try:
		connection.execute(
			f"""
			CREATE TRIGGER reference_category_before_delete
			BEFORE DELETE ON categories
			WHEN OLD.id = {category["id"]}
			BEGIN
				INSERT INTO transactions (
					id,
					date,
					merchant,
					description,
					amount,
					category_id,
					created_at,
					updated_at
				)
				VALUES (
					999999,
					'2026-08-31',
					'Concurrent writer',
					'Late category reference',
					1.00,
					OLD.id,
					'2026-08-31T00:00:00+00:00',
					'2026-08-31T00:00:00+00:00'
				);
			END
			"""
		)
		connection.commit()
	finally:
		connection.close()

	response = client.delete(f"/categories/{category['id']}")

	assert response.status_code == 409
	assert response.get_json()["code"] == "database_conflict"
	assert client.get(f"/categories/{category['id']}").status_code == 200


def test_category_type_rejects_non_scalar_json(database_client):
	client, _database_path = database_client

	response = client.post(
		"/categories",
		json={"name": "Invalid", "type": []},
	)

	assert response.status_code == 422
	assert response.get_json()["code"] == "invalid_category_type"


@mark.parametrize(
	("endpoint", "payload", "code"),
	[
		(
			"/transactions",
			transaction_payload(merchant="\ud800"),
			"invalid_merchant",
		),
		(
			"/categories",
			{"name": "\ud800", "type": "want"},
			"invalid_name",
		),
	],
)
def test_text_fields_reject_unpaired_unicode_surrogates(
	database_client,
	endpoint,
	payload,
	code,
):
	client, _database_path = database_client

	response = client.post(endpoint, json=payload)

	assert response.status_code == 422
	assert response.get_json()["code"] == code


def test_category_correction_records_and_applies_atomically(database_client):
	client, database_path = database_client
	created = client.post("/transactions", json=transaction_payload()).get_json()

	response = client.post(
		f"/transactions/{created['id']}/category-correction",
		json={"category_id": 81},
	)

	assert response.status_code == 201
	result = response.get_json()
	assert result["transaction"]["category_id"] == 81
	assert set(result["transaction"]) == {
		"id",
		"amount",
		"merchant",
		"date",
		"description",
		"category_id",
	}
	assert result["correction"]["previous_category_id"] == 80
	assert result["correction"]["previous_category_name"] == "Dining"
	assert result["correction"]["user_category_id"] == 81
	assert result["correction"]["user_category_name"] == "Groceries"

	connection = get_connection(database_path)
	try:
		stored = connection.execute(
			"SELECT category_id FROM transactions WHERE id = ?",
			(created["id"],),
		).fetchone()
		correction = connection.execute(
			"""
			SELECT previous_category_id, user_category_id
			FROM category_corrections
			WHERE transaction_id = ?
			""",
			(created["id"],),
		).fetchone()
		assert dict(stored) == {"category_id": 81}
		assert dict(correction) == {
			"previous_category_id": 80,
			"user_category_id": 81,
		}
	finally:
		connection.close()

	assert client.delete(f"/transactions/{created['id']}").status_code == 204
	connection = get_connection(database_path)
	try:
		assert connection.execute(
			"SELECT COUNT(*) FROM category_corrections WHERE transaction_id = ?",
			(created["id"],),
		).fetchone()[0] == 0
	finally:
		connection.close()


def test_failed_category_correction_leaves_transaction_unchanged(database_client):
	client, database_path = database_client
	created = client.post(
		"/transactions",
		json=transaction_payload(merchant="Manual Category"),
	).get_json()

	response = client.post(
		f"/transactions/{created['id']}/category-correction",
		json={"category_id": MISSING_CATEGORY_ID},
	)

	assert response.status_code == 422
	assert response.get_json()["code"] == "category_not_found"
	connection = get_connection(database_path)
	try:
		assert connection.execute(
			"SELECT category_id FROM transactions WHERE id = ?",
			(created["id"],),
		).fetchone()["category_id"] == 80
		assert connection.execute(
			"SELECT COUNT(*) FROM category_corrections WHERE transaction_id = ?",
			(created["id"],),
		).fetchone()[0] == 0
	finally:
		connection.close()


def test_category_corrections_can_be_filtered_by_merchant_and_limit(database_client):
	client, _database_path = database_client

	response = client.get("/category-corrections?merchant=merivale&limit=1")

	assert response.status_code == 200
	corrections = response.get_json()
	assert len(corrections) == 1
	assert corrections[0]["merchant"] == "Merivale"
	assert corrections[0]["previous_category_name"] == "Uncategorised"
	assert corrections[0]["user_category_name"] == "Dining"


def test_database_connection_enforces_foreign_keys(database_client):
	_client, database_path = database_client
	connection = get_connection(database_path)
	try:
		with raises(sqlite3.IntegrityError):
			connection.execute(
				"""
				INSERT INTO transactions (
					id,
					date,
					merchant,
					description,
					amount,
					category_id,
					created_at,
					updated_at
				)
				VALUES (
					?,
					'2026-08-31',
					'Invalid',
					'Missing category',
					1.00,
					?,
					'2026-08-31T00:00:00+00:00',
					'2026-08-31T00:00:00+00:00'
				)
				""",
				(999999, MISSING_CATEGORY_ID),
			)
		connection.rollback()
	finally:
		connection.close()


def test_setup_preserves_user_data_without_duplicating_seed(database_client):
	client, database_path = database_client
	created = client.post("/transactions", json=transaction_payload()).get_json()

	setup_app(str(database_path))

	assert client.get(f"/transactions/{created['id']}").status_code == 200
	assert len(client.get("/transactions").get_json()) == SEED_TRANSACTION_COUNT + 1


def test_startup_seed_rolls_back_when_any_seed_row_is_invalid(
	tmp_path,
	monkeypatch,
):
	database_path = tmp_path / "partial-seed" / "transactions.db"
	invalid_transaction = (
		999,
		"2026-09-01",
		"Invalid seed row",
		"Missing category",
		"10.00",
		9999,
		"2026-09-01T00:00:00+00:00",
		"2026-09-01T00:00:00+00:00",
	)
	monkeypatch.setattr(
		database_seed,
		"TRANSACTIONS",
		database_seed.TRANSACTIONS + (invalid_transaction,),
	)

	with raises(IntegrityError):
		setup_app(str(database_path))

	connection = get_connection(database_path)
	try:
		for table in ("categories", "transactions", "category_corrections"):
			assert connection.execute(
				f"SELECT COUNT(*) FROM {table}"
			).fetchone()[0] == 0
	finally:
		connection.close()


@mark.parametrize(
	("method", "url", "payload", "status"),
	[
		(
			"post",
			"/transactions",
			transaction_payload(category_id=9223372036854775808),
			422,
		),
		("get", "/transactions?category_id=9223372036854775808", None, 400),
		("get", "/transactions?min_amount=1e999999", None, 400),
		("get", "/transactions/9223372036854775808", None, 404),
		("get", f"/transactions/{'9' * 5000}", None, 404),
		("get", "/categories/9223372036854775808", None, 404),
	],
)
def test_numeric_overflow_respects_error_contract(
	database_client,
	method,
	url,
	payload,
	status,
):
	client, _database_path = database_client

	response = getattr(client, method)(url, json=payload)

	assert response.status_code == status
	assert response.is_json


def test_transactions_report_unavailable_database(database_client):
	client, database_path = database_client
	with client.application.app_context():
		db.session.remove()
		db.engine.dispose()
	database_path.unlink()
	database_path.mkdir()

	response = client.get("/transactions")

	assert response.status_code == 503
	assert response.get_json() == {
		"error": "database unavailable",
		"code": "database_unavailable",
	}
