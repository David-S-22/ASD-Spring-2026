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


def _proposal_feedback_summary(summary: dict) -> str:
    proposals = summary.get("coach_proposals")
    if not isinstance(proposals, list):
        return "No prior proposal outcomes recorded for this month."
    lines: list[str] = []
    for proposal in proposals[-6:]:
        if not isinstance(proposal, dict):
            continue
        status = proposal.get("status")
        rationale = str(proposal.get("rationale") or "").strip()
        rejection_reason = str(proposal.get("rejection_reason") or "").strip()
        if status == "rejected":
            lines.append(
                f"Rejected proposal: {rejection_reason or rationale or 'No rejection reason recorded.'}"
            )
        elif status == "accepted":
            lines.append(
                f"Accepted proposal: {rationale or 'Applied after user approval.'}"
            )
    return "\n".join(lines) if lines else "No prior proposal outcomes recorded for this month."


def _mcp_context_summary(chat_context: dict | None) -> str:
    if not isinstance(chat_context, dict):
        return "No shared MCP transaction evidence attached."
    mcp_transactions = chat_context.get("mcp_transactions")
    if not isinstance(mcp_transactions, dict):
        return "No shared MCP transaction evidence attached."
    preview = mcp_transactions.get("result_preview")
    if not isinstance(preview, list) or not preview:
        return "Shared MCP transaction search returned no matching preview rows."
    lines = [
        (
            f"- {item.get('date') or 'unknown date'} | "
            f"{item.get('merchant') or item.get('description') or 'unknown merchant'} | "
            f"{_format_cents(int(round(float(item.get('amount', 0)) * 100))) if isinstance(item.get('amount'), (int, float)) and not isinstance(item.get('amount'), bool) else 'unknown amount'}"
        )
        for item in preview[:5]
        if isinstance(item, dict)
    ]
    total_amount = mcp_transactions.get("total_matched_amount")
    total_text = f"${float(total_amount):,.2f}" if isinstance(total_amount, (int, float)) and not isinstance(total_amount, bool) else "unknown"
    scope = str(mcp_transactions.get("scope") or "this budget context")
    return (
        f"Shared MCP transaction evidence for {scope}: {mcp_transactions.get('count', 0)} match(es), total {total_text}.\n"
        + "\n".join(lines)
    )


def _rag_context_summary(chat_context: dict | None) -> str:
    if not isinstance(chat_context, dict):
        return "No retrieved shared budget guidance attached."
    rag_guidance = chat_context.get("rag_guidance")
    if not isinstance(rag_guidance, dict):
        return "No retrieved shared budget guidance attached."
    retrieval = rag_guidance.get("retrieval")
    if not isinstance(retrieval, list) or not retrieval:
        return "No retrieved shared budget guidance attached."
    lines: list[str] = []
    for item in retrieval[:3]:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("id") or "retrieved-source")
        text = str(item.get("text") or "").strip().replace("\r", " ").replace("\n", " ")
        if len(text) > 220:
            text = text[:217].rstrip() + "..."
        lines.append(f"- {source}: {text}")
    return "Retrieved shared budget guidance:\n" + ("\n".join(lines) if lines else "No retrieved shared budget guidance attached.")


def _context_hint_summary(chat_context: dict | None) -> str:
    if not isinstance(chat_context, dict):
        return "No UI context hints attached."
    hints = chat_context.get("context_hints")
    if not isinstance(hints, dict) or not hints:
        return "No UI context hints attached."
    parts: list[str] = []
    for key in ("ui_action", "target_category", "target_budget_line_id", "target_planned_event_id"):
        value = hints.get(key)
        if value is None or value == "":
            continue
        parts.append(f"{key}={value}")
    return ", ".join(parts) if parts else "No UI context hints attached."


def _computed_budget_context_summary(chat_context: dict | None) -> str:
    if not isinstance(chat_context, dict):
        return "No computed budget facts attached."
    computed = chat_context.get("computed_budget_context")
    if not isinstance(computed, dict):
        return "No computed budget facts attached."

    kind = computed.get("kind")
    if kind == "affordability":
        requested = _format_cents(computed.get("requested_amount_cents"))
        remaining_before = _format_cents(computed.get("remaining_income_before_cents"))
        remaining_after = _format_cents(computed.get("remaining_income_after_cents"))
        needs_amount = bool(computed.get("needs_amount_clarification"))
        line = computed.get("line")
        if not isinstance(line, dict):
            if needs_amount:
                return "- Affordability check needs the user to provide an amount before exact budget impact can be explained."
            return (
                f"- Requested spend: {requested}\n"
                f"- Remaining income before spend: {remaining_before}\n"
                f"- Remaining income after spend: {remaining_after}\n"
                "- No specific budget line is currently resolved."
            )
        return (
            f"- Affordability target: {line.get('category') or 'Unknown category'}\n"
            f"- Requested spend: {requested}\n"
            f"- Remaining income before spend: {remaining_before}\n"
            f"- Remaining income after spend: {remaining_after}\n"
            f"- Actual spend: {_format_cents(line.get('actual_spend_cents'))}\n"
            f"- Planned spend: {_format_cents(line.get('planned_spend_cents'))}\n"
            f"- Current projected spend: {_format_cents(line.get('projected_spend_cents'))}\n"
            f"- Projected spend after request: {_format_cents(line.get('projected_after_spend_cents'))}\n"
            f"- Warning amount: {_format_cents(line.get('warn_at_cents'))}\n"
            f"- Hard cap: {_format_cents(line.get('hard_cap_cents'))}\n"
            f"- Current threshold state: {line.get('threshold_state') or 'unknown'}\n"
            f"- Threshold state after request: {line.get('threshold_state_after_spend') or 'unknown'}"
        )

    if kind == "pressure":
        lines = computed.get("top_lines")
        if not isinstance(lines, list) or not lines:
            return "No computed budget facts attached."
        focus_line = computed.get("focus_line")
        parts: list[str] = []
        if isinstance(focus_line, dict):
            parts.append(
                f"- Focus line: {focus_line.get('category') or 'Unknown category'} at {_format_cents(focus_line.get('projected_spend_cents'))}, "
                f"state={focus_line.get('threshold_state') or 'unknown'}, driver={focus_line.get('primary_pressure_source') or 'unknown'}"
            )
        parts.append("- Top pressure lines:")
        for line in lines[:3]:
            if not isinstance(line, dict):
                continue
            parts.append(
                f"  - {line.get('category') or 'Unknown category'} | projected {_format_cents(line.get('projected_spend_cents'))} | "
                f"warn {_format_cents(line.get('warn_at_cents'))} | cap {_format_cents(line.get('hard_cap_cents'))} | "
                f"state={line.get('threshold_state') or 'unknown'} | driver={line.get('primary_pressure_source') or 'unknown'}"
            )
        return "\n".join(parts)

    return "No computed budget facts attached."


def build(message: str, history: list[dict], summary: dict, chat_context: dict | None = None, error: str | None = None) -> list[dict]:
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
        "When computed budget facts are supplied, treat them as authoritative for numeric claims, threshold state, and affordability impact. "
        "When shared transaction evidence or retrieved guidance is supplied, use it explicitly and do not contradict it. "
        "Keep actual spend, planned spend, and projected spend clearly separated and labelled. "
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
        + "\nProposal feedback:\n"
        + _proposal_feedback_summary(summary)
        + "\nContext hints:\n"
        + _context_hint_summary(chat_context)
        + "\nComputed budget facts:\n"
        + _computed_budget_context_summary(chat_context)
        + "\nShared MCP transaction evidence:\n"
        + _mcp_context_summary(chat_context)
        + "\nRetrieved guidance:\n"
        + _rag_context_summary(chat_context)
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
