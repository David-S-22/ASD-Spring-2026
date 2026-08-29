"""JSON API routes for inbound automation handoffs from other students' features."""
from flask import Blueprint, jsonify, request

from sophia.backend import config
from sophia.backend.clients import bills_db

bp = Blueprint("handoff", __name__, url_prefix="/api")


def _op_for_intent(intent, bill_id, merchant, payload):
    if intent == "end":
        effective_from = payload.get("effective_from") or config.DEMO_TODAY.isoformat()
        return {"op": "update", "entity": "bill", "id": bill_id, "fields": {"end_date": effective_from}}
    if intent == "change_amount":
        return {"op": "update", "entity": "bill", "id": bill_id, "fields": {"amount_cents": payload.get("amount")}}
    return {
        "op": "create",
        "entity": "bill",
        "id": None,
        "fields": {"merchant": merchant, "name": merchant, "amount_cents": payload.get("amount")},
    }


@bp.post("/handoff/recurring")
def handoff_recurring():
    payload = request.get_json(silent=True) or {}
    merchant = payload.get("merchant")
    intent = payload.get("intent")
    match = next((b for b in bills_db.list_bills() if b["merchant"] == merchant), None)
    op = _op_for_intent(intent, match["id"] if match else None, merchant, payload)
    preview = {"say": f"{intent} for {merchant}", "op": op, "note": payload.get("note")}
    handoff_id = f"{intent}-{merchant}".lower().replace(" ", "-")
    return jsonify(
        {
            "preview": preview,
            "apply_url": "/api/chat/apply",
            "ui_url": f"{config.FRONTEND_ORIGIN}/#chat?handoff={handoff_id}",
        }
    )


@bp.post("/suggestions")
def suggestions():
    payload = request.get_json(silent=True) or {}
    bill = bills_db.create_bill(
        {
            "name": payload.get("merchant"),
            "merchant": payload.get("merchant"),
            "amount_cents": payload.get("amount"),
            "cadence": payload.get("cadence"),
            "next_billing_date": payload.get("last_seen"),
            "type": "subscription",
            "source": "f4_handoff",
            "confirmed_at": None,
        }
    )
    return (
        jsonify(
            {
                "bill_id": bill["id"],
                "status": bill["status"],
                "confirm_url": f"{config.FRONTEND_ORIGIN}/#bills?confirm={bill['id']}",
            }
        ),
        201,
    )
