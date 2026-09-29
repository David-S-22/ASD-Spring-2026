"""JSON API and HTMX fragment routes for grounded answers about the user's bills."""
from flask import Blueprint, jsonify, render_template, request

from sophia.backend import config
from sophia.backend.json_body import json_body
from sophia.backend.services import evidence as evidence_service
from sophia.backend.services.errors import ServiceError

bp = Blueprint("evidence", __name__, url_prefix="/api/evidence")


@bp.post("")
def ask():
    """Answer a question from the bills corpus: {"question"} in, the evidence dict out."""
    payload = json_body()
    if not isinstance(payload, dict):
        raise ServiceError("expected a JSON object with a question")
    return jsonify(evidence_service.ask(payload.get("question", "")))


ui = Blueprint("evidence_ui", __name__, url_prefix="/ui/evidence")


@ui.errorhandler(ServiceError)
def handle_ui_error(error):
    status = error.status if error.status >= 500 else 422
    return render_template("error_fragment.html", message=error.message), status


@ui.errorhandler(Exception)
def handle_unexpected_ui_error(error):
    if isinstance(error, ServiceError):
        raise error
    return render_template("error_fragment.html", message="Something went wrong — try again."), 500


@ui.get("")
def evidence_panel():
    return render_template("evidence_panel.html", enabled=config.MCP_ENABLED and config.RAG_ENABLED)


@ui.post("")
def evidence_ask():
    result = evidence_service.ask(request.form.get("question", ""))
    return render_template("evidence_answer.html", result=result)
