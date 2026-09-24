from datetime import date
import json
import os
from typing import Any, List, Optional
from shared.backend import dto
from .helpers import fetch_categories, fetch_feedbacks, fetch_goals, fetch_suggestions
from .ollama_service import (
    execute_mcp_tool,
    fetch_mcp_tools,
    generate_tool_call_arguments,
    load_prompt,
    planner_model,
    prompt_text,
    search_model,
)


def _get_item_field(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def _format_amount(value: Any) -> str:
    """Formats numeric values as currency strings ($X.XX)."""
    try:
        return f"${float(value):.2f}"
    except Exception:
        return f"${value}"


def _format_active_goals(goals: List[dto.Goal]) -> list[dict]:
    """Extracts and formats active goals for the planner prompt."""
    return [
        {
            "goal": getattr(goal, "name", goal.get("name", "") if isinstance(goal, dict) else ""),
            "target_amount": _format_amount(getattr(goal, "cost", goal.get("cost", 0) if isinstance(goal, dict) else 0)),
            "deadline": str(getattr(goal, "date", goal.get("date", "") if isinstance(goal, dict) else ""))[:10],
        }
        for goal in (goals or [])
    ]


def _format_past_suggestions(suggestions: List[dto.Suggestion]) -> list[str]:
    """Formats past suggestions with their acceptance status and feedback rationale."""
    formatted_suggestions = []
    for suggestion in (suggestions or []):
        text = getattr(suggestion, "suggestion", suggestion.get("suggestion", "") if isinstance(suggestion, dict) else "")
        is_accepted = getattr(suggestion, "accepted", suggestion.get("accepted", False) if isinstance(suggestion, dict) else False)
        feedback_comment = getattr(suggestion, "feedback", suggestion.get("feedback", None) if isinstance(suggestion, dict) else None)
        status = "ACCEPTED" if is_accepted else "REJECTED"
        if feedback_comment:
            formatted_suggestions.append(f'[{status}] "{text}" -> Feedback: "{feedback_comment}"')
        else:
            formatted_suggestions.append(f'[{status}] "{text}"')
    return formatted_suggestions


def _format_user_preferences(
    feedbacks: List[dto.Feedback],
    category_map: dict[int, str],
) -> list[dict]:
    """Formats general user preferences (reversed so newest preferences appear first)."""
    preferences = []
    for feedback_item in reversed(feedbacks or []):
        if _get_item_field(feedback_item, "suggestion_id") is not None:
            continue
        preference = {
            "rule": _get_item_field(feedback_item, "feedback", "") or "",
        }
        category_id = _get_item_field(feedback_item, "category_id")
        if category_id is not None and category_id in category_map:
            preference["category"] = category_map[category_id]
        timeframe = _get_item_field(feedback_item, "timeframe")
        if timeframe:
            preference["timeframe"] = timeframe
        preferences.append(preference)
    return preferences


def _format_category_timeframe_feedback(
    feedbacks: List[dto.Feedback],
    category_map: dict[int, str],
) -> str:
    """Formats all feedbacks that specify category/timeframe (reversed, newest first)."""
    category_timeframe_items = [
        item
        for item in (feedbacks or [])
        if _get_item_field(item, "category_id") is not None or _get_item_field(item, "timeframe") is not None
    ]
    if not category_timeframe_items:
        return "None"

    lines = []
    for index, item in enumerate(reversed(category_timeframe_items), start=1):
        details = []
        category_name = category_map.get(_get_item_field(item, "category_id"))
        if category_name:
            details.append(f"Category: {category_name}")
        timeframe = _get_item_field(item, "timeframe")
        if timeframe:
            details.append(f"Timeframe: {timeframe}")

        detail_str = f" [{', '.join(details)}]" if details else ""
        text = _get_item_field(item, "feedback", "") or ""
        tag = " (Newest)" if index == 1 else ""
        lines.append(f"{index}.{tag} \"{str(text).strip()}\"{detail_str}")

    return "\n".join(lines)


def _format_background_preferences(feedbacks: List[dto.Feedback]) -> str:
    """Formats general constraint feedbacks without category/timeframe (reversed, newest first)."""
    general_items = [
        item
        for item in (feedbacks or [])
        if _get_item_field(item, "category_id") is None and _get_item_field(item, "timeframe") is None
    ]
    lines = [
        f"- {str(_get_item_field(item, 'feedback', '')).strip()}"
        for item in reversed(general_items)
        if _get_item_field(item, "feedback") and str(_get_item_field(item, "feedback")).strip()
    ]
    return "\n".join(lines) if lines else "None"


def format_planner_prompt(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
    tx_url: Optional[str] = None,
) -> str:
    """Constructs the structured JSON data block for the 8B planner prompt."""
    categories = fetch_categories(tx_url)
    category_map = {category.id: category.name for category in categories} if categories else {}
    tables = {
        "active_goals": _format_active_goals(goals),
        "past_suggestions": _format_past_suggestions(suggestions),
        "general_user_preferences": _format_user_preferences(feedbacks, category_map),
    }
    return f"User Financial Data:\n{json.dumps(tables, indent=2)}"


def generate_transaction_search_args(feedbacks: List[dto.Feedback], tx_url: Optional[str] = None) -> dict:
    """Prompts the search tool model to determine search_transactions arguments based on user feedback."""
    tools = fetch_mcp_tools()
    if not tools:
        return {}

    categories = fetch_categories(tx_url)
    category_names = [category.name for category in categories] if categories else []
    category_map = {category.id: category.name for category in categories} if categories else {}
    today_str = os.environ.get("DEMO_TODAY", date.today().isoformat())

    search_prompt = load_prompt("search_prompt.txt").format(
        today=today_str,
        category_timeframe_feedback=_format_category_timeframe_feedback(feedbacks, category_map),
        background_preferences=_format_background_preferences(feedbacks),
        valid_categories=", ".join(category_names) if category_names else "None",
    ).strip()

    if category_names:
        for tool_definition in tools:
            if tool_definition.get("function", {}).get("name") == "search_transactions":
                tool_definition["function"]["parameters"].setdefault("properties", {}).setdefault(
                    "category_name", {}
                )["enum"] = category_names

    tool_args = generate_tool_call_arguments(
        search_prompt,
        tools=tools,
        model=search_model,
        temperature=0.0,
    )

    if category_names and tool_args.get("category_name") not in category_names:
        tool_args.pop("category_name", None)

    return {key: value for key, value in tool_args.items() if value is not None and value != ""}


def _format_transactions_for_prompt(
    transactions: list[dict],
    category_map: dict[int, str],
) -> list[dict]:
    """Formats and enriches transactions with readable dates, amounts, and category names."""
    formatted = []
    for tx in (transactions or []):
        item = {
            "date": str(tx.get("date", ""))[:10],
            "merchant": tx.get("merchant", ""),
            "description": tx.get("description", ""),
            "amount": _format_amount(tx.get("amount", 0)),
        }
        category_id = tx.get("category_id")
        if category_id is not None and category_id in category_map:
            item["category"] = category_map[category_id]
        formatted.append(item)
    return formatted


def generate_advice(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
    tx_url: Optional[str] = None,
) -> str:
    """Coordinates retrieval of transactions via MCP and prompts the planner model to generate savings advice."""
    categories = fetch_categories(tx_url)
    category_map = {category.id: category.name for category in categories} if categories else {}
    user_data = format_planner_prompt(goals, suggestions, feedbacks, tx_url=tx_url)

    search_args = generate_transaction_search_args(feedbacks, tx_url=tx_url)
    transactions = execute_mcp_tool("search_transactions", search_args)
    if not transactions:
        if search_args:
            all_transactions = execute_mcp_tool("search_transactions", {})
            if all_transactions:
                filter_parts = []
                if "category_name" in search_args:
                    filter_parts.append(f"in category '{search_args['category_name']}'")
                if "start_date" in search_args or "end_date" in search_args:
                    filter_parts.append("within the specified timeframe")
                filter_str = " ".join(filter_parts) if filter_parts else "matching your filter"
                return f"No transactions found {filter_str}. Try broadening your feedback or checking other categories."
        return "You don't have any transactions yet. Add transactions using the transactions tab."

    formatted_transactions = _format_transactions_for_prompt(transactions, category_map)

    system_prompt = load_prompt("savings_prompt.txt")
    user_prompt = (
        f"{user_data}\n\n"
        f"Retrieved Transactions from MCP search_transactions:\n{json.dumps(formatted_transactions, indent=2)}\n\n"
        "Execute the ACT phase of the Plan-Act-Observe-Adapt loop by delivering 1 or 2 specialized, personalized savings advice sentences directly to me in plain text without preamble or markdown bolding:\n"
        "- Begin immediately with the first word of the advice (no intro, heading, or colon).\n"
        "- Ground advice in specific merchants and amounts from retrieved transactions and connect to an exact active goal name.\n"
        "- Do not repeat merchants in past_suggestions; follow user preferences and cadence rules."
    )
    return prompt_text(
        user_prompt,
        model=planner_model,
        system_prompt=system_prompt,
        temperature=0.4,
    )


def generate_savings_advice(db_url: str, tx_url: Optional[str] = None) -> str:
    """Top-level entry point to fetch data and generate personalized savings advice."""
    goals = fetch_goals(db_url)
    if not goals:
        return (
            "You don't have any active savings goals yet. "
            "Add a goal in the Savings Goals table to receive personalized, adaptive savings advice!"
        )

    feedbacks = fetch_feedbacks(db_url)
    suggestions = fetch_suggestions(db_url)

    try:
        advice = generate_advice(goals, suggestions, feedbacks, tx_url=tx_url)
        if advice:
            return advice
        return "Error: Could not generate AI savings suggestion (empty response received from AI model)."
    except Exception as e:
        return f"Error: Could not generate AI savings suggestion ({e})."
