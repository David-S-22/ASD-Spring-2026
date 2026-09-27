from datetime import date
import json
import os
from typing import Any
from shared.backend import dto
from .helpers import fetch_categories, fetch_feedbacks, fetch_goals, fetch_suggestions
from .ollama_service import (
    execute_mcp_tool,
    fetch_mcp_tools,
    load_prompt,
    planner_model,
    prompt_text_and_calculate_confidence,
    prompt_tool_call,
    search_model,
)

def _get_item_field(item: dict[str, Any] | Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)

def _format_amount(value: int | float | str | None) -> str:
    """Formats numeric values as currency strings ($X.XX)."""
    try:
        return f"${float(value):.2f}"
    except Exception:
        return f"${value}"

def _format_active_goals(goals: list[dto.Goal] | list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Extracts and formats active goals for the planner prompt."""
    return [
        {
            "goal": str(_get_item_field(goal, "name", "") or ""),
            "target_amount": _format_amount(_get_item_field(goal, "cost", 0)),
            "deadline": str(_get_item_field(goal, "date", "") or "")[:10],
        }
        for goal in (goals or [])
    ]

def _format_past_suggestions(suggestions: list[dto.Suggestion] | list[dict[str, Any]] | None) -> list[str]:
    """Formats past suggestions with their acceptance status and feedback rationale."""
    formatted_suggestions = []
    for suggestion in (suggestions or []):
        text = str(_get_item_field(suggestion, "suggestion", "") or "")
        if text and "\n\n" in text:
            text = text.split("\n\n")[0].strip()
        is_accepted = bool(_get_item_field(suggestion, "accepted", False))
        feedback_comment = _get_item_field(suggestion, "feedback", None)
        status = "ACCEPTED" if is_accepted else "REJECTED"
        if feedback_comment:
            formatted_suggestions.append(f'[{status}] "{text}" -> Feedback: "{feedback_comment}"')
        else:
            formatted_suggestions.append(f'[{status}] "{text}"')
    return formatted_suggestions

def _format_user_preferences(
    feedbacks: list[dto.Feedback] | list[dict[str, Any]] | None,
    category_map: dict[int, str],
) -> list[dict[str, str]]:
    """Formats general user preferences (reversed so newest preferences appear first)."""
    preferences = []
    for feedback_item in reversed(feedbacks or []):
        if _get_item_field(feedback_item, "suggestion_id") is not None:
            continue
        preference = {
            "rule": str(_get_item_field(feedback_item, "feedback", "") or ""),
        }
        category_id = _get_item_field(feedback_item, "category_id")
        if category_id is not None and category_id in category_map:
            preference["category"] = category_map[category_id]
        timeframe = _get_item_field(feedback_item, "timeframe")
        if timeframe:
            preference["timeframe"] = str(timeframe)
        preferences.append(preference)
    return preferences

def _format_category_timeframe_feedback(
    feedbacks: list[dto.Feedback] | list[dict[str, Any]] | None,
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

def _format_background_preferences(feedbacks: list[dto.Feedback] | list[dict[str, Any]] | None) -> str:
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
    goals: list[dto.Goal] | list[dict[str, Any]] | None,
    suggestions: list[dto.Suggestion] | list[dict[str, Any]] | None,
    feedbacks: list[dto.Feedback] | list[dict[str, Any]] | None,
    tx_url: str | None = None,
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

def generate_transaction_search_tool_call(
    feedbacks: list[dto.Feedback] | list[dict[str, Any]] | None,
    tx_url: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Prompts the search tool model with all available MCP tools to select the transaction querying tool and arguments based on user feedback."""
    tools = fetch_mcp_tools()
    if not tools:
        return "search_transactions", {}

    categories = fetch_categories(tx_url)
    category_names = [category.name for category in categories] if categories else []
    category_map = {category.id: category.name for category in categories} if categories else {}
    today_str = date.today().isoformat()

    search_prompt = load_prompt("search_prompt.txt").format(
        today=today_str,
        category_timeframe_feedback=_format_category_timeframe_feedback(feedbacks, category_map),
        background_preferences=_format_background_preferences(feedbacks),
        valid_categories=", ".join(category_names) if category_names else "None",
    ).strip()

    if category_names:
        for tool_definition in tools:
            props = (
                tool_definition.get("function", {})
                .get("parameters", {})
                .get("properties", {})
            )
            if "category_name" in props:
                props["category_name"]["enum"] = category_names

    system_prompt = (
        "You are a financial data assistant. Select and invoke the tool that queries user transactions. "
        "Do not invoke document retrieval or other tools."
    )

    tool_name, tool_args, _ = prompt_tool_call(
        search_prompt,
        tools=tools,
        model=search_model,
        system_prompt=system_prompt,
        temperature=0.0,
    )

    cat_val = tool_args.get("category_name")
    if cat_val and category_names:
        matched_cat = next(
            (c for c in category_names if c.lower() == str(cat_val).lower()),
            None,
        )
        if matched_cat:
            tool_args["category_name"] = matched_cat

    cleaned_args = {key: value for key, value in tool_args.items() if value is not None and value != ""}
    return tool_name or "search_transactions", cleaned_args


def generate_context_retrieval_args(
    goals: list[dto.Goal] | list[dict[str, Any]] | None = None,
    k: int = 3,
) -> dict[str, str | int]:
    """
    Constructs arguments for the retrieve_context MCP tool targeting savings advice.
    Formulates a targeted question on how to generate savings advice.
    """
    question = "advice about how to generate savings advice"
    if goals:
        goal_name = _get_item_field(goals[0], "name")
        if goal_name:
            question = f"advice about how to generate savings advice towards {goal_name}"
    return {
        "feature": "savings",
        "question": question,
        "k": k,
    }

def _format_transactions_for_prompt(
    transactions: list[dict[str, Any]] | None,
    category_map: dict[int, str],
) -> list[dict[str, str]]:
    """Formats and enriches transactions with readable dates, amounts, and category names."""
    formatted = []
    for tx in (transactions or []):
        item = {
            "date": str(tx.get("date", ""))[:10],
            "merchant": str(tx.get("merchant", "") or ""),
            "description": str(tx.get("description", "") or ""),
            "amount": _format_amount(tx.get("amount", 0)),
        }
        category_id = tx.get("category_id")
        if category_id is not None and category_id in category_map:
            item["category"] = category_map[category_id]
        formatted.append(item)
    return formatted

def _aggregate_spending_by_merchant(
    transactions: list[dict[str, Any]] | None,
    category_map: dict[int, str],
) -> list[dict[str, Any]]:
    """Aggregates spending totals and transaction counts grouped by merchant."""
    merchants: dict[str, dict[str, Any]] = {}
    for tx in (transactions or []):
        merchant = str(tx.get("merchant") or "Unknown").strip()
        try:
            amount = float(tx.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0.0

        category_id = tx.get("category_id")
        category_name = None
        if category_id is not None and category_id in category_map:
            category_name = category_map[category_id]
        elif "category" in tx:
            category_name = tx.get("category")

        if merchant not in merchants:
            merchants[merchant] = {
                "merchant": merchant,
                "total_spent_raw": 0.0,
                "transaction_count": 0,
                "categories": set(),
            }
        merchants[merchant]["total_spent_raw"] += amount
        merchants[merchant]["transaction_count"] += 1
        if category_name:
            merchants[merchant]["categories"].add(category_name)

    sorted_merchants = sorted(
        merchants.values(),
        key=lambda m: m["total_spent_raw"],
        reverse=True,
    )

    aggregated = []
    for m in sorted_merchants:
        aggregated.append({
            "merchant": m["merchant"],
            "total_spent": _format_amount(m["total_spent_raw"]),
            "transaction_count": m["transaction_count"],
            "category": ", ".join(sorted(m["categories"])) if m["categories"] else "Uncategorized",
        })
    return aggregated

def _fetch_filtered_transactions(
    feedbacks: list[dto.Feedback] | list[dict[str, Any]] | None,
    tx_url: str | None = None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Executes transaction search tool call derived from user feedbacks.
    Returns (transactions, None) on success, or (None, fallback_message) if no transactions exist.
    """
    tool_name, search_args = generate_transaction_search_tool_call(feedbacks, tx_url=tx_url)
    transactions = execute_mcp_tool(tool_name, search_args)
    if not transactions:
        if search_args:
            all_transactions = execute_mcp_tool(tool_name, {})
            if all_transactions:
                filter_parts = []
                if "category_name" in search_args:
                    filter_parts.append(f"in category '{search_args['category_name']}'")
                if "start_date" in search_args or "end_date" in search_args:
                    filter_parts.append("within the specified timeframe")
                filter_str = " ".join(filter_parts) if filter_parts else "matching your filter"
                return None, f"No transactions found {filter_str}. Try broadening your feedback or checking other categories."
        return None, "You don't have any transactions yet. Add transactions using the transactions tab."
    return transactions, None


def _extract_rag_sources(rag_docs: list[dict[str, Any]]) -> str:
    """Extracts unique source citations from retrieved RAG documents."""
    sources: list[str] = []
    for doc in rag_docs:
        source_name = doc.get("metadata", {}).get("source")
        if source_name and source_name not in sources:
            sources.append(source_name)
    return ", ".join(sources) if sources else "savings_advice_guide.md"


def _fetch_rag_guidelines(
    goals: list[dto.Goal] | list[dict[str, Any]] | None,
) -> tuple[str, str] | None:
    """
    Retrieves savings advice guidelines from the RAG knowledge base via MCP retrieve_context.
    Returns (context_blocks, sources_str) if sufficient context exists, otherwise None.
    """
    rag_args = generate_context_retrieval_args(goals)
    try:
        rag_response = execute_mcp_tool("retrieve_context", rag_args)
    except Exception:
        rag_response = None

    rag_results = rag_response.get("results", []) if isinstance(rag_response, dict) else []
    valid_rag_docs = [doc for doc in rag_results if doc.get("text", "").strip()]

    # Ensure advice is NOT generated if the AI has an insufficient amount of context
    if not valid_rag_docs or sum(len(doc.get("text", "").strip()) for doc in valid_rag_docs) < 30:
        return None

    sources_str = _extract_rag_sources(valid_rag_docs)
    rag_context_blocks = "\n".join([
        f"- [Source: {doc.get('metadata', {}).get('source', 'Unknown')}]: {doc.get('text', '').strip()}"
        for doc in valid_rag_docs
    ])
    return rag_context_blocks, sources_str


def _build_advice_prompt(
    user_data: str,
    spending_summary: list[dict[str, Any]],
    formatted_transactions: list[dict[str, str]],
    rag_context_blocks: str,
) -> str:
    """Constructs the prompt for the savings advice planner model."""
    return (
        f"{user_data}\n\n"
        f"Pre-Calculated Spending Summary by Merchant:\n{json.dumps(spending_summary, indent=2)}\n\n"
        f"Retrieved Transactions:\n{json.dumps(formatted_transactions, indent=2)}\n\n"
        f"Retrieved Savings Advice Guidelines:\n{rag_context_blocks}\n\n"
        "Deliver 1 or 2 personalized savings advice sentences in a single plain text paragraph based on the guidelines and spending data. "
        "If context is insufficient, reply strictly with: Insufficient context to generate savings advice."
    )


def generate_advice(
    goals: list[dto.Goal] | list[dict[str, Any]] | None,
    suggestions: list[dto.Suggestion] | list[dict[str, Any]] | None,
    feedbacks: list[dto.Feedback] | list[dict[str, Any]] | None,
    tx_url: str | None = None,
) -> str:
    """Coordinates retrieval of transactions & RAG context via MCP and prompts the planner model to generate savings advice."""
    if not goals:
        return "Insufficient context available to generate savings advice."

    transactions, tx_error = _fetch_filtered_transactions(feedbacks, tx_url=tx_url)
    if tx_error is not None or not transactions:
        return tx_error or "You don't have any transactions yet. Add transactions using the transactions tab."

    categories = fetch_categories(tx_url)
    category_map = {category.id: category.name for category in categories} if categories else {}
    formatted_transactions = _format_transactions_for_prompt(transactions, category_map)
    spending_summary = _aggregate_spending_by_merchant(transactions, category_map)

    rag_guidelines = _fetch_rag_guidelines(goals)
    if not rag_guidelines:
        return "Insufficient context available to generate savings advice."
    rag_context_blocks, sources_str = rag_guidelines

    user_data = format_planner_prompt(goals, suggestions, feedbacks, tx_url=tx_url)
    system_prompt = load_prompt("savings_prompt.txt")
    user_prompt = _build_advice_prompt(user_data, spending_summary, formatted_transactions, rag_context_blocks)

    raw_advice, confidence_category = prompt_text_and_calculate_confidence(
        user_prompt,
        model=planner_model,
        system_prompt=system_prompt,
        temperature=0.0,
    )

    if not raw_advice or raw_advice.strip().lower().startswith("insufficient context"):
        return "Insufficient context available to generate savings advice."

    advice_lines = [line.strip() for line in raw_advice.strip().splitlines() if line.strip()]
    advice_paragraph = " ".join(advice_lines)
    metadata_paragraph = f"Sources: {sources_str} | Confidence: {confidence_category}"
    return f"{advice_paragraph}\n\n{metadata_paragraph}"


def generate_savings_advice(db_url: str, tx_url: str | None = None) -> str:
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
