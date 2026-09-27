import os
from datetime import datetime

import requests
from dateutil import parser
from fastmcp import FastMCP

mcp = FastMCP("Transactions")

TRANSACTIONS_DB_URL = os.getenv("TRANSACTIONS_DB_URL", "http://localhost:6001")
RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://localhost:5003")


@mcp.resource("docs://readme", mime_type="text/markdown")
def readme() -> str:
    return "Fetch transactions using requirements with the 'search_transactions' tool"

@mcp.tool()
def search_transactions(
    start_date: str | None = None,
    end_date: str | None = None,
    category_name: str | None = None,
    merchant: str | None = None,
    search_text: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
) -> list[dict]:
    """Search and filter transactions by date range, category, merchant, text and amount.

    Args:
        start_date: Earliest transaction date (inclusive). If omitted, searches from earliest transaction.
        end_date: Latest transaction date (inclusive). If omitted, searches up to current date.
        category_name: Name of category to filter by (case-insensitive). If omitted, returns all categories.
        merchant: Merchant name to filter by (case-insensitive exact match). If omitted, returns all merchants.
        search_text: Free-text search across merchant and description (case-insensitive substring). If omitted, no text filter.
        min_amount: Minimum transaction amount (inclusive). If omitted, no lower bound.
        max_amount: Maximum transaction amount (inclusive). If omitted, no upper bound.
    """
    start_dt = parser.parse(start_date) if start_date else None
    end_dt = parser.parse(end_date) if end_date else None

    if start_dt and not end_dt:
        end_dt = datetime.now()

    if start_dt and end_dt and start_dt > end_dt:
        raise ValueError("start_date must not be after end_date")

    min_value = _parse_amount(min_amount, "min_amount")
    max_value = _parse_amount(max_amount, "max_amount")

    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError("min_amount must not exceed max_amount")

    params = {}
    if start_dt:
        params["date_from"] = start_dt.date().isoformat()
    if end_dt:
        params["date_to"] = end_dt.date().isoformat()

    if category_name:
        params["category_name"] = category_name

    for name, value in (("merchant", merchant), ("search_text", search_text)):
        text = str(value).strip() if value is not None else ""
        if text:
            params[name] = text

    if min_value is not None:
        params["min_amount"] = min_value
    if max_value is not None:
        params["max_amount"] = max_value

    resp = requests.get(
        f"{TRANSACTIONS_DB_URL.rstrip('/')}/transactions",
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_amount(value, name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric") from None


@mcp.tool()
def retrieve_context(feature: str, question: str, k: int = 3) -> dict:
    """Return the documents in a feature's corpus that are closest to the question.

    Args:
        feature: Which feature's corpus to search, for example 'bills' or 'savings'.
        question: The question to find supporting documents for.
        k: How many documents to return.
    """
    resp = requests.post(
        f"{RAG_SERVER_URL.rstrip('/')}/retrieve",
        json={"feature": feature, "question": question, "k": k},
    )
    resp.raise_for_status()
    return resp.json()



if __name__ == "__main__":
    mcp.run(transport="http", port=8000)

