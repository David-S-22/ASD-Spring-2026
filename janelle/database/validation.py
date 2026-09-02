from datetime import date, datetime, time, timezone
from decimal import Decimal, DecimalException


CATEGORY_TYPES = {"need", "want", "saving"}
TRANSACTION_FIELDS = {
	"date",
	"merchant",
	"description",
	"amount",
	"category_id",
}
CATEGORY_FIELDS = {"name", "type"}
MAX_SQLITE_INTEGER = (2**63) - 1
MAX_AMOUNT = Decimal("9999999999.99")


class ApiError(Exception):
	def __init__(self, message, code, status):
		super().__init__(message)
		self.message = message
		self.code = code
		self.status = status


def reject_unknown_fields(data, allowed_fields):
	unknown = sorted(set(data) - allowed_fields)
	if unknown:
		raise ApiError(
			f"unsupported fields: {', '.join(unknown)}",
			"unsupported_fields",
			422,
		)


def parse_text(value, field_name, max_length):
	if not isinstance(value, str):
		raise ApiError(f"{field_name} must be a string", f"invalid_{field_name}", 422)
	value = value.strip()
	if not value:
		raise ApiError(f"{field_name} must not be empty", f"invalid_{field_name}", 422)
	if len(value) > max_length:
		raise ApiError(
			f"{field_name} must be at most {max_length} characters",
			f"invalid_{field_name}",
			422,
		)
	if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
		raise ApiError(
			f"{field_name} contains invalid Unicode",
			f"invalid_{field_name}",
			422,
		)
	return value


def parse_datetime(value, field_name, status=422, code=None, end_of_day=False):
	if not isinstance(value, str):
		raise ApiError(
			f"{field_name} must be an ISO 8601 date or datetime",
			code or f"invalid_{field_name}",
			status,
		)
	try:
		if len(value) == 10:
			parsed_date = date.fromisoformat(value)
			parsed = datetime.combine(
				parsed_date,
				time.max if end_of_day else time.min,
			)
		else:
			parsed = datetime.fromisoformat(value)
	except ValueError as error:
		raise ApiError(
			f"{field_name} must be an ISO 8601 date or datetime",
			code or f"invalid_{field_name}",
			status,
		) from error
	if parsed.tzinfo is not None:
		parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
	return parsed


def parse_integer_id(value, field_name, status=422, code=None):
	if (
		isinstance(value, bool)
		or not isinstance(value, int)
		or value <= 0
		or value > MAX_SQLITE_INTEGER
	):
		raise ApiError(
			f"{field_name} must be a supported positive integer",
			code or f"invalid_{field_name}",
			status,
		)
	return value


def parse_amount(value, field_name, status, code, require_number):
	if require_number and (
		isinstance(value, bool)
		or not isinstance(value, (int, float))
	):
		raise ApiError(f"{field_name} must be a number", code, status)
	try:
		amount = Decimal(str(value))
		if not amount.is_finite():
			raise ApiError(f"{field_name} must be finite", code, status)
		scaled_amount = amount * 100
		if scaled_amount != scaled_amount.to_integral_value():
			raise ApiError(
				f"{field_name} must have at most two decimal places",
				code,
				status,
			)
		if abs(amount) > MAX_AMOUNT:
			raise ApiError(
				f"{field_name} is outside the supported range",
				code,
				status,
			)
	except (DecimalException, ValueError) as error:
		raise ApiError(f"{field_name} must be a valid amount", code, status) from error
	return amount.quantize(Decimal("0.01"))


def validate_transaction_payload(data, partial=False):
	reject_unknown_fields(data, TRANSACTION_FIELDS)
	required = {"date", "merchant", "description", "amount", "category_id"}
	if not partial:
		missing = sorted(field for field in required if field not in data)
		if missing:
			raise ApiError(
				f"missing required fields: {', '.join(missing)}",
				"missing_fields",
				422,
			)
	if partial and not data:
		raise ApiError("no updatable fields supplied", "no_updates", 422)

	values = {}
	if "date" in data:
		values["date"] = parse_datetime(data["date"], "date")
	if "merchant" in data:
		values["merchant"] = parse_text(data["merchant"], "merchant", 200)
	if "description" in data:
		values["description"] = parse_text(
			data["description"],
			"description",
			500,
		)
	if "amount" in data:
		values["amount"] = parse_amount(
			data["amount"],
			"amount",
			422,
			"invalid_amount",
			require_number=True,
		)
	if "category_id" in data:
		values["category_id"] = parse_integer_id(data["category_id"], "category_id")
	return values


def validate_category_payload(data, partial=False):
	reject_unknown_fields(data, CATEGORY_FIELDS)
	if not partial and "name" not in data:
		raise ApiError("missing required fields: name", "missing_fields", 422)
	if partial and not data:
		raise ApiError("no updatable fields supplied", "no_updates", 422)

	values = {}
	if "name" in data:
		values["name"] = parse_text(data["name"], "name", 80)
	if "type" in data:
		category_type = data["type"]
		if category_type is not None and (
			not isinstance(category_type, str)
			or category_type not in CATEGORY_TYPES
		):
			raise ApiError(
				"type must be need, want, saving, or null",
				"invalid_category_type",
				422,
			)
		values["type"] = category_type
	elif not partial:
		values["type"] = None
	return values


def validate_correction_payload(data):
	reject_unknown_fields(data, {"category_id", "user_category_id"})
	category_id = data.get("category_id")
	user_category_id = data.get("user_category_id")
	if category_id is None and user_category_id is None:
		raise ApiError(
			"missing required fields: category_id",
			"missing_fields",
			422,
		)
	parsed_category_id = (
		parse_integer_id(category_id, "category_id")
		if category_id is not None
		else None
	)
	parsed_user_category_id = (
		parse_integer_id(user_category_id, "user_category_id")
		if user_category_id is not None
		else None
	)
	if (
		parsed_category_id is not None
		and parsed_user_category_id is not None
		and parsed_category_id != parsed_user_category_id
	):
		raise ApiError(
			"category_id and user_category_id must match",
			"category_mismatch",
			422,
		)
	return parsed_category_id or parsed_user_category_id


def parse_transaction_filters(arguments):
	filters = {
		"q": arguments.get("q", "").strip(),
		"merchant": arguments.get("merchant", "").strip(),
		"date_from": parse_query_date(arguments.get("date_from"), "date_from"),
		"date_to": parse_query_date(
			arguments.get("date_to"),
			"date_to",
			end_of_day=True,
		),
		"since": parse_query_date(arguments.get("since"), "since"),
		"category_id": parse_query_positive_integer(
			arguments.get("category_id"),
			"category_id",
		),
		"min_amount": parse_query_amount(
			arguments.get("min_amount"),
			"min_amount",
		),
		"max_amount": parse_query_amount(
			arguments.get("max_amount"),
			"max_amount",
		),
	}
	lower_dates = [
		value
		for value in (filters["date_from"], filters["since"])
		if value is not None
	]
	if filters["date_to"] is not None and any(
		value > filters["date_to"] for value in lower_dates
	):
		raise ApiError(
			"date lower bounds must not be after date_to",
			"invalid_query",
			400,
		)
	if (
		filters["min_amount"] is not None
		and filters["max_amount"] is not None
		and filters["min_amount"] > filters["max_amount"]
	):
		raise ApiError(
			"min_amount must not exceed max_amount",
			"invalid_query",
			400,
		)
	return filters


def parse_query_date(value, field_name, end_of_day=False):
	if value in (None, ""):
		return None
	return parse_datetime(
		value,
		field_name,
		400,
		"invalid_query",
		end_of_day=end_of_day,
	)


def parse_query_amount(value, field_name):
	if value in (None, ""):
		return None
	return parse_amount(
		value,
		field_name,
		400,
		"invalid_query",
		require_number=False,
	)


def parse_query_positive_integer(value, field_name, maximum=None):
	if value in (None, ""):
		return None
	try:
		parsed = int(value)
	except (TypeError, ValueError) as error:
		raise ApiError(
			f"{field_name} must be a positive integer",
			"invalid_query",
			400,
		) from error
	if parsed <= 0 or parsed > MAX_SQLITE_INTEGER or str(parsed) != str(value):
		raise ApiError(
			f"{field_name} must be a supported positive integer",
			"invalid_query",
			400,
		)
	if maximum is not None and parsed > maximum:
		raise ApiError(
			f"{field_name} must not exceed {maximum}",
			"invalid_query",
			400,
		)
	return parsed


def validate_path_identifier(value, entity_name):
	if isinstance(value, str):
		if len(value) > 19 or not value.isascii() or not value.isdigit():
			raise ApiError(
				f"{entity_name} not found",
				f"{entity_name}_not_found",
				404,
			)
		value = int(value)
	if (
		isinstance(value, bool)
		or not isinstance(value, int)
		or value <= 0
		or value > MAX_SQLITE_INTEGER
	):
		raise ApiError(
			f"{entity_name} not found",
			f"{entity_name}_not_found",
			404,
		)
	return value
