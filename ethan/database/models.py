from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class Budget(db.Model):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    declared_income: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    budget_lines: Mapped[list[BudgetLine]] = relationship(
        back_populates="budget",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    planned_events: Mapped[list[PlannedEvent]] = relationship(
        back_populates="budget",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    coach_proposals: Mapped[list[CoachProposal]] = relationship(
        back_populates="budget",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("month", name="uq_budgets_month"),
        CheckConstraint(
            "status IS NULL OR status IN ('draft', 'active', 'closed')",
            name="ck_budgets_status",
        ),
    )

    def to_dict(self) -> dict[str, object | None]:
        return {
            "id": self.id,
            "month": self.month,
            "declared_income": self.declared_income,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class BudgetLine(db.Model):
    __tablename__ = "budget_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(120, collation="NOCASE"), nullable=True)
    warn_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hard_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    budget: Mapped[Budget] = relationship(back_populates="budget_lines")

    __table_args__ = (
        UniqueConstraint("budget_id", "category_id", name="uq_budget_lines_budget_category_id"),
        CheckConstraint(
            "warn_at IS NULL OR hard_cap IS NULL OR warn_at <= hard_cap",
            name="ck_budget_lines_warn_at_hard_cap",
        ),
    )

    def to_dict(self) -> dict[str, object | None]:
        return {
            "id": self.id,
            "budget_id": self.budget_id,
            "category_id": self.category_id,
            "category": self.category,
            "warn_at": self.warn_at,
            "hard_cap": self.hard_cap,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PlannedEvent(db.Model):
    __tablename__ = "planned_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120, collation="NOCASE"), nullable=True)
    est_low: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_high: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    budget: Mapped[Budget] = relationship(back_populates="planned_events")

    __table_args__ = (
        CheckConstraint(
            "est_low IS NULL OR est_high IS NULL OR est_low <= est_high",
            name="ck_planned_events_est_range",
        ),
        CheckConstraint(
            "source IS NULL OR source IN ('user', 'predicted')",
            name="ck_planned_events_source",
        ),
        CheckConstraint(
            "status IS NULL OR status IN ('planned', 'confirmed', 'cancelled')",
            name="ck_planned_events_status",
        ),
    )

    def to_dict(self) -> dict[str, object | None]:
        return {
            "id": self.id,
            "budget_id": self.budget_id,
            "date": self.date,
            "label": self.label,
            "category": self.category,
            "est_low": self.est_low,
            "est_high": self.est_high,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class CoachProposal(db.Model):
    __tablename__ = "coach_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    proposal_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    budget: Mapped[Budget] = relationship(back_populates="coach_proposals")

    __table_args__ = (
        CheckConstraint(
            "status IS NULL OR status IN ('proposed', 'accepted', 'rejected')",
            name="ck_coach_proposals_status",
        ),
    )

    def to_dict(self) -> dict[str, object | None]:
        return {
            "id": self.id,
            "budget_id": self.budget_id,
            "proposal_json": self.proposal_json,
            "rationale": self.rationale,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "decided_at": self.decided_at,
            "created_at": self.created_at,
        }
