from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
	CheckConstraint,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	event,
	func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from shared.backend import dto


class Base(DeclarativeBase):
	pass


db = SQLAlchemy(model_class=Base)


def _casefold(value):
	return value.casefold() if isinstance(value, str) else value


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(database_connection, _connection_record):
	if not isinstance(database_connection, sqlite3.Connection):
		return
	database_connection.create_function("casefold", 1, _casefold, deterministic=True)
	database_connection.execute("PRAGMA foreign_keys = ON")
	database_connection.execute("PRAGMA busy_timeout = 5000")


class Category(db.Model):
	__tablename__ = "categories"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	name: Mapped[str] = mapped_column(
		String(80, collation="NOCASE"),
		nullable=False,
		unique=True,
	)
	type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

	__table_args__ = (
		CheckConstraint(
			"type IS NULL OR type IN ('need', 'want', 'saving')",
			name="ck_categories_type",
		),
		Index(
			"uq_categories_name_normalized",
			func.casefold(name),
			unique=True,
		),
	)

	def to_dto(self):
		return dto.Category(
			id=self.id,
			name=self.name,
			type=self.type,
		)


class Transaction(db.Model):
	__tablename__ = "transactions"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
	merchant: Mapped[str] = mapped_column(String(200), nullable=False)
	description: Mapped[str] = mapped_column(String(500), nullable=False)
	amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
	category_id: Mapped[int] = mapped_column(
		ForeignKey("categories.id", ondelete="RESTRICT", onupdate="CASCADE"),
		nullable=False,
	)
	created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
	updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

	category: Mapped[Category] = relationship(
		foreign_keys=[category_id],
		lazy="joined",
	)
	category_corrections: Mapped[list[CategoryCorrection]] = relationship(
		back_populates="transaction",
		cascade="all, delete-orphan",
		passive_deletes=True,
	)

	__table_args__ = (
		Index("idx_transactions_date", date.desc()),
		Index("idx_transactions_merchant_normalized", func.casefold(merchant)),
		Index("idx_transactions_category_id", category_id),
	)

	def to_dto(self):
		return dto.Transaction(
			id=self.id,
			amount=float(self.amount),
			merchant=self.merchant,
			date=self.date,
			description=self.description,
			category_id=self.category_id,
		)


class CategoryCorrection(db.Model):
	__tablename__ = "category_corrections"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	transaction_id: Mapped[int] = mapped_column(
		ForeignKey("transactions.id", ondelete="CASCADE"),
		nullable=False,
	)
	previous_category_id: Mapped[int] = mapped_column(
		ForeignKey("categories.id", ondelete="RESTRICT", onupdate="CASCADE"),
		nullable=False,
	)
	user_category_id: Mapped[int] = mapped_column(
		ForeignKey("categories.id", ondelete="RESTRICT", onupdate="CASCADE"),
		nullable=False,
	)
	corrected_at: Mapped[str] = mapped_column(String(40), nullable=False)

	transaction: Mapped[Transaction] = relationship(
		back_populates="category_corrections",
		lazy="joined",
	)
	previous_category: Mapped[Category] = relationship(
		foreign_keys=[previous_category_id],
		lazy="joined",
	)
	user_category: Mapped[Category] = relationship(
		foreign_keys=[user_category_id],
		lazy="joined",
	)

	__table_args__ = (
		Index("idx_category_corrections_transaction_id", transaction_id),
		Index("idx_category_corrections_corrected_at", corrected_at.desc()),
	)

	def to_dict(self):
		return {
			"id": self.id,
			"transaction_id": self.transaction_id,
			"date": self.transaction.date,
			"merchant": self.transaction.merchant,
			"description": self.transaction.description,
			"previous_category_id": self.previous_category_id,
			"previous_category_name": self.previous_category.name,
			"user_category_id": self.user_category_id,
			"user_category_name": self.user_category.name,
			"corrected_at": self.corrected_at,
		}
