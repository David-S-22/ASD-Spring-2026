from __future__ import annotations

import json


FALLBACK = {
    "mode": "advice",
    "say": "Tally could not reach the AI service just now, so no suggestion was made. You can still use the manual budget tools.",
    "question": None,
    "proposal": None,
}


def _format_cents(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return "unknown"
    return f"${value / 100:,.2f}"


def _line_summary(line: dict) -> str:
    category = line.get("category") or "Unnamed"
    return (
        f"{category}: spent {_format_cents(line.get('actual_spend'))}, "
        f"planned {_format_cents(line.get('planned_est_high_total'))}, "
        f"projected {_format_cents(line.get('projected_high_total'))}, "
        f"warn {_format_cents(line.get('warn_at'))}, "
        f"cap {_format_cents(line.get('hard_cap'))}"
    )


def _budget_lines(summary: dict) -> list[dict]:
    lines = summary.get("budget_lines")
    if not isinstance(lines, list):
        return []
    return [line for line in lines if isinstance(line, dict)]


def _line_projected_high(line: dict) -> int:
    projected = line.get("projected_high_total")
    if isinstance(projected, int):
        return projected
    actual = line.get("actual_spend") if isinstance(line.get("actual_spend"), int) else 0
    planned = line.get("planned_est_high_total") if isinstance(line.get("planned_est_high_total"), int) else 0
    return actual + planned


def _sample_line(summary: dict) -> dict | None:
    lines = _budget_lines(summary)
    if not lines:
        return None

    def sort_key(line: dict) -> tuple[int, int, int]:
        projected = _line_projected_high(line)
        hard_cap = line.get("hard_cap") if isinstance(line.get("hard_cap"), int) else None
        warn_at = line.get("warn_at") if isinstance(line.get("warn_at"), int) else None
        threshold = hard_cap if hard_cap is not None else warn_at
        if threshold is None or threshold <= 0:
            return (0, 0, projected)
        overshoot = projected - threshold
        return (1 if overshoot >= 0 else 0, overshoot, projected)

    return sorted(lines, key=sort_key, reverse=True)[0]


def _json_message(payload: dict) -> str:
    return json.dumps(payload)


def _few_shot(summary: dict) -> list[tuple[str, str]]:
    line = _sample_line(summary)
    if line is None:
        return [
            (
                "Where am I overspending most?",
                _json_message({
                    "mode": "advice",
                    "say": "I cannot see any budget lines for the selected month yet, so I cannot rank overspending.",
                    "question": None,
                    "proposal": None,
                }),
            ),
        ]

    line_id = line.get("id") if isinstance(line.get("id"), int) else 1
    category = str(line.get("category") or "this category")
    actual = line.get("actual_spend") if isinstance(line.get("actual_spend"), int) else 0
    planned = line.get("planned_est_high_total") if isinstance(line.get("planned_est_high_total"), int) else 0
    projected = _line_projected_high(line)
    warn_at = line.get("warn_at") if isinstance(line.get("warn_at"), int) else None
    hard_cap = line.get("hard_cap") if isinstance(line.get("hard_cap"), int) else None
    recommended_cap = hard_cap if isinstance(hard_cap, int) and hard_cap > projected else projected + 2000
    if recommended_cap <= projected:
        recommended_cap = projected + 2000
    recommended_warn = warn_at if isinstance(warn_at, int) and warn_at < recommended_cap else max(projected, recommended_cap - 1000)
    if recommended_warn >= recommended_cap:
        recommended_warn = recommended_cap - 1000

    if hard_cap is not None and projected >= hard_cap:
        overspending_say = (
            f"You are overspending most in {category}. Its projected total is {_format_cents(projected)}, "
            f"which is {_format_cents(projected - hard_cap)} over the hard cap of {_format_cents(hard_cap)}."
        )
        affordability_say = (
            f"No, your {category} expenses this month are already exceeding your current budget. "
            f"{category} is spent {_format_cents(actual)} with {_format_cents(planned)} planned, so the projected total is {_format_cents(projected)}."
        )
    elif warn_at is not None and projected >= warn_at:
        overspending_say = (
            f"{category} is under the most pressure this month. Its projected total is {_format_cents(projected)}, "
            f"which is {_format_cents(projected - warn_at)} over the warning amount of {_format_cents(warn_at)}."
        )
        if hard_cap is not None:
            affordability_say = (
                f"Maybe, but {category} is already in warning range this month. Based on your current budget and spending, "
                f"you still have {_format_cents(hard_cap - projected)} left before reaching the hard cap."
            )
        else:
            affordability_say = f"Maybe, but {category} is already in warning range this month at a projected {_format_cents(projected)}."
    else:
        overspending_say = f"{category} is under the most pressure this month at a projected {_format_cents(projected)}."
        limit_value = hard_cap if hard_cap is not None else warn_at
        limit_label = "hard cap" if hard_cap is not None else "warning amount"
        if limit_value is not None:
            affordability_say = (
                f"Yes, based on your current budget and spending you still have {_format_cents(limit_value - projected)} left to spend on "
                f"{category} this month before reaching the {limit_label}."
            )
        else:
            affordability_say = f"I can see {category}, but there is no warning or hard-cap limit set yet for that budget line."

    proposal_say = (
        f"{category} is projected to reach {_format_cents(projected)} this month against its current warning amount of "
        f"{_format_cents(warn_at)} and hard cap of {_format_cents(hard_cap)}. I prepared a proposal to move the warning amount "
        f"to {_format_cents(recommended_warn)} and the hard cap to {_format_cents(recommended_cap)} for you to review."
    )
    proposal = {
        "proposal_type": "adjust_budget_line_thresholds",
        "operations": [
            {
                "action": "update_budget_line",
                "budget_line_id": line_id,
                "fields": {"warn_at": recommended_warn, "hard_cap": recommended_cap},
            }
        ],
    }
    return [
        (
            "Where am I overspending most?",
            _json_message({"mode": "advice", "say": overspending_say, "question": None, "proposal": None}),
        ),
        (
            f"Can I still afford to spend more on {category} this month?",
            _json_message({"mode": "advice", "say": affordability_say, "question": None, "proposal": None}),
        ),
        (
            f"What adjustment would you suggest for {category}?",
            _json_message({"mode": "proposal", "say": proposal_say, "question": None, "proposal": proposal}),
        ),
    ]


def _history_summary(history: list[dict]) -> str:
    lines: list[str] = []
    for turn in history[-8:]:
        role = "User" if turn.get("role") == "user" else "Assistant"
        content = str(turn.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "No prior conversation in this month yet."


def build(message: str, history: list[dict], summary: dict, error: str | None = None) -> list[dict]:
    budget = summary.get("budget") or {}
    totals = summary.get("totals") or {}
    lines = summary.get("budget_lines") or []
    system_prompt = (
        "You are Tally, a budgeting assistant for one selected month. "
        "Respond with JSON only using exactly these keys: "
        '{"mode":"advice"|"clarify"|"proposal","say":"<string>","question":"<string|null>","proposal":<object|null>}. '
        "Never claim a budget change was applied. Proposals are suggestions only and must be reviewed by the user before anything changes. "
        "Never say you changed, updated, set, or adjusted the real budget data. When discussing a budget change, say you prepared or revised a proposal for review. "
        "You must ground every answer in the supplied budget data and recent conversation facts. "
        "Do not ask again for information the user already provided in the recent conversation. "
        "Keep factual budget answers separate from proposals. If the user asks where they are overspending or how they are tracking, answer directly from the current thresholds instead of proposing a change unless they explicitly ask for a suggestion or adjustment. "
        "Only create proposal mode for safe reviewable changes to existing budget-line warning or cap values. "
        "Budget-threshold proposals must stay directionally consistent with the user's request, must be plausible against current projected spend, and must not suggest tiny or obviously unrealistic amounts. "
        "If the user reacts to an existing suggestion with feedback like too high, too low, more, or less, revise the suggestion instead of repeating the same numbers. "
        "When using proposal mode, proposal must include proposal_type and one or more update_budget_line operations with integer budget_line_id plus warn_at or hard_cap fields. "
        "Always talk about money in decimal $ format, such as $50.00, $78.40, $1,000,000.00."
    )
    context_prompt = (
        f"Selected month: {budget.get('month')}\n"
        f"Income: {_format_cents(totals.get('declared_income', budget.get('declared_income')))}\n"
        f"Actual spend: {_format_cents(totals.get('actual_spend_total'))}\n"
        f"Planned spend: {_format_cents(totals.get('planned_est_high_total'))}\n"
        f"Projected remaining income: {_format_cents(totals.get('remaining_income_high'))}\n"
        "Budget lines:\n"
        + "\n".join(_line_summary(line) for line in lines[:12])
        + "\nRecent conversation:\n"
        + _history_summary(history)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": context_prompt},
    ]
    for user_text, assistant_json in _few_shot(summary):
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_json})
    messages.append({"role": "user", "content": message})
    if error:
        messages.append({"role": "user", "content": f"Your last response was invalid: {error}. Reply again with valid JSON only."})
    return messages
