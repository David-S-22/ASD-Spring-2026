"""JSON API routes for payments; each write recomputes and stores the owning bill's status."""
from flask import Blueprint, jsonify, request

from sophia.backend import config
from sophia.backend.clients import bills_db
from sophia.backend.engine.status import derive_status

bp = Blueprint("payments", __name__, url_prefix="/api")


def _refresh_bill_status(bill_id):
    bill_row = bills_db.get_bill(bill_id)
    if bill_row is None:
        return
    bill = bills_db.row_to_bill(bill_row)
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_bill_payments(bill_id)]
    status, _label = derive_status(bill, payments, config.DEMO_TODAY)
    if bill_row.get("status") != status:
        bills_db.update_bill(bill_id, {"status": status})


@bp.post("/payments")
def create_payment():
    payload = request.get_json(silent=True) or {}
    created = bills_db.create_payment(payload)
    _refresh_bill_status(created["bill_id"])
    return jsonify(created), 201


@bp.put("/payments/<int:payment_id>")
def update_payment(payment_id):
    payload = request.get_json(silent=True) or {}
    updated = bills_db.update_payment(payment_id, payload)
    _refresh_bill_status(updated["bill_id"])
    return jsonify(updated)


@bp.delete("/payments/<int:payment_id>")
def delete_payment(payment_id):
    existing = bills_db.get_payment(payment_id)
    result = bills_db.delete_payment(payment_id)
    if existing is not None:
        _refresh_bill_status(existing["bill_id"])
    return jsonify(result)
