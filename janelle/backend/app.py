import requests
from flask import Flask, jsonify, render_template, request

from . import config


def _json_response(response):
    if response.status_code == 204:
        return "", 204
    try:
        payload = response.json()
    except (ValueError, RecursionError):
        return jsonify({
            "error": "transactions database returned invalid JSON",
            "code": "invalid_database_response",
        }), 502
    return jsonify(payload), response.status_code


def align_transactions_with_corresponding_category_names(
    transactions,
    categories,
):
    category_names = {
        category["id"]: category["name"]
        for category in categories
        if isinstance(category.get("id"), int)
        and isinstance(category.get("name"), str)
    }
    return [
        {
            **transaction,
            "category_name": category_names.get(
                transaction.get("category_id")
            ),
        }
        for transaction in transactions
    ]


def setup_app(db_url: str) -> Flask:
    application = Flask(__name__)
    db_url = db_url.rstrip("/")

    @application.errorhandler(requests.RequestException)
    def handle_database_unavailable(error):
        application.logger.warning(
            "Transactions database request failed: %s",
            error,
        )
        return jsonify({
            "error": "transactions database is unavailable",
            "code": "database_unavailable",
        }), 503

    @application.route("/")
    def get_index():
        return jsonify(container="transactions-backend")

    @application.route("/transactions")
    def get_transactions():
        response = requests.get(
            f"{db_url}/transactions",
            params=request.args,
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route("/ui/transactions")
    def get_transaction_rows():
        try:
            transaction_response = requests.get(
                f"{db_url}/transactions",
                timeout=config.DATABASE_TIMEOUT_SECONDS,
            )
            transaction_response.raise_for_status()
            transactions = transaction_response.json()

            category_response = requests.get(
                f"{db_url}/categories",
                timeout=config.DATABASE_TIMEOUT_SECONDS,
            )
            category_response.raise_for_status()
            categories = category_response.json()

            if (
                not isinstance(transactions, list)
                or not all(
                    isinstance(row, dict)
                    for row in transactions
                )
                or not isinstance(categories, list)
                or not all(
                    isinstance(row, dict)
                    for row in categories
                )
            ):
                raise ValueError("invalid database response")
        except (ValueError, RecursionError):
            return render_template(
                "transactions_table.jinja",
                transactions=[],
                error="Unable to load transactions because the database response was invalid.",
            ), 502
        except requests.RequestException:
            return render_template(
                "transactions_table.jinja",
                transactions=[],
                error="Unable to load transactions because the database service is unavailable.",
            ), 502

        return render_template(
            "transactions_table.jinja",
            transactions=align_transactions_with_corresponding_category_names(
                transactions,
                categories,
            ),
            error=None,
        )

    @application.route("/transactions", methods=["POST"])
    def create_transaction():
        response = requests.post(
            f"{db_url}/transactions",
            json=request.get_json(silent=True),
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route("/transactions/<int:transaction_id>")
    def get_transaction(transaction_id):
        response = requests.get(
            f"{db_url}/transactions/{transaction_id}",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route(
        "/transactions/<int:transaction_id>",
        methods=["PATCH"],
    )
    def update_transaction(transaction_id):
        response = requests.patch(
            f"{db_url}/transactions/{transaction_id}",
            json=request.get_json(silent=True),
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route(
        "/transactions/<int:transaction_id>",
        methods=["DELETE"],
    )
    def delete_transaction(transaction_id):
        response = requests.delete(
            f"{db_url}/transactions/{transaction_id}",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route("/categories")
    def get_categories():
        response = requests.get(
            f"{db_url}/categories",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route("/categories", methods=["POST"])
    def create_category():
        response = requests.post(
            f"{db_url}/categories",
            json=request.get_json(silent=True),
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route("/categories/<int:category_id>")
    def get_category(category_id):
        response = requests.get(
            f"{db_url}/categories/{category_id}",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route(
        "/categories/<int:category_id>",
        methods=["PATCH"],
    )
    def update_category(category_id):
        response = requests.patch(
            f"{db_url}/categories/{category_id}",
            json=request.get_json(silent=True),
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    @application.route(
        "/categories/<int:category_id>",
        methods=["DELETE"],
    )
    def delete_category(category_id):
        response = requests.delete(
            f"{db_url}/categories/{category_id}",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return _json_response(response)

    return application


app = setup_app(config.TRANSACTIONS_DB_URL)
