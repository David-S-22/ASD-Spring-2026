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
    start_date: str = None,
    end_date: str = None,
    category_name: str = None,
) -> list[dict]:
    """Search and filter transactions by date range and category name.

    Args:
        start_date: Earliest transaction date (inclusive). If omitted, searches from earliest transaction.
        end_date: Latest transaction date (inclusive). If omitted, searches up to current date.
        category_name: Name of category to filter by (case-insensitive). If omitted, returns all categories.
    """
    start_dt = parser.parse(start_date) if start_date else None
    end_dt = parser.parse(end_date) if end_date else None

    if start_dt and not end_dt:
        end_dt = datetime.now()

    if start_dt and end_dt and start_dt > end_dt:
        raise ValueError("start_date must not be after end_date")

    params = {}
    if start_dt:
        params["date_from"] = start_dt.date().isoformat()
    if end_dt:
        params["date_to"] = end_dt.date().isoformat()

    if category_name:
        params["category_name"] = category_name

    resp = requests.get(f"{TRANSACTIONS_DB_URL.rstrip('/')}/transactions", params=params)
    resp.raise_for_status()
    return resp.json()



@mcp.tool()
def retrieve_context(feature: str, question: str, k: int = 3) -> dict:
    """Return the documents in a feature's corpus that are closest to the question.

    Args:
        feature: Which feature's corpus to search, for example 'bills'.
        question: The question to find supporting documents for.
        k: How many documents to return.
    """
    resp = requests.post(f"{RAG_SERVER_URL.rstrip('/')}/retrieve", json={"feature": feature, "question": question, "k": k})
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def answer_question(feature: str, question: str, k: int = 3, role: str = "generation") -> dict:
    """Answer a question from a feature's corpus and list the documents used.

    Args:
        feature: Which feature's corpus to answer from, for example 'bills'.
        question: The question to answer.
        k: How many documents to answer from.
        role: Which model answers: 'generation' (default) or 'reasoning' for questions that need working out.
    """
    resp = requests.post(f"{RAG_SERVER_URL.rstrip('/')}/answer", json={"feature": feature, "question": question, "k": k, "role": role})
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def review_answer(feature: str, question: str, answer: str, k: int = 3) -> dict:
    """Check whether an answer is supported by a feature's corpus.

    Args:
        feature: Which feature's corpus to check against, for example 'bills'.
        question: The question the answer was written for.
        answer: The answer to check.
        k: How many documents to check against.
    """
    resp = requests.post(f"{RAG_SERVER_URL.rstrip('/')}/review", json={"feature": feature, "question": question, "answer": answer, "k": k})
    resp.raise_for_status()
    return resp.json()



if __name__ == "__main__":
    mcp.run(transport="http", port=8000)

