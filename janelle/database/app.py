import os
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, jsonify


app = Flask(__name__)
app.config["DB_PATH"] = os.environ.get("DB_PATH", "./transactions.db")

DEMO_TRANSACTIONS = (
    (1, "2026-08-20", "Spotify AU", "Monthly subscription", 1799, "Subscriptions"),
    (2, "2026-08-22", "Woolworths", "Weekly groceries", 8645, "Groceries"),
    (3, "2026-08-25", "Sydney Trains", "Opal card top-up", 4000, "Transport"),
)


def _connect_database():
    connection = sqlite3.connect(app.config["DB_PATH"])
    connection.row_factory = sqlite3.Row
    return connection


@app.get("/")
def get_index():
    return jsonify(container="transactions-db")


@app.get("/transactions")
def get_transactions():
    try:
        with closing(_connect_database()) as connection:
            rows = connection.execute(
                """
                SELECT id, date, merchant, description, amount_cents, category_name
                FROM transactions
                ORDER BY date DESC, id DESC
                """
            ).fetchall()
    except (OSError, sqlite3.Error):
        return jsonify(error="database unavailable"), 503

    return jsonify([
        {
            "id": row["id"],
            "date": row["date"],
            "merchant": row["merchant"],
            "description": row["description"],
            "amount": row["amount_cents"] / 100,
            "amount_cents": row["amount_cents"],
            "category_name": row["category_name"],
        }
        for row in rows
    ])


def setup(db_path: str):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    app.config["DB_PATH"] = str(path)
    with closing(_connect_database()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                merchant TEXT NOT NULL,
                description TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                category_name TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO transactions (
                id,
                date,
                merchant,
                description,
                amount_cents,
                category_name
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            DEMO_TRANSACTIONS,
        )
        connection.commit()
