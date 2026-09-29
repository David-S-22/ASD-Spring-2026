"""JSON API route for grounded answers about the user's bills."""
from flask import Blueprint, jsonify

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
