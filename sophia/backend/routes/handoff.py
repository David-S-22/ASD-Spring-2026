"""JSON API routes for inbound automation handoffs from other students' features.

Deep-link shape: the parameter travels in the QUERY and the hash is a bare
"#bills". The shared shell routes tabs on an exact hash match
(`tabs.find(t => t.dataset.page === location.hash.slice(1)) || tabs[0]`), so the
old "#bills?confirm=7" sliced to "bills?confirm=7", matched nothing and landed
on Home -- the link silently did nothing. There is no "chat" page in the shell
either, so "#chat?handoff=x" could never work there; Bills owns Ask Tally, and
app.js routes on the query parameter once Bills is loaded.
"""
from urllib.parse import quote

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
            "ui_url": f"{config.FRONTEND_ORIGIN}/?handoff={quote(handoff_id)}#bills",
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
                "confirm_url": f"{config.FRONTEND_ORIGIN}/?confirm={bill['id']}#bills",
            }
        ),
        201,
    )
