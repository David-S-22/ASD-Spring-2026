import json

import requests
from flask import Flask, jsonify, make_response, render_template, request

from . import config
from .Helpers import (
    align_transactions_with_corresponding_category_names,
    database_response_error,
    format_currency,
    format_transaction_date,
    json_object,
    json_response,
    render_category_form,
    render_transaction_form,
    render_transaction_page,
    render_transaction_table,
)
from .services.chat_service import ChatError
from .services.transaction_orchestrator import (
    get_preview_request_context,
    orchestrate_transaction_request,
    run_category_selection,
    run_confirmed_transaction,
)


def setup_app(db_url: str) -> Flask:
    application = Flask(__name__)
    db_url = db_url.rstrip("/")
    anomalies_backend_url = config.ANOMALIES_BACKEND_URL.rstrip("/")

    def check_transaction_for_anomalies(transaction):
        """Ask the anomalies backend to review a newly created transaction.

        Runs server-side so the check cannot be bypassed by the client. The
        anomalies backend queues the transaction and returns immediately, so
        this call is quick. Failures are logged and swallowed so they never
        affect transaction creation.
        """
        try:
            response = requests.post(
                f"{anomalies_backend_url}/check-transaction",
                json=transaction,
                timeout=config.ANOMALIES_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            application.logger.warning(
                "Anomaly check request failed: %s",
                error,
            )
            return

        if response.status_code == 204 or response.ok:
            return

        application.logger.warning(
            "Anomaly check returned %s: %s",
            response.status_code,
            response.text,
        )

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
        return render_transaction_page(db_url)

    @application.get("/ui/transactions/new")
    def get_new_transaction_form():
        return render_transaction_form(db_url)

    @application.get("/ui/categories/new")
    def get_new_category_form():
        return render_category_form()

    @application.post("/ui/categories")
    def create_ui_category():
        values = request.form.to_dict()
        payload = {
            "name": values.get("name"),
            "type": values.get("type") or None,
        }
        try:
            response = requests.post(
                f"{db_url}/categories",
                json=payload,
                timeout=config.DATABASE_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            return render_category_form(
                "The category could not be saved because the database is unavailable.",
                values,
            )

        if response.status_code >= 400:
            return render_category_form(
                database_response_error(
                    response,
                    "The category could not be saved.",
                ),
                values,
            )

        return render_transaction_page(
            db_url,
            notice="Category saved.",
        )

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
            return render_transaction_form(
                db_url,
                database_response_error(
                    response,
                    "The transaction could not be saved.",
                ),
                values,
            )

        return render_transaction_page(
            db_url,
            notice="Transaction saved.",
        )

    @application.route("/transactions", methods=["POST"])
    def create_transaction():
        payload = json_object()
        if "suggested_category_id" in payload:
            raise ChatError(
                "suggested_category_id is only accepted from a confirmed "
                "agent category override",
                "unsupported_fields",
                422,
            )
        response = requests.post(
            f"{db_url}/transactions",
            json=payload,
            timeout=config.DATABASE_TIMEOUT_SECONDS,
        )

        if response.status_code == 201:
            try:
                created = response.json()
            except (ValueError, RecursionError):
                created = None
            if isinstance(created, dict):
                check_transaction_for_anomalies(created)

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
        return jsonify(orchestrate_transaction_request(
            payload.get("message"),
            db_url,
        ))

    @application.post("/chat/category")
    def select_chat_category():
        return jsonify(run_category_selection(json_object(), db_url))

    @application.post("/chat/apply")
    def apply_chat_preview():
        return jsonify(run_confirmed_transaction(json_object(), db_url))

    @application.get("/ui/chat")
    def get_chat_panel():
        return render_template("chat_panel.jinja")

    @application.post("/ui/chat")
    def post_ui_chat():
        try:
            if "clarification" in request.form:
                original_message = request.form.get("original_message", "").strip()
                clarification = request.form.get("clarification", "").strip()
                if not original_message:
                    raise ChatError(
                        "The original request is missing. Start a new request.",
                        "invalid_message",
                        422,
                    )
                if not clarification:
                    raise ChatError(
                        "Enter an answer before continuing.",
                        "invalid_message",
                        422,
                    )
                separator = (
                    ""
                    if original_message[-1] in ".!?"
                    else "."
                )
                message = (
                    f"{original_message}{separator}\n"
                    f"Additional details: {clarification}"
                )
            elif "adjustment" in request.form:
                adjustment = request.form.get("adjustment", "").strip()
                if not adjustment:
                    raise ChatError(
                        "Enter what you want to change before continuing.",
                        "invalid_message",
                        422,
                    )
                original_message = get_preview_request_context(
                    request.form.get("request_id")
                )
                message = (
                    f"{original_message}\n"
                    f"Requested change: {adjustment}"
                )
            else:
                message = request.form.get("message")
            result = orchestrate_transaction_request(
                message,
                db_url,
            )
            response = make_response(render_template(
                "chat_result.jinja",
                result=result,
                error=None,
                success=None,
                request_context=message,
            ))
            if result.get("agent", {}).get("status") == "complete":
                response.headers["HX-Trigger"] = "transaction-completed"
            return response
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

    @application.post("/ui/chat/category")
    def select_ui_chat_category():
        try:
            result = run_category_selection(
                {
                    "request_id": request.form.get("request_id"),
                    "category_id": int(
                        request.form.get("category_id", "")
                    ),
                },
                db_url,
            )
            return render_template(
                "chat_result.jinja",
                result=result,
                error=None,
                success=None,
                request_context=request.form.get("request_context"),
            )
        except (TypeError, ValueError):
            error = ChatError(
                "Choose a valid category.",
                "invalid_category",
                422,
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

    @application.post("/ui/chat/apply")
    def apply_ui_chat_preview():
        try:
            preview = json.loads(request.form.get("preview", ""))
            payload = {"preview": preview}
            request_id = request.form.get("request_id")
            if request_id:
                payload["request_id"] = request_id
            result = run_confirmed_transaction(payload, db_url)
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

        response = make_response(render_template(
            "chat_result.jinja",
            result=result,
            error=None,
            success=result["reply"],
        ))
        triggers = ["transactionsChanged"]
        if (
            result.get("saved") is True
            and result.get("verified") is True
            and result.get("agent", {}).get("status") == "complete"
        ):
            triggers.append("transaction-completed")
        response.headers["HX-Trigger"] = ", ".join(triggers)
        return response

    @application.get("/ui/chat/clear")
    def clear_ui_chat():
        return ""

    return application
app = setup_app(config.TRANSACTIONS_DB_URL)
