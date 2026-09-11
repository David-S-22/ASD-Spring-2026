import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dateutil import parser
from fastmcp import FastMCP

mcp = FastMCP("Transactions")

TRANSACTIONS_DB_URL = os.getenv("TRANSACTIONS_DB_URL", "http://localhost:6001")


@mcp.resource("docs:://readme", mime_type="text/markdown")
def readme() -> str:
    return "Fetch transactions using requirements with the 'search_transactions' tool"

@mcp.resource("data://transactions{?start_date,end_date,category_name}")
def search_transactions(
    start_date: str = None,
    end_date: str = None,
    category_name: str = None,
) -> list[dict]:
    start_dt = parser.parse(start_date) if start_date else None
    end_dt = parser.parse(end_date) if end_date else None

    if start_dt and not end_dt:
        end_dt = datetime.now()

    if start_dt and end_dt and start_dt > end_dt:
        return []

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



if __name__ == "__main__":
    mcp.run(transport="http", port=8000)

