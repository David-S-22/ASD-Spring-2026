"""Payment CRUD, shared by /api/payments and /ui/payments. Recomputes the owning bill's status."""
from datetime import date

from sophia.backend.clients import bills_db
from sophia.backend.services.bills import _persist_status_if_drifted
from sophia.backend.services.errors import NotFound, ServiceError


def _refresh_bill_status(bill_id):
    bill_row = bills_db.get_bill(bill_id)
    if bill_row is None:
        return
    _persist_status_if_drifted(bill_row)


def _clean_payload(payload, require_bill_id):
    cleaned = dict(payload)
    if require_bill_id or "bill_id" in cleaned:
        if not cleaned.get("bill_id"):
            raise ServiceError("bill_id is required")
        try:
            cleaned["bill_id"] = int(cleaned["bill_id"])
        except (TypeError, ValueError):
            raise ServiceError("bill_id must be an integer")
    if require_bill_id or "date" in cleaned:
        if not cleaned.get("date"):
            raise ServiceError("date is required")
        try:
            date.fromisoformat(cleaned["date"])
        except ValueError:
            raise ServiceError("date must be YYYY-MM-DD")
    if require_bill_id or "amount_cents" in cleaned:
        if cleaned.get("amount_cents") in (None, ""):
            raise ServiceError("amount_cents is required")
        try:
            cleaned["amount_cents"] = int(cleaned["amount_cents"])
        except (TypeError, ValueError):
            raise ServiceError("amount_cents must be a whole number of cents")
    return cleaned


def create_payment(payload):
    cleaned = _clean_payload(payload, require_bill_id=True)
    if bills_db.get_bill(cleaned["bill_id"]) is None:
        raise NotFound("bill not found")
    created = bills_db.create_payment(cleaned)
    _refresh_bill_status(created["bill_id"])
    return created


def update_payment(payment_id, payload):
    cleaned = _clean_payload(payload, require_bill_id=False)
    updated = bills_db.update_payment(payment_id, cleaned)
    _refresh_bill_status(updated["bill_id"])
    return updated


def delete_payment(payment_id):
    existing = bills_db.get_payment(payment_id)
    result = bills_db.delete_payment(payment_id)
    if existing is not None:
        _refresh_bill_status(existing["bill_id"])
    return result
