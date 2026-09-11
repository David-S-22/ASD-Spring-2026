import asyncio
import json
import os
import sys
import threading
from pathlib import Path

import requests
from fastmcp import Client

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MCP_DIR = Path(__file__).resolve().parents[1]
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import server
from server import TRANSACTIONS_DB_URL, mcp


def ensure_database_service():
    """Ensure the transactions-db HTTP service is reachable."""
    try:
        resp = requests.get(f"{TRANSACTIONS_DB_URL.rstrip('/')}/health", timeout=1.0)
        if resp.status_code == 200:
            return None
    except Exception:
        pass

    from janelle.database.app import setup_app
    from werkzeug.serving import make_server

    db_path = os.getenv("DB_PATH", str(REPO_ROOT / "transactions.db"))
    app = setup_app(db_path)
    http_server = make_server("127.0.0.1", 6001, app)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    return http_server


async def main():
    db_server = ensure_database_service()

    try:
        async with Client(mcp) as client:
            print("=== FastMCP Transactions Client ===\n")

            # 1. No start date, end date, or category (all transactions)
            print("[Scenario 1] No start date, end date, or category:")
            res = await client.read_resource("data://transactions")
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) > 0

            # 2. No transactions (date range in future with no matches)
            print("\n[Scenario 2] No matching transactions:")
            res = await client.read_resource("data://transactions?start_date=2099-01-01")
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) == 0

            # 3a. Only start date (goes up to current date)
            print("\n[Scenario 3a] Only start date (start_date=2026-07-01):")
            res = await client.read_resource("data://transactions?start_date=2026-07-01")
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) > 0

            # 3b. Only end date (earliest transaction to end date)
            print("\n[Scenario 3b] Only end date (end_date=2026-06-20):")
            res = await client.read_resource("data://transactions?end_date=2026-06-20")
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) > 0

            # 3c. Only category (category_name=Fitness)
            print("\n[Scenario 3c] Only category (category_name=Fitness):")
            res = await client.read_resource("data://transactions?category_name=Fitness")
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) > 0

            # 4. Start date + end date
            print("\n[Scenario 4] Start date + end date (2026-06-10 to 2026-06-24):")
            res = await client.read_resource(
                "data://transactions?start_date=2026-06-10&end_date=2026-06-24"
            )
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) > 0

            # 5. Start date + category
            print("\n[Scenario 5] Start date + category (start_date=2026-07-01, category_name=Fitness):")
            res = await client.read_resource(
                "data://transactions?start_date=2026-07-01&category_name=Fitness"
            )
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) > 0

            # 6. End date + category
            print("\n[Scenario 6] End date + category (end_date=2026-06-24, category_name=Fitness):")
            res = await client.read_resource(
                "data://transactions?end_date=2026-06-24&category_name=Fitness"
            )
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) > 0

            # 7. Start date + end date + category
            print(
                "\n[Scenario 7] Start date + end date + category "
                "(2026-06-10 to 2026-06-24, category_name=Housing):"
            )
            res = await client.read_resource(
                "data://transactions?start_date=2026-06-10&end_date=2026-06-24&category_name=Housing"
            )
            transactions = json.loads(res[0].text)
            print(f"  Result: {len(transactions)} transactions found.")
            assert len(transactions) > 0

            print("\nAll scenarios tested successfully.")
    finally:
        if db_server is not None:
            db_server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
