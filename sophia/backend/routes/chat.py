"""JSON API routes for the Ask Tally chat assistant. Writes only chat_messages; apply does the rest."""
import json
from datetime import timedelta

from flask import Blueprint, jsonify, request

from sophia.backend import config
from sophia.backend.ai import chat_prompt, guard
from sophia.backend.ai.schemas import validate_chat_response
from sophia.backend.clients import bills_db, transactions
from sophia.backend.engine import BARELY_USING_THRESHOLD, money
from sophia.backend.engine.calendar import month_breakdown
from sophia.backend.engine.projection import project

bp = Blueprint("chat", __name__, url_prefix="/api/chat")

BILL_FIELD_WHITELIST = {
    "bill": {"name", "merchant", "amount_cents", "cadence", "next_billing_date", "type", "payment_method", "end_date"},
    "payment": {"bill_id", "date", "amount_cents"},
    "dispute": {"bill_id", "reason", "status"},
}


def _recent_history():
    rows = bills_db.list_chat_messages()
    return [{"role": r["role"], "content": r["content"]} for r in rows[-10:]]


def _answer_total():
    today = config.DEMO_TODAY
    bills = [bills_db.row_to_bill(r) for r in bills_db.list_bills()]
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_payments()]
    breakdown = month_breakdown(bills, payments, today.year, today.month, today)
    return f"This month you're set to pay around {money.format_estimate_single(breakdown.total_high_cents)} in bills and subscriptions."


def _answer_barely_using():
    """A subscription counts as barely used when it has fewer than BARELY_USING_THRESHOLD
    payments since it was confirmed (or created), and few matching transactions either.
    """
    bill_rows = bills_db.list_bills()
    payment_rows = bills_db.list_payments()
    barely = []
    for row in bill_rows:
        if row["type"] != "subscription":
            continue
        since = row.get("confirmed_at") or row.get("created_at")
        count = sum(1 for p in payment_rows if p["bill_id"] == row["id"] and (since is None or p["date"] >= since))
        if count < BARELY_USING_THRESHOLD:
            transaction_rows, _source = transactions.list_transactions(merchant=row["merchant"])
            if len(transaction_rows) < BARELY_USING_THRESHOLD:
                barely.append(row["name"])
    if not barely:
        return "Everything looks actively used based on your payment and transaction history."
    return f"These subscriptions look barely used: {', '.join(barely)}."


def _answer_upcoming():
    today = config.DEMO_TODAY
    bills = [bills_db.row_to_bill(r) for r in bills_db.list_bills()]
    window_end = today + timedelta(days=7)
    names = []
    for bill in bills:
        names.extend(occ.name for occ in project(bill, today, window_end))
    if not names:
        return "Nothing is due in the next 7 days."
    return f"Coming up this week: {', '.join(names)}."


def _resolve_question(question):
    if question == "total":
        return _answer_total()
    if question == "barely_using":
        return _answer_barely_using()
    if question == "upcoming":
        return _answer_upcoming()
    return None


def _build_preview(data):
    op, entity = data.get("op"), data.get("entity")
    if not op or not entity:
        return None
    return {"op": op, "entity": entity, "id": data.get("id"), "fields": data.get("fields")}


@bp.post("")
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "")
    history = _recent_history()
    bills_db.create_chat_message({"role": "user", "content": message})

    data = guard.run(
        config.CHAT_MODEL,
        lambda error: chat_prompt.build(message, history, error=error),
        validate_chat_response,
        chat_prompt.FALLBACK,
    )

    reply = _resolve_question(data.get("question")) or data.get("say", "")
    preview = _build_preview(data)

    bills_db.create_chat_message(
        {"role": "assistant", "content": reply, "op_json": json.dumps(preview) if preview else None}
    )
    return jsonify({"reply": reply, "op": preview["op"] if preview else None, "preview": preview, "fallback": data.get("fallback", False)})


@bp.post("/apply")
def apply():
    payload = request.get_json(silent=True) or {}
    op = payload.get("op")
    entity = payload.get("entity")
    entity_id = payload.get("id")
    fields = payload.get("fields") or {}
    if entity not in BILL_FIELD_WHITELIST:
        return jsonify({"error": "unknown entity"}), 400
    clean_fields = {k: v for k, v in fields.items() if k in BILL_FIELD_WHITELIST[entity]}

    if entity == "bill" and op == "update":
        if bills_db.get_bill(entity_id) is None:
            return jsonify({"error": "bill not found"}), 404
        result = bills_db.update_bill(entity_id, clean_fields)
    elif entity == "bill" and op == "create":
        result = bills_db.create_bill({**clean_fields, "source": "chat"})
    elif entity == "bill" and op == "delete":
        result = bills_db.delete_bill(entity_id)
    elif entity == "payment" and op == "create":
        result = bills_db.create_payment(clean_fields)
    elif entity == "payment" and op == "delete":
        result = bills_db.delete_payment(entity_id)
    elif entity == "dispute" and op == "update":
        result = bills_db.update_dispute(entity_id, clean_fields)
    else:
        return jsonify({"error": f"unsupported op '{op}' for entity '{entity}'"}), 400

    bills_db.create_chat_message({"role": "assistant", "content": "Done — change saved.", "applied": True})
    return jsonify(result)


@bp.get("/history")
def history():
    return jsonify(bills_db.list_chat_messages())
