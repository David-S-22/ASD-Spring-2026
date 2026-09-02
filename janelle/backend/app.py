import json

import requests
from flask import Flask, jsonify, make_response, render_template, request

from . import config
from .Helpers import (
    align_transactions_with_corresponding_category_names,
    format_currency,
    format_transaction_date,
    json_object,
    json_response,
    render_transaction_form,
    render_transaction_table,
)
from .services.chat_service import ChatError, apply_preview, handle_message


def setup_app(db_url: str) -> Flask:
    application = Flask(__name__)
    db_url = db_url.rstrip("/")
    application.jinja_env.filters["transaction_date"] = (
        format_transaction_date
    )
    application.jinja_env.filters["currency"] = format_currency

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

    @application.errorhandler(ChatError)
    def handle_chat_error(error):
        return jsonify(error.to_dict()), error.status

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
        return json_response(response)

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
            return render_transaction_table(
                [],
                "Unable to load transactions because the database response was invalid.",
            ), 502
        except requests.RequestException:
            return render_transaction_table(
                [],
                "Unable to load transactions because the database service is unavailable.",
            ), 502

        return render_transaction_table(
            align_transactions_with_corresponding_category_names(
                transactions,
                categories,
            ),
        )

    @application.get("/ui/transactions/page")
    def get_transactions_page():
        return render_template(
            "transactions_page.jinja",
            notice=None,
        )

    @application.get("/ui/transactions/new")
    def get_new_transaction_form():
        return render_transaction_form(db_url)

    @application.post("/ui/transactions")
    def create_ui_transaction():
        values = request.form.to_dict()
        try:
            payload = {
                "date": values.get("date"),
                "amount": float(values.get("amount", "")),
                "merchant": values.get("merchant"),
                "description": values.get("description"),
                "category_id": int(values.get("category_id", "")),
            }
        except (TypeError, ValueError):
            return render_transaction_form(
                db_url,
                "Enter a valid amount and category.",
                values,
            )

        try:
            response = requests.post(
                f"{db_url}/transactions",
                json=payload,
                timeout=config.DATABASE_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            return render_transaction_form(
                db_url,
                "The transaction could not be saved because the database is unavailable.",
                values,
            )

        if response.status_code >= 400:
            try:
                error_payload = response.json()
            except (ValueError, RecursionError):
                error_payload = {}
            error = (
                error_payload.get("error")
                if isinstance(error_payload, dict)
                else None
            )
            return render_transaction_form(
                db_url,
                error or "The transaction could not be saved.",
                values,
            )

        return render_template(
            "transactions_page.jinja",
            notice="Transaction saved.",
        )

    @application.route("/transactions", methods=["POST"])
    def create_transaction():
        response = requests.post(
            f"{db_url}/transactions",
            json=request.get_json(silent=True),
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return json_response(response)

    @application.route("/transactions/<int:transaction_id>")
    def get_transaction(transaction_id):
        response = requests.get(
            f"{db_url}/transactions/{transaction_id}",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return json_response(response)

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
        return json_response(response)

    @application.route(
        "/transactions/<int:transaction_id>",
        methods=["DELETE"],
    )
    def delete_transaction(transaction_id):
        response = requests.delete(
            f"{db_url}/transactions/{transaction_id}",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return json_response(response)

    @application.route("/categories")
    def get_categories():
        response = requests.get(
            f"{db_url}/categories",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return json_response(response)

    @application.route("/categories", methods=["POST"])
    def create_category():
        response = requests.post(
            f"{db_url}/categories",
            json=request.get_json(silent=True),
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return json_response(response)

    @application.route("/categories/<int:category_id>")
    def get_category(category_id):
        response = requests.get(
            f"{db_url}/categories/{category_id}",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return json_response(response)

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
        return json_response(response)

    @application.route(
        "/categories/<int:category_id>",
        methods=["DELETE"],
    )
    def delete_category(category_id):
        response = requests.delete(
            f"{db_url}/categories/{category_id}",
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )
        return json_response(response)

    @application.post("/chat")
    def chat():
        payload = json_object()
        unknown = sorted(set(payload) - {"message"})
        if unknown:
            raise ChatError(
                f"unsupported fields: {', '.join(unknown)}",
                "unsupported_fields",
                422,
            )
        return jsonify(handle_message(payload.get("message"), db_url))

    @application.post("/chat/apply")
    def apply_chat_preview():
        return jsonify(apply_preview(json_object(), db_url))

    @application.get("/ui/chat")
    def get_chat_panel():
        return render_template("chat_panel.jinja")

    @application.post("/ui/chat")
    def post_ui_chat():
        try:
            result = handle_message(request.form.get("message"), db_url)
            return render_template(
                "chat_result.jinja",
                result=result,
                error=None,
                success=None,
            )
        except ChatError as error:
            return render_template(
                "chat_result.jinja",
                result=None,
                error=error.message,
                success=None,
            ), error.status
        except requests.RequestException as error:
            application.logger.warning(
                "Transactions database request failed: %s",
                error,
            )
            return render_template(
                "chat_result.jinja",
                result=None,
                error="The transactions service is unavailable.",
                success=None,
            ), 503

    @application.post("/ui/chat/apply")
    def apply_ui_chat_preview():
        try:
            preview = json.loads(request.form.get("preview", ""))
            result = apply_preview(preview, db_url)
        except (json.JSONDecodeError, TypeError):
            error = ChatError(
                "The confirmation preview is invalid.",
                "invalid_preview",
                400,
            )
            return render_template(
                "chat_result.jinja",
                result=None,
                error=error.message,
                success=None,
            ), error.status
        except ChatError as error:
            return render_template(
                "chat_result.jinja",
                result=None,
                error=error.message,
                success=None,
            ), error.status
        except requests.RequestException as error:
            application.logger.warning(
                "Transactions database request failed: %s",
                error,
            )
            return render_template(
                "chat_result.jinja",
                result=None,
                error="The transaction change could not be saved.",
                success=None,
            ), 503

        operation = result["operation"]
        response = make_response(render_template(
            "chat_result.jinja",
            result=None,
            error=None,
            success=(
                f"The confirmed {operation} operation was saved."
            ),
        ))
        response.headers["HX-Trigger"] = "transactionsChanged"
        return response

    @application.get("/ui/chat/clear")
    def clear_ui_chat():
        return ""

    return application
app = setup_app(config.TRANSACTIONS_DB_URL)
