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


def format_planner_prompt(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
) -> str:
    def format_amount(val: Any) -> str:
        try:
            return f"${float(val):.2f}"
        except Exception:
            return f"${val}"

    past_suggestions = []
    for suggestion in (suggestions or []):
        suggestion_text = getattr(suggestion, "suggestion", suggestion.get("suggestion", "") if isinstance(suggestion, dict) else "")
        suggestion_accepted = getattr(suggestion, "accepted", suggestion.get("accepted", False) if isinstance(suggestion, dict) else False)
        suggestion_feedback = getattr(suggestion, "feedback", suggestion.get("feedback", None) if isinstance(suggestion, dict) else None)
        status = "ACCEPTED" if suggestion_accepted else "REJECTED"
        if suggestion_feedback:
            past_suggestions.append(f'[{status}] "{suggestion_text}" -> Feedback: "{suggestion_feedback}"')
        else:
            past_suggestions.append(f'[{status}] "{suggestion_text}"')

    category_map = {category.id: category.name for category in fetch_categories()}
    user_preferences = []
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
        user_preferences.append(preference)

    tables = {
        "active_goals": [
            {
                "goal": getattr(goal, "name", goal.get("name", "") if isinstance(goal, dict) else ""),
                "target_amount": format_amount(getattr(goal, "cost", goal.get("cost", 0) if isinstance(goal, dict) else 0)),
                "deadline": str(getattr(goal, "date", goal.get("date", "") if isinstance(goal, dict) else ""))[:10],
            }
            for goal in (goals or [])
        ],
        "past_suggestions": past_suggestions,
        "general_user_preferences": user_preferences,
    }

    return f"User Financial Data:\n{json.dumps(tables, indent=2)}"


def generate_transaction_search_args(feedbacks: List[dto.Feedback]) -> dict:
    tools = fetch_mcp_tools()
    if not tools:
        return {}

    categories = fetch_categories()
    category_names = [category.name for category in categories] if categories else []
    category_map = {category.id: category.name for category in categories}
    today_str = os.environ.get("DEMO_TODAY", date.today().isoformat())

    category_timeframe_items = [
        feedback_item
        for feedback_item in (feedbacks or [])
        if getattr(feedback_item, "category_id", None) is not None or getattr(feedback_item, "timeframe", None) is not None
    ]
    category_timeframe_lines = []
    for index, feedback_item in enumerate(reversed(category_timeframe_items), start=1):
        details = []
        category_name = category_map.get(getattr(feedback_item, "category_id", None))
        if category_name:
            details.append(f"Category: {category_name}")
        timeframe = getattr(feedback_item, "timeframe", None)
        if timeframe:
            details.append(f"Timeframe: {timeframe}")

        detail_str = f" [{', '.join(details)}]" if details else ""
        text = getattr(feedback_item, "feedback", "") or ""
        tag = " (Newest)" if index == 1 else ""
        category_timeframe_lines.append(f"{index}.{tag} \"{text.strip()}\"{detail_str}")

    category_timeframe_feedback = "\n".join(category_timeframe_lines) if category_timeframe_lines else "None"

    general_items = [
        feedback_item
        for feedback_item in (feedbacks or [])
        if getattr(feedback_item, "category_id", None) is None and getattr(feedback_item, "timeframe", None) is None
    ]
    background_preference_lines = [
        f"- {feedback_item.feedback.strip()}"
        for feedback_item in reversed(general_items)
        if getattr(feedback_item, "feedback", None) and str(feedback_item.feedback).strip()
    ]
    background_preferences = "\n".join(background_preference_lines) if background_preference_lines else "None"

    valid_categories = ", ".join(category_names) if category_names else "None"

    prompt_template = load_prompt("search_prompt.txt")
    search_prompt = prompt_template.format(
        today=today_str,
        category_timeframe_feedback=category_timeframe_feedback,
        background_preferences=background_preferences,
        valid_categories=valid_categories,
    ).strip()

    if category_names:
        for tool_definition in tools:
            if tool_definition.get("function", {}).get("name") == "search_transactions":
                tool_definition["function"]["parameters"].setdefault("properties", {}).setdefault("category_name", {})["enum"] = category_names

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
