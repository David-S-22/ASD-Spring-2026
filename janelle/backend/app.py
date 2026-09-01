import requests
from flask import Flask, jsonify, render_template

from .services import transactions_api


app = Flask(__name__)


@app.get("/")
def get_index():
    return jsonify(container="transactions-backend")


@app.get("/ui/transactions")
def get_transaction_rows():
    try:
        transactions = transactions_api.get_all_transactions()
        categories = transactions_api.get_all_categories()
    except requests.RequestException:
        return render_template(
            "transactions_table.jinja",
            transactions=[],
            error="Unable to load transactions because the database service is unavailable.",
        ), 502

    except transactions_api.InvalidDatabaseResponse:
        return render_template(
            "transactions_table.jinja",
            transactions=[],
            error="Unable to load transactions because the database response was invalid.",
        ), 502

    return render_template(
        "transactions_table.jinja",
        transactions=align_transactions_with_corresponding_category_names(
            transactions,
            categories,
        ),
        error=None,
    )

def align_transactions_with_corresponding_category_names(transactions, categories):
    category_names = {
        category["id"]: category["name"]
        for category in categories
        if isinstance(category.get("id"), str)
        and isinstance(category.get("name"), str)
    }
    return [
        {
            **transaction,
            "category_name": category_names.get(transaction.get("category_id")),
        }
        for transaction in transactions
    ]
