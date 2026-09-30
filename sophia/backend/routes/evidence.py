"""JSON API and HTMX fragment routes for grounded answers about the user's bills."""
from flask import Blueprint, jsonify, render_template, request

from sophia.backend import config
from sophia.backend.fragment_errors import register_fragment_error_handlers
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
register_fragment_error_handlers(ui)


@ui.get("")
def evidence_panel():
    return render_template("evidence_panel.html", enabled=config.MCP_ENABLED and config.RAG_ENABLED)


@ui.post("")
def evidence_ask():
    result = evidence_service.ask(request.form.get("question", ""))
    return render_template("evidence_answer.html", result=result)
