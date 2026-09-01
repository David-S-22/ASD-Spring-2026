import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from flask import Flask, jsonify, request
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import BadRequest, HTTPException

from .helpers import (
	category_corrections,
	category_is_in_use,
	category_name_exists,
	filtered_transactions,
)
from .models import Category, CategoryCorrection, Transaction, db
from .seed import seed_database_if_empty
from .validation import (
	ApiError,
	parse_query_positive_integer,
	parse_transaction_filters,
	validate_category_payload,
	validate_correction_payload,
	validate_transaction_payload,
	validate_uuid_identifier,
)


PROTECTED_CATEGORY_NAME = "Uncategorised"


def _database_uri(database_path):
	if database_path == ":memory:":
		return "sqlite:///:memory:"
	path = Path(database_path).resolve()
	path.parent.mkdir(parents=True, exist_ok=True)
	return f"sqlite:///{path.as_posix()}"


def _utc_datetime():
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _json_body():
	if not request.is_json:
		raise ApiError(
			"request body must be a JSON object",
			"invalid_json",
			400,
		)
	try:
		payload = request.get_json()
	except (BadRequest, RecursionError) as error:
		raise ApiError("request body contains invalid JSON", "invalid_json", 400) from error
	if not isinstance(payload, dict):
		raise ApiError(
			"request body must be a JSON object",
			"invalid_json",
			400,
		)
	return payload


def _require_category(category_id):
	category = db.session.get(Category, category_id)
	if category is None:
		raise ApiError("category not found", "category_not_found", 422)
	return category


def _resolve_transaction(transaction_identifier):
	try:
		transaction_id = UUID(transaction_identifier)
	except (TypeError, ValueError, AttributeError):
		raise ApiError(
			"transaction not found",
			"transaction_not_found",
			404,
		)

	transaction = db.session.get(Transaction, transaction_id)
	if transaction is None:
		raise ApiError("transaction not found", "transaction_not_found", 404)
	return transaction


def _apply_transaction_values(transaction, values):
	for field in ("date", "merchant", "description", "amount"):
		if field in values:
			setattr(transaction, field, values[field])
	if "category_id" in values:
		transaction.category = _require_category(values["category_id"])
	transaction.updated_at = _utc_datetime()


def _register_error_handlers(application):
	@application.errorhandler(ApiError)
	def handle_api_error(error):
		db.session.rollback()
		return jsonify(error=error.message, code=error.code), error.status

	@application.errorhandler(IntegrityError)
	def handle_integrity_error(_error):
		db.session.rollback()
		return jsonify(
			error="database constraint conflict",
			code="database_conflict",
		), 409

	@application.errorhandler(SQLAlchemyError)
	def handle_database_error(error):
		db.session.rollback()
		application.logger.exception("Transactions database operation failed")
		return jsonify(
			error="database unavailable",
			code="database_unavailable",
		), 503

	@application.errorhandler(HTTPException)
	def handle_http_error(error):
		code = error.name.lower().replace(" ", "_")
		return jsonify(error=error.description, code=code), error.code


def _register_routes(application):
	@application.get("/")
	def get_index():
		return jsonify(container="transactions-db")

	@application.get("/transactions")
	def get_transactions():
		transactions = filtered_transactions(
			parse_transaction_filters(request.args)
		)
		return jsonify([transaction.to_dto() for transaction in transactions])

	@application.post("/transactions")
	def post_transaction():
		values = validate_transaction_payload(_json_body())
		now = _utc_datetime()
		transaction = Transaction(
			date=values["date"],
			merchant=values["merchant"],
			description=values["description"],
			amount=values["amount"],
			category=_require_category(values["category_id"]),
			created_at=now,
			updated_at=now,
		)
		db.session.add(transaction)
		db.session.commit()
		return jsonify(transaction.to_dto()), 201

	@application.get("/transactions/<transaction_id>")
	def get_transaction(transaction_id):
		transaction = _resolve_transaction(transaction_id)
		return jsonify(transaction.to_dto())

	@application.patch("/transactions/<transaction_id>")
	def patch_transaction(transaction_id):
		transaction = _resolve_transaction(transaction_id)
		values = validate_transaction_payload(_json_body(), partial=True)
		_apply_transaction_values(transaction, values)
		db.session.commit()
		return jsonify(transaction.to_dto())

	@application.delete("/transactions/<transaction_id>")
	def delete_transaction(transaction_id):
		db.session.delete(_resolve_transaction(transaction_id))
		db.session.commit()
		return "", 204

	@application.post("/transactions/<transaction_id>/category-correction")
	def post_category_correction(transaction_id):
		user_category_id = validate_correction_payload(_json_body())
		transaction = _resolve_transaction(transaction_id)
		user_category = _require_category(user_category_id)
		now = _utc_datetime()
		correction = CategoryCorrection(
			transaction=transaction,
			previous_category=transaction.category,
			user_category=user_category,
			corrected_at=now.isoformat(),
		)
		transaction.category = user_category
		transaction.updated_at = now
		db.session.add(correction)
		db.session.commit()
		return jsonify(
			transaction=transaction.to_dto(),
			correction=correction.to_dict(),
		), 201

	@application.get("/categories")
	def get_categories():
		protected_first = case(
			(
				func.casefold(Category.name) == PROTECTED_CATEGORY_NAME.casefold(),
				0,
			),
			else_=1,
		)
		categories = db.session.scalars(
			select(Category).order_by(protected_first, func.casefold(Category.name))
		).all()
		return jsonify([category.to_dto() for category in categories])

	@application.post("/categories")
	def post_category():
		values = validate_category_payload(_json_body())
		if category_name_exists(values["name"]):
			raise ApiError(
				"category name already exists",
				"category_name_conflict",
				409,
			)
		category = Category(name=values["name"], type=values["type"])
		db.session.add(category)
		db.session.commit()
		return jsonify(category.to_dto()), 201

	@application.get("/categories/<category_id>")
	def get_category(category_id):
		category_id = validate_uuid_identifier(category_id, "category")
		category = db.session.get(Category, category_id)
		if category is None:
			raise ApiError("category not found", "category_not_found", 404)
		return jsonify(category.to_dto())

	@application.patch("/categories/<category_id>")
	def patch_category(category_id):
		category_id = validate_uuid_identifier(category_id, "category")
		category = db.session.get(Category, category_id)
		if category is None:
			raise ApiError("category not found", "category_not_found", 404)
		if category.name.casefold() == PROTECTED_CATEGORY_NAME.casefold():
			raise ApiError(
				"Uncategorised is a protected system category",
				"protected_category",
				409,
			)
		values = validate_category_payload(_json_body(), partial=True)
		if "name" in values and category_name_exists(
			values["name"],
			excluded_id=category.id,
		):
			raise ApiError(
				"category name already exists",
				"category_name_conflict",
				409,
			)
		for field in ("name", "type"):
			if field in values:
				setattr(category, field, values[field])
		db.session.commit()
		return jsonify(category.to_dto())

	@application.delete("/categories/<category_id>")
	def delete_category(category_id):
		category_id = validate_uuid_identifier(category_id, "category")
		category = db.session.get(Category, category_id)
		if category is None:
			raise ApiError("category not found", "category_not_found", 404)
		if category.name.casefold() == PROTECTED_CATEGORY_NAME.casefold():
			raise ApiError(
				"Uncategorised is a protected system category",
				"protected_category",
				409,
			)
		if category_is_in_use(category.id):
			raise ApiError("category is in use", "category_in_use", 409)
		db.session.delete(category)
		db.session.commit()
		return "", 204

	@application.get("/category-corrections")
	def get_category_corrections():
		merchant = request.args.get("merchant", "").strip()
		limit = parse_query_positive_integer(
			request.args.get("limit"),
			"limit",
			maximum=100,
		)

		return jsonify([
			correction.to_dict()
			for correction in category_corrections(merchant, limit)
		])


def setup_app(database_path=None):
	application = Flask(__name__)
	resolved_database_path = database_path or os.environ.get(
		"DB_PATH",
		"./transactions.db",
	)
	application.config["DB_PATH"] = resolved_database_path
	application.config["SQLALCHEMY_DATABASE_URI"] = _database_uri(
		resolved_database_path
	)
	application.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

	db.init_app(application)
	_register_error_handlers(application)
	_register_routes(application)

	with application.app_context():
		db.create_all()
		seed_database_if_empty()

	return application
