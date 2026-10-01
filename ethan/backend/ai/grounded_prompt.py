from __future__ import annotations

import json


def _format_cents(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return f"${value / 100:,.2f}"


FALLBACK = {
    "answer": "I couldn't ground a reliable answer from the retrieved budget guidance right now.",
    "cited": [],
    "insufficient_context": True,
}


def build(question: str, summary: dict, retrieved_chunks: list[dict], error: str | None = None) -> list[dict]:
    budget = summary.get("budget") if isinstance(summary.get("budget"), dict) else {}
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    budget_lines = summary.get("budget_lines") if isinstance(summary.get("budget_lines"), list) else []
    lines = [
        {
            "id": line.get("id"),
            "category": line.get("category"),
            "actual_spend_display": _format_cents(line.get("actual_spend")),
            "week_ahead_planned_high_display": _format_cents(line.get("planned_est_high_total")),
            "projected_high_total_display": _format_cents(line.get("projected_high_total")),
            "warn_at_display": _format_cents(line.get("warn_at")),
            "hard_cap_display": _format_cents(line.get("hard_cap")),
            "pressure_basis": (
                "week-ahead planned spending"
                if isinstance(line.get("planned_est_high_total"), int) and line.get("planned_est_high_total") > 0
                else "current spending"
            ),
        }
        for line in budget_lines[:8]
        if isinstance(line, dict)
    ]
    retrieval = [
        {
            "id": chunk.get("id"),
            "source": chunk.get("metadata", {}).get("source"),
            "distance": chunk.get("distance"),
            "text": chunk.get("text"),
        }
        for chunk in retrieved_chunks
    ]
    instructions = {
        "role": "system",
        "content": (
            "You are Tally, the Budget Coach grounded-response assistant. "
            "Answer only from the supplied budget snapshot and retrieved guidance. "
            "Do not invent sources. If the retrieved context is too weak or irrelevant, "
            "set insufficient_context to true and keep the answer brief. "
            "All money values in the budget snapshot are already formatted for display, so quote those values exactly "
            "when you mention money. "
            "If a category is under pressure because of planned spending, say that it is based on the "
            "week-ahead plan or planned spending rather than implying the money has already been spent. "
            "Return JSON only with keys answer, cited, insufficient_context. "
            "cited must be a list of source strings taken exactly from the provided retrieval items."
        ),
    }
    context = {
        "role": "user",
        "content": json.dumps(
            {
                "question": question,
                "budget": {
                    "id": budget.get("id"),
                    "month": budget.get("month"),
                    "declared_income_display": _format_cents(budget.get("declared_income")),
                },
                "totals": {
                    "actual_spend_total_display": _format_cents(totals.get("actual_spend_total")),
                    "planned_est_high_total_display": _format_cents(totals.get("planned_est_high_total")),
                    "remaining_income_high_display": _format_cents(totals.get("remaining_income_high")),
                },
                "budget_lines": lines,
                "retrieval": retrieval,
                "previous_error": error,
            },
            ensure_ascii=True,
        ),
    }
    return [instructions, context]
