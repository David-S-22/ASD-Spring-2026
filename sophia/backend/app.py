"""Flask application factory for the bills backend (:5005)."""
import os

import requests
from flask import Flask, jsonify
from flask_cors import CORS

from sophia.backend import config
from sophia.backend.clients import bills_db, transactions
from sophia.backend.routes import bills, chat, disputes, fragments, handoff, payments, views
from sophia.backend.services.errors import ServiceError

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


def _ollama_status():
    try:
        response = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
        return "up" if response.ok else "down"
    except requests.RequestException:
        return "down"


def create_app():
    app = Flask(__name__, template_folder=TEMPLATE_DIR)
    CORS(app)
    app.register_blueprint(bills.bp)
    app.register_blueprint(payments.bp)
    app.register_blueprint(disputes.bp)
    app.register_blueprint(views.bp)
    app.register_blueprint(chat.bp)
    app.register_blueprint(handoff.bp)
    app.register_blueprint(fragments.bp)

    @app.errorhandler(ServiceError)
    def handle_service_error(error):
        return jsonify({"error": error.message}), error.status

    @app.get("/health")
    def health():
        try:
            bills_db.health()
            db_api = "up"
        except requests.RequestException:
            db_api = "down"
        _rows, transactions_source = transactions.list_transactions()
        return jsonify(
            {
                "ok": db_api == "up",
                "today": config.DEMO_TODAY.isoformat(),
                "db_api": db_api,
                "transactions_api": transactions_source,
                "ollama": _ollama_status(),
            }
        )

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=config.PORT)
