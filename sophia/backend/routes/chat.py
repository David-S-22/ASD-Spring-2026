"""JSON API routes for the Ask Tally chat assistant. Writes only chat_messages; apply does the rest."""
from flask import Blueprint, jsonify, request

from sophia.backend.clients import bills_db
from sophia.backend.json_body import json_body
from sophia.backend.services import chat as chat_service

bp = Blueprint("chat", __name__, url_prefix="/api/chat")


@bp.post("")
def chat():
    payload = json_body()
    return jsonify(chat_service.send_message(payload.get("message", "")))


@bp.post("/apply")
def apply():
    payload = json_body()
    result = chat_service.apply(
        payload.get("op"),
        payload.get("entity"),
        payload.get("id"),
        payload.get("fields"),
        message_id=payload.get("message_id"),
    )
    return jsonify(result)


@bp.get("/history")
def history():
    return jsonify(bills_db.list_chat_messages())


@bp.get("/suggestions")
def list_suggestions():
    return jsonify(bills_db.list_suggestions(request.args.get("status")))


@bp.post("/suggestions/<int:suggestion_id>/approve")
def approve_suggestion(suggestion_id):
    return jsonify(chat_service.approve_suggestion(suggestion_id))


@bp.post("/suggestions/<int:suggestion_id>/reject")
def reject_suggestion(suggestion_id):
    return jsonify(chat_service.reject_suggestion(suggestion_id))
