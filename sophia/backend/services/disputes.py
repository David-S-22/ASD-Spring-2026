"""Dispute CRUD and AI-drafted letters, shared by /api/disputes and /ui/disputes."""
from sophia.backend import config
from sophia.backend.ai import dispute_prompt, guard
from sophia.backend.ai.schemas import validate_dispute_draft
from sophia.backend.clients import bills_db
from sophia.backend.services.errors import NotFound, ServiceError

DISPUTE_STATUSES = ("draft", "sent", "resolved")


def draft_for_bill(bill_row, reason, previous_letter=None, edited_letter=None, feedback=None):
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


def list_disputes():
    return bills_db.list_disputes()


def create_dispute(bill_id, reason):
    if not bill_id:
        raise ServiceError("bill_id is required")
    if not reason:
        raise ServiceError("reason is required")
    bill_row = bills_db.get_bill(bill_id)
    if bill_row is None:
        raise NotFound("bill not found")
    dispute = bills_db.create_dispute({"bill_id": bill_id, "reason": reason})
    draft = draft_for_bill(bill_row, reason)
    bills_db.create_dispute_draft(
        dispute["id"],
        {"letter_text": draft["letter_text"], "steps_json": {"steps": draft["steps"], "escalation": draft["escalation"]}},
    )
    dispute["draft"] = draft
    return dispute


def get_dispute(dispute_id):
    dispute = bills_db.get_dispute(dispute_id)
    if dispute is None:
        raise NotFound("dispute not found")
    return dispute


def update_dispute(dispute_id, payload):
    if bills_db.get_dispute(dispute_id) is None:
        raise NotFound("dispute not found")
    if "status" in payload and payload["status"] not in DISPUTE_STATUSES:
        raise ServiceError(f"status must be one of {', '.join(DISPUTE_STATUSES)}")
    return bills_db.update_dispute(dispute_id, payload)


def update_status(dispute_id, status):
    return update_dispute(dispute_id, {"status": status})


def delete_dispute(dispute_id):
    return bills_db.delete_dispute(dispute_id)


def list_drafts(dispute_id):
    return bills_db.list_dispute_drafts(dispute_id)


def regenerate(dispute_id, edited_letter=None, feedback=None):
    dispute = bills_db.get_dispute(dispute_id)
    if dispute is None:
        raise NotFound("dispute not found")
    bill_row = bills_db.get_bill(dispute["bill_id"])
    bill = bills_db.row_to_bill(bill_row)
    if edited_letter and not feedback:
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
        draft = draft_for_bill(
            bill_row, dispute["reason"], previous_letter=previous_letter, edited_letter=edited_letter, feedback=feedback
        )
    created = bills_db.create_dispute_draft(
        dispute_id,
        {"letter_text": draft["letter_text"], "steps_json": {"steps": draft["steps"], "escalation": draft["escalation"]}},
    )
    created["draft"] = draft
    return created
