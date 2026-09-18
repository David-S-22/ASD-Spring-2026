from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from .models import Category, CategoryCorrection, Transaction, db


SYSTEM_CATEGORY = (1, "Uncategorised", None)


CATEGORIES = (
	SYSTEM_CATEGORY,
	(30, "Housing", "need"),
	(31, "Fitness", "want"),
	(32, "Music subscriptions", "want"),
	(33, "Streaming subscriptions", "want"),
	(34, "Video subscriptions", "want"),
	(35, "Gym memberships", "want"),
	(60, "Internet", "need"),
	(61, "Mobile", "need"),
	(62, "Utilities", "need"),
	(70, "Transport", "need"),
	(71, "Shared household", "need"),
	(72, "Cloud storage", "want"),
	(80, "Dining", "want"),
	(81, "Groceries", "need"),
)

FIXTURE_TRANSACTIONS = (
	("2026-06-10", "Harbourview Realty", "Rent payment", "1100.00", 30),
	("2026-06-10", "Netflix", "Netflix.com subscription", "20.99", 33),
	("2026-06-10", "FibreLink", "Internet plan", "79.00", 60),
	("2026-06-10", "Transport card", "Opal top-up", "38.50", 70),
	("2026-06-10", "Harbourview Realty", "Rent payment", "1100.00", 30),
	("2026-06-24", "Harbourview Realty", "Rent payment", "1100.00", 30),
	("2026-06-24", "Anytime Fitness Ultimo", "Direct debit membership fee", "17.50", 31),
	("2026-06-24", "Netflix", "Netflix.com subscription", "20.99", 33),
	("2026-06-24", "Prime Video", "Amazon Prime Video", "9.99", 34),
	("2026-06-24", "FibreLink", "Internet plan", "79.00", 60),
	("2026-06-24", "Telco One", "Mobile plan", "49.00", 61),
	("2026-06-24", "Transport card", "Opal top-up", "38.50", 70),
	("2026-06-24", "Housemates", "Shared kitty transfer", "25.00", 71),
	("2026-07-08", "Anytime Fitness Ultimo", "Direct debit membership fee", "17.50", 31),
	("2026-07-08", "Spotify AU", "Spotify Premium subscription", "13.99", 32),
	("2026-07-08", "Prime Video", "Amazon Prime Video", "9.99", 34),
	("2026-07-08", "GymCo", "GymCo membership", "24.99", 35),
	("2026-07-08", "Telco One", "Mobile plan", "49.00", 61),
	("2026-07-08", "Sparkwell Energy", "Electricity bill", "139.75", 62),
	("2026-07-08", "Housemates", "Shared kitty transfer", "25.00", 71),
	("2026-07-08", "DriveBox", "Cloud storage subscription", "2.99", 72),
	("2026-07-15", "Spotify AU", "Spotify Premium subscription", "13.99", 32),
	("2026-07-15", "GymCo", "GymCo membership", "24.99", 35),
	("2026-07-15", "Sparkwell Energy", "Electricity bill", "139.75", 62),
	("2026-07-15", "DriveBox", "Cloud storage subscription", "2.99", 72),
)


def fixture_rows():
	rows = []
	for transaction_id, transaction in enumerate(FIXTURE_TRANSACTIONS, start=1):
		transaction_date, merchant, description, amount, category_id = transaction
		timestamp = f"{transaction_date}T12:00:00+00:00"
		rows.append(
			(
				transaction_id,
				transaction_date,
				merchant,
				description,
				amount,
				category_id,
				timestamp,
				timestamp,
			)
		)
	return rows


TRANSACTIONS = tuple(fixture_rows()) + (
	(26, "2026-08-20", "Spotify AU", "Monthly subscription", "17.99", 32, "2026-08-20T12:00:00+00:00", "2026-08-20T12:00:00+00:00"),
	(27, "2026-08-09", "Merivale", "Dinner", "84.50", 80, "2026-08-09T12:00:00+00:00", "2026-08-10T09:00:00+00:00"),
	(28, "2026-08-16", "Merivale", "Lunch", "42.00", 80, "2026-08-16T12:00:00+00:00", "2026-08-16T12:00:00+00:00"),
	(29, "2026-08-30", "Merivale", "Dinner", "76.00", 80, "2026-08-30T12:00:00+00:00", "2026-08-30T12:00:00+00:00"),
	(30, "2026-08-12", "Chat Thai", "Lunch", "28.50", 80, "2026-08-12T12:00:00+00:00", "2026-08-12T12:00:00+00:00"),
	(31, "2026-08-26", "Chat Thai", "Dinner", "47.20", 80, "2026-08-26T12:00:00+00:00", "2026-08-26T12:00:00+00:00"),
	(32, "2026-08-22", "Woolworths", "Weekly groceries", "86.45", 81, "2026-08-22T12:00:00+00:00", "2026-08-22T14:00:00+00:00"),
	(33, "2026-08-25", "Sydney Trains", "Opal card top-up", "40.00", 70, "2026-08-25T12:00:00+00:00", "2026-08-25T14:00:00+00:00"),
	(34, "2026-08-29", "Mystery Merchant", "Unrecognised card charge", "12.34", 1, "2026-08-29T12:00:00+00:00", "2026-08-29T12:00:00+00:00"),
)

CATEGORY_CORRECTIONS = (
	(1, 27, 1, 80, "2026-08-10T09:00:00+00:00"),
	(2, 32, 80, 81, "2026-08-22T14:00:00+00:00"),
	(3, 33, 81, 70, "2026-08-25T14:00:00+00:00"),
)


def seed_datetime(value):
	return datetime.fromisoformat(value).replace(tzinfo=None)


def seed_database_if_empty():
	try:
		if any(seed_counts().values()):
			return

		for category_row in CATEGORIES:
			db.session.add(
				Category(
					id=category_row[0],
					name=category_row[1],
					type=category_row[2],
				)
			)

		for transaction_row in TRANSACTIONS:
			db.session.add(
				Transaction(
					id=transaction_row[0],
					date=seed_datetime(transaction_row[1]),
					merchant=transaction_row[2],
					description=transaction_row[3],
					amount=Decimal(transaction_row[4]),
					category_id=transaction_row[5],
					created_at=seed_datetime(transaction_row[6]),
					updated_at=seed_datetime(transaction_row[7]),
				)
			)

		for correction_row in CATEGORY_CORRECTIONS:
			db.session.add(
				CategoryCorrection(
					id=correction_row[0],
					transaction_id=correction_row[1],
					previous_category_id=correction_row[2],
					user_category_id=correction_row[3],
					corrected_at=correction_row[4],
				)
			)

		db.session.commit()
	except Exception:
		db.session.rollback()
		raise


def seed_counts():
	return {
		"categories": db.session.scalar(select(func.count(Category.id))),
		"transactions": db.session.scalar(select(func.count(Transaction.id))),
		"category_corrections": db.session.scalar(
			select(func.count(CategoryCorrection.id))
		),
	}
