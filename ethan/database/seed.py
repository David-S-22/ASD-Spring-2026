from __future__ import annotations

from sqlalchemy import func, select

from .models import Budget, BudgetLine, CoachProposal, PlannedEvent, db


SEED_BUDGETS = (
    ("2026-01", 520000, "closed"),
    ("2026-02", 515000, "closed"),
    ("2026-03", 530000, "closed"),
    ("2026-04", 525000, "closed"),
    ("2026-05", 535000, "closed"),
    ("2026-06", 540000, "closed"),
    ("2026-07", 550000, "closed"),
    ("2026-08", 548000, "closed"),
    ("2026-09", 560000, "active"),
    ("2026-10", 565000, "draft"),
)

SEED_LINE_CATEGORIES = (
    (30, "Housing"),
    (31, "Fitness"),
    (32, "Music subscriptions"),
    (33, "Streaming subscriptions"),
    (60, "Internet"),
    (61, "Mobile"),
    (62, "Utilities"),
    (70, "Transport"),
    (80, "Dining"),
    (81, "Groceries"),
)

SEED_EVENT_LABELS = (
    "Weekly grocery shop",
    "Fuel top-up",
    "Dinner with friends",
    "Cinema night",
    "Electricity bill",
    "Pharmacy purchase",
    "Clothing allowance",
    "Streaming renewal",
    "Weekend trip",
    "Unexpected expense buffer",
)

SEED_EVENT_SOURCES = (
    "user",
    "predicted",
    "user",
    "predicted",
    "user",
    "predicted",
    "user",
    "predicted",
    "user",
    "predicted",
)

SEED_EVENT_STATUSES = (
    "confirmed",
    "planned",
    "planned",
    "planned",
    "confirmed",
    "planned",
    "planned",
    "confirmed",
    "planned",
    "planned",
)

SEED_PROPOSAL_STATUSES = (
    "accepted",
    "rejected",
    "accepted",
    "proposed",
    "accepted",
    "rejected",
    "proposed",
    "accepted",
    "proposed",
    "proposed",
)


def seed_database_if_empty():
    try:
        if any(_seed_counts().values()):
            return

        for index, budget_row in enumerate(SEED_BUDGETS, start=1):
            month, declared_income, budget_status = budget_row
            timestamp = f"{month}-01T09:00:00+00:00"
            budget = Budget(
                id=index,
                month=month,
                declared_income=declared_income,
                status=budget_status,
                created_at=timestamp,
                updated_at=timestamp,
            )
            db.session.add(budget)
            db.session.flush()

            category_id, category = SEED_LINE_CATEGORIES[index - 1]
            warn_at = 10000 + index * 1000
            hard_cap = warn_at + 5000
            budget_line = BudgetLine(
                id=index,
                budget_id=budget.id,
                category_id=category_id,
                category=category,
                warn_at=warn_at,
                hard_cap=hard_cap,
                created_at=timestamp,
                updated_at=timestamp,
            )
            db.session.add(budget_line)

            planned_event = PlannedEvent(
                id=index,
                budget_id=budget.id,
                date=f"{month}-0{index if index < 10 else 9}",
                label=SEED_EVENT_LABELS[index - 1],
                category=category,
                est_low=max(1000, warn_at - 2000),
                est_high=warn_at,
                source=SEED_EVENT_SOURCES[index - 1],
                status=SEED_EVENT_STATUSES[index - 1],
                created_at=timestamp,
                updated_at=timestamp,
            )
            db.session.add(planned_event)

            proposal_status = SEED_PROPOSAL_STATUSES[index - 1]
            decided_at = timestamp if proposal_status in {"accepted", "rejected"} else None
            rejection_reason = (
                "User preferred to keep current budget settings."
                if proposal_status == "rejected"
                else None
            )
            coach_proposal = CoachProposal(
                id=index,
                budget_id=budget.id,
                proposal_json={
                    "proposal_type": "coach_seed",
                    "operations": [
                        {
                            "action": "update_budget_line",
                            "target": {"category": category},
                            "fields": {
                                "warn_at": warn_at + 500,
                                "hard_cap": hard_cap + 500,
                            },
                        }
                    ],
                    "user_confirmation_message": f"Adjust {category} budget for {month}?",
                },
                rationale=f"Seeded proposal for {category.lower()} in {month}.",
                status=proposal_status,
                rejection_reason=rejection_reason,
                decided_at=decided_at,
                created_at=timestamp,
            )
            db.session.add(coach_proposal)

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _seed_counts() -> dict[str, int]:
    return {
        "budgets": db.session.scalar(select(func.count(Budget.id))) or 0,
        "budget_lines": db.session.scalar(select(func.count(BudgetLine.id))) or 0,
        "planned_events": db.session.scalar(select(func.count(PlannedEvent.id))) or 0,
        "coach_proposals": db.session.scalar(select(func.count(CoachProposal.id))) or 0,
    }
