"""JSON API routes for disputes and their AI-drafted letters."""
from flask import Blueprint, jsonify, request

from sophia.backend import config
from sophia.backend.ai import dispute_prompt, guard
from sophia.backend.ai.schemas import validate_dispute_draft
from sophia.backend.clients import bills_db

bp = Blueprint("disputes", __name__, url_prefix="/api")


def _draft_for_bill(bill_row, reason, previous_letter=None, edited_letter=None, feedback=None):
    bill = bills_db.row_to_bill(bill_row)
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_bill_payments(bill.id)]
    fallback = dispute_prompt.fallback_draft(bill, reason)
    data = guard.run(
        config.DRAFT_MODEL,
        lambda error: dispute_prompt.build(
            bill,
            reason,
            payments=payments,
            previous_letter=previous_letter,
            edited_letter=edited_letter,
            feedback=feedback,
            error=error,
        ),
        validate_dispute_draft,
        fallback,
    )
    return dispute_prompt.enforce_payment_method_step(data, bill)


@bp.get("/disputes")
def list_disputes():
    return jsonify(bills_db.list_disputes())


@bp.post("/disputes")
def create_dispute():
    payload = request.get_json(silent=True) or {}
    bill_row = bills_db.get_bill(payload.get("bill_id"))
    if bill_row is None:
        return jsonify({"error": "bill not found"}), 404
    dispute = bills_db.create_dispute({"bill_id": payload["bill_id"], "reason": payload["reason"]})
    draft = _draft_for_bill(bill_row, payload["reason"])
    bills_db.create_dispute_draft(
        dispute["id"],
        {"letter_text": draft["letter_text"], "steps_json": {"steps": draft["steps"], "escalation": draft["escalation"]}},
    )
    dispute["draft"] = draft
    return jsonify(dispute), 201


@bp.get("/disputes/<int:dispute_id>")
def get_dispute(dispute_id):
    dispute = bills_db.get_dispute(dispute_id)
    if dispute is None:
        return jsonify({"error": "dispute not found"}), 404
    return jsonify(dispute)


@bp.put("/disputes/<int:dispute_id>")
def update_dispute(dispute_id):
    payload = request.get_json(silent=True) or {}
    return jsonify(bills_db.update_dispute(dispute_id, payload))


@bp.delete("/disputes/<int:dispute_id>")
def delete_dispute(dispute_id):
    return jsonify(bills_db.delete_dispute(dispute_id))


@bp.get("/disputes/<int:dispute_id>/drafts")
def list_drafts(dispute_id):
    return jsonify(bills_db.list_dispute_drafts(dispute_id))


@bp.post("/disputes/<int:dispute_id>/regenerate")
def regenerate(dispute_id):
    payload = request.get_json(silent=True) or {}
    dispute = bills_db.get_dispute(dispute_id)
    if dispute is None:
        return jsonify({"error": "dispute not found"}), 404
    bill_row = bills_db.get_bill(dispute["bill_id"])
    bill = bills_db.row_to_bill(bill_row)
    edited_letter = payload.get("edited_letter")
    if edited_letter and not payload.get("feedback"):
        draft = dispute_prompt.enforce_payment_method_step(
            {
                "letter_text": edited_letter,
                "steps": [],
                "escalation": list(dispute_prompt.ESCALATION_DEFAULT),
                "fallback": False,
            },
            bill,
        )
    else:
        existing_drafts = bills_db.list_dispute_drafts(dispute_id)
        previous_letter = existing_drafts[-1]["letter_text"] if existing_drafts else None
        draft = _draft_for_bill(
            bill_row,
            dispute["reason"],
            previous_letter=previous_letter,
            edited_letter=edited_letter,
            feedback=payload.get("feedback"),
        )
    created = bills_db.create_dispute_draft(
        dispute_id,
        {"letter_text": draft["letter_text"], "steps_json": {"steps": draft["steps"], "escalation": draft["escalation"]}},
    )
    created["draft"] = draft
    return jsonify(created), 201
