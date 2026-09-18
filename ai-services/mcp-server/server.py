import os
from datetime import datetime

import requests
from dateutil import parser
from fastmcp import FastMCP

mcp = FastMCP("Transactions")

TRANSACTIONS_DB_URL = os.getenv("TRANSACTIONS_DB_URL", "http://localhost:6001")
ANOMALIES_DB_URL = os.getenv("ANOMALIES_DB_URL", "http://localhost:6004/anomalies")


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

def _get_transactions_with_anomaly_status(is_confirmed: bool) -> list[dict]:
    anomalies_response = requests.get(ANOMALIES_DB_URL.rstrip("/"))
    anomalies_response.raise_for_status()
    anomalies = [
        anomaly for anomaly in anomalies_response.json()
        if anomaly.get("is_confirmed_by_user") is is_confirmed
    ]

    transactions_response = requests.get(
        f"{TRANSACTIONS_DB_URL.rstrip('/')}/transactions")
    transactions_response.raise_for_status()
    transactions_by_id = {
        transaction["id"]: transaction
        for transaction in transactions_response.json()
    }

    return [
        {
            "transaction": transactions_by_id[anomaly["transaction_id"]],
            "anomaly": anomaly,
        }
        for anomaly in anomalies
        if anomaly["transaction_id"] in transactions_by_id
    ]

@mcp.tool()
def get_transactions_with_confirmed_anomalies() -> list[dict]:
    """Return transactions whose anomalies the user confirmed as suspicious."""
    return _get_transactions_with_anomaly_status(True)

@mcp.tool()
def get_transactions_with_rejected_anomalies() -> list[dict]:
    """Return transactions whose anomalies the user rejected as not suspicious."""
    return _get_transactions_with_anomaly_status(False)



if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
