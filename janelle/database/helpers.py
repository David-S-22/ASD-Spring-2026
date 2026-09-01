from sqlalchemy import func, or_, select

from .models import Category, CategoryCorrection, Transaction, db


def filtered_transactions(filters):
	statement = select(Transaction)
	if filters["q"]:
		query = filters["q"].casefold()
		statement = statement.where(
			or_(
				func.instr(func.casefold(Transaction.merchant), query) > 0,
				func.instr(func.casefold(Transaction.description), query) > 0,
			)
		)
	if filters["merchant"]:
		statement = statement.where(
			func.casefold(Transaction.merchant) == filters["merchant"].casefold()
		)
	if filters["date_from"] is not None:
		statement = statement.where(Transaction.date >= filters["date_from"])
	if filters["date_to"] is not None:
		statement = statement.where(Transaction.date <= filters["date_to"])
	if filters["since"] is not None:
		statement = statement.where(Transaction.date >= filters["since"])
	if filters["category_id"] is not None:
		statement = statement.where(
			Transaction.category_id == filters["category_id"]
		)
	if filters["min_amount"] is not None:
		statement = statement.where(Transaction.amount >= filters["min_amount"])
	if filters["max_amount"] is not None:
		statement = statement.where(Transaction.amount <= filters["max_amount"])
	return db.session.scalars(
		statement.order_by(
			Transaction.date.desc(),
			Transaction.created_at.desc(),
			Transaction.id.desc(),
		)
	).unique().all()


def category_name_exists(name, excluded_id=None):
	statement = select(Category.id).where(
		func.casefold(Category.name) == name.casefold()
	)
	if excluded_id is not None:
		statement = statement.where(Category.id != excluded_id)
	return db.session.scalar(statement.limit(1)) is not None


def category_is_in_use(category_id):
	transaction = db.session.scalar(
		select(Transaction.id).where(
			Transaction.category_id == category_id
		).limit(1)
	)
	correction = db.session.scalar(
		select(CategoryCorrection.id).where(
			or_(
				CategoryCorrection.previous_category_id == category_id,
				CategoryCorrection.user_category_id == category_id,
			)
		).limit(1)
	)
	return transaction is not None or correction is not None


def category_corrections(merchant, limit):
	statement = select(CategoryCorrection).join(
		CategoryCorrection.transaction
	)
	if merchant:
		statement = statement.where(
			func.casefold(Transaction.merchant) == merchant.casefold()
		)
	statement = statement.order_by(
		CategoryCorrection.corrected_at.desc(),
		CategoryCorrection.id.desc(),
	)
	if limit is not None:
		statement = statement.limit(limit)
	return db.session.scalars(statement).unique().all()
