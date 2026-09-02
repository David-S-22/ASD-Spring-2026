from __future__ import annotations

from . import db_api, transactions_api


def _normalise_category(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed.casefold() if trimmed else None


def _category_name_map(categories: list[dict]) -> dict[int, str]:
    result: dict[int, str] = {}
    for category in categories:
        category_id = category.get("id")
        name = category.get("name")
        if isinstance(category_id, int) and isinstance(name, str) and name.strip():
            result[category_id] = name
    return result


def _sum_ints(values: list[int | None]) -> int:
    return sum(value for value in values if isinstance(value, int))


def build_budget_summary(budget_id: str) -> dict:
    budget = db_api.get_budget(budget_id)
    budget_lines = db_api.list_budget_lines(budget_id)
    planned_events = db_api.list_planned_events(budget_id)
    coach_proposals = db_api.list_coach_proposals(budget_id)

    categories = transactions_api.list_categories()
    category_names = _category_name_map(categories)
    transactions = transactions_api.list_transactions_for_month(budget.get("month") or "")
    budgeted_category_ids = {
        category_id
        for category_id in (line.get("category_id") for line in budget_lines)
        if isinstance(category_id, int)
    }

    actual_spend_by_category_id: dict[int, int] = {}
    actual_spend_by_category_name: dict[str, int] = {}
    uncategorised_total = 0
    for transaction in transactions:
        amount = transaction.get("amount")
        category_id = transaction.get("category_id")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            continue
        amount_cents = int(round(float(amount) * 100))
        if isinstance(category_id, int):
            actual_spend_by_category_id[category_id] = actual_spend_by_category_id.get(category_id, 0) + amount_cents
        category_name = category_names.get(category_id) if isinstance(category_id, int) else None
        normalised_category = _normalise_category(category_name)
        if normalised_category is None and not isinstance(category_id, int):
            uncategorised_total += amount_cents
            continue
        if normalised_category is not None:
            actual_spend_by_category_name[normalised_category] = (
                actual_spend_by_category_name.get(normalised_category, 0) + amount_cents
            )
        elif isinstance(category_id, int) and category_id not in category_names:
            uncategorised_total += amount_cents

    planned_by_category: dict[str, dict[str, int]] = {}
    active_planned_events = []
    for planned_event in planned_events:
        if planned_event.get("status") == "cancelled":
            continue
        active_planned_events.append(planned_event)
        category_key = _normalise_category(planned_event.get("category"))
        if category_key is None:
            continue
        category_bucket = planned_by_category.setdefault(category_key, {"low": 0, "high": 0})
        est_low = planned_event.get("est_low")
        est_high = planned_event.get("est_high")
        if isinstance(est_low, int):
            category_bucket["low"] += est_low
        if isinstance(est_high, int):
            category_bucket["high"] += est_high

    line_summaries = []
    for budget_line in budget_lines:
        category = budget_line.get("category")
        category_id = budget_line.get("category_id")
        category_key = _normalise_category(category)
        if isinstance(category_id, int):
            actual_spend = actual_spend_by_category_id.get(category_id, 0)
        else:
            actual_spend = actual_spend_by_category_name.get(category_key, 0) if category_key else 0
        planned_totals = planned_by_category.get(category_key, {"low": 0, "high": 0}) if category_key else {"low": 0, "high": 0}
        warn_at = budget_line.get("warn_at") if isinstance(budget_line.get("warn_at"), int) else None
        hard_cap = budget_line.get("hard_cap") if isinstance(budget_line.get("hard_cap"), int) else None
        projected_low = actual_spend + planned_totals["low"]
        projected_high = actual_spend + planned_totals["high"]
        line_summaries.append(
            {
                **budget_line,
                "actual_spend": actual_spend,
                "planned_est_low_total": planned_totals["low"],
                "planned_est_high_total": planned_totals["high"],
                "projected_low_total": projected_low,
                "projected_high_total": projected_high,
                "warning_state": bool(warn_at is not None and actual_spend >= warn_at),
                "cap_state": bool(hard_cap is not None and actual_spend >= hard_cap),
                "remaining_to_warn": None if warn_at is None else warn_at - actual_spend,
                "remaining_to_cap": None if hard_cap is None else hard_cap - actual_spend,
            }
        )

    other_expenses = [
        {
            "category_id": category_id,
            "category": category_names[category_id],
            "actual_spend": actual_spend,
        }
        for category_id, actual_spend in actual_spend_by_category_id.items()
        if category_id not in budgeted_category_ids and category_id in category_names
    ]
    other_expenses.sort(key=lambda expense: str(expense.get("category") or ""))

    totals = {
        "declared_income": budget.get("declared_income"),
        "actual_spend_total": _sum_ints([line["actual_spend"] for line in line_summaries]),
        "planned_est_low_total": _sum_ints([line["planned_est_low_total"] for line in line_summaries]),
        "planned_est_high_total": _sum_ints([line["planned_est_high_total"] for line in line_summaries]),
        "budget_warn_total": _sum_ints([line.get("warn_at") for line in line_summaries]),
        "budget_cap_total": _sum_ints([line.get("hard_cap") for line in line_summaries]),
    }
    totals["projected_low_total"] = totals["actual_spend_total"] + totals["planned_est_low_total"]
    totals["projected_high_total"] = totals["actual_spend_total"] + totals["planned_est_high_total"]

    declared_income = totals["declared_income"] if isinstance(totals["declared_income"], int) else None
    totals["remaining_income_low"] = None if declared_income is None else declared_income - totals["projected_low_total"]
    totals["remaining_income_high"] = None if declared_income is None else declared_income - totals["projected_high_total"]

    return {
        "budget": budget,
        "budget_lines": line_summaries,
        "planned_events": active_planned_events,
        "coach_proposals": coach_proposals,
        "transactions": {
            "count": len(transactions),
            "uncategorised_total": uncategorised_total,
            "other_expenses": other_expenses,
        },
        "totals": totals,
    }
