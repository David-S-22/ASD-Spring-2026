import requests
from flask import Flask, jsonify, render_template

from . import config


app = Flask(__name__)


@app.get("/")
def get_index():
    return jsonify(container="transactions-backend")


@app.get("/ui/transactions")
def get_transaction_rows():
    try:
        response = requests.get(
            f"{config.TRANSACTIONS_DB_URL}/transactions",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException:
        return render_template(
            "transactions_table.jinja",
            transactions=[],
            error="Unable to load transactions because the database service is unavailable.",
        ), 502

    try:
        transactions = response.json()
    except requests.exceptions.JSONDecodeError:
        return render_template(
            "transactions_table.jinja",
            transactions=[],
            error="Unable to load transactions because the database response was invalid.",
        ), 502

    if not isinstance(transactions, list) or not all(
        isinstance(transaction, dict) for transaction in transactions
    ):
        return render_template(
            "transactions_table.jinja",
            transactions=[],
            error="Unable to load transactions because the database response was invalid.",
        ), 502

    return render_template("transactions_table.jinja", transactions=transactions, error=None)
