from datetime import date
import json
import os
from typing import Any, List
from shared.backend import dto
from .helpers import fetch_categories, fetch_feedbacks, fetch_goals, fetch_suggestions
from .ollama_service import (
    execute_mcp_tool,
    fetch_mcp_tools,
    generate_tool_call_arguments,
    load_prompt,
    planner_model,
    prompt_model,
    search_model,
)


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
        if getattr(feedback_item, "suggestion_id", feedback_item.get("suggestion_id") if isinstance(feedback_item, dict) else None) is not None:
            continue
        preference = {
            "rule": getattr(feedback_item, "feedback", feedback_item.get("feedback", "") if isinstance(feedback_item, dict) else ""),
        }
        category_id = getattr(feedback_item, "category_id", feedback_item.get("category_id") if isinstance(feedback_item, dict) else None)
        if category_id is not None and category_id in category_map:
            preference["category"] = category_map[category_id]
        timeframe = getattr(feedback_item, "timeframe", feedback_item.get("timeframe") if isinstance(feedback_item, dict) else None)
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
        if getattr(item, "category_id", None) is not None or getattr(item, "timeframe", None) is not None
    ]
    if not category_timeframe_items:
        return "None"

    lines = []
    for index, item in enumerate(reversed(category_timeframe_items), start=1):
        details = []
        category_name = category_map.get(getattr(item, "category_id", None))
        if category_name:
            details.append(f"Category: {category_name}")
        timeframe = getattr(item, "timeframe", None)
        if timeframe:
            details.append(f"Timeframe: {timeframe}")

        detail_str = f" [{', '.join(details)}]" if details else ""
        text = getattr(item, "feedback", "") or ""
        tag = " (Newest)" if index == 1 else ""
        lines.append(f"{index}.{tag} \"{text.strip()}\"{detail_str}")

    return "\n".join(lines)


def _format_background_preferences(feedbacks: List[dto.Feedback]) -> str:
    """Formats general constraint feedbacks without category/timeframe (reversed, newest first)."""
    general_items = [
        item
        for item in (feedbacks or [])
        if getattr(item, "category_id", None) is None and getattr(item, "timeframe", None) is None
    ]
    lines = [
        f"- {item.feedback.strip()}"
        for item in reversed(general_items)
        if getattr(item, "feedback", None) and str(item.feedback).strip()
    ]
    return "\n".join(lines) if lines else "None"


def format_planner_prompt(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
) -> str:
    """Constructs the structured JSON data block for the 8B planner prompt."""
    category_map = {category.id: category.name for category in fetch_categories()}
    tables = {
        "active_goals": _format_active_goals(goals),
        "past_suggestions": _format_past_suggestions(suggestions),
        "general_user_preferences": _format_user_preferences(feedbacks, category_map),
    }
    return f"User Financial Data:\n{json.dumps(tables, indent=2)}"


def generate_transaction_search_args(feedbacks: List[dto.Feedback]) -> dict:
    """Prompts the search tool model to determine search_transactions arguments based on user feedback."""
    tools = fetch_mcp_tools()
    if not tools:
        return {}

    categories = fetch_categories()
    category_names = [category.name for category in categories] if categories else []
    category_map = {category.id: category.name for category in categories}
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


def generate_advice(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
) -> str:
    """Coordinates retrieval of transactions via MCP and prompts the planner model to generate savings advice."""
    user_data = format_planner_prompt(goals, suggestions, feedbacks)

    search_args = generate_transaction_search_args(feedbacks)
    transactions = execute_mcp_tool("search_transactions", search_args)
    if not transactions:
        return "You don't have any transactions yet. Add transactions using the transactions tab."

    system_prompt = load_prompt("savings_prompt.txt")
    user_prompt = (
        f"{user_data}\n\n"
        f"Retrieved Transactions from MCP search_transactions:\n{json.dumps(transactions, indent=2)}\n\n"
        "Deliver 1 or 2 natural, well-phrased savings advice sentences that help the user reduce expenses toward an active goal, starting immediately with the first word of the advice."
    )
    return prompt_model(
        user_prompt,
        model=planner_model,
        system_prompt=system_prompt,
        temperature=0.4,
    )


def generate_savings_advice(db_url: str) -> str:
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
        advice = generate_advice(goals, suggestions, feedbacks)
        if advice:
            return advice
        return "Error: Could not generate AI savings suggestion (empty response received from AI model)."
    except Exception as e:
        return f"Error: Could not generate AI savings suggestion ({e})."
