"""JSON API routes for bills: list/create/read/update/delete, payments, confirm."""
from datetime import timedelta

from flask import Blueprint, jsonify, request

from sophia.backend import config
from sophia.backend.clients import bills_db
from sophia.backend.engine import money
from sophia.backend.engine.calendar import usual_range
from sophia.backend.engine.dates import expected_per_month
from sophia.backend.engine.projection import project
from sophia.backend.engine.status import derive_status

bp = Blueprint("bills", __name__, url_prefix="/api")


def enrich_bill(bill_row, payments, today):
    """Return bill_row plus status, status_label, next_occurrence, usual_range, monthly_equivalent_cents."""
    bill = bills_db.row_to_bill(bill_row)
    status, label = derive_status(bill, payments, today)
    occurrences = project(bill, today, today + timedelta(days=400))
    next_occurrence = occurrences[0].date.isoformat() if occurrences else None
    lo, hi = usual_range(bill, payments)
    enriched = dict(bill_row)
    enriched["status"] = status
    enriched["status_label"] = label
    enriched["next_occurrence"] = next_occurrence
    enriched["usual_range"] = {
        "lo": money.format_actual(lo),
        "hi": money.format_actual(hi),
        "lo_cents": lo,
        "hi_cents": hi,
    }
    enriched["monthly_equivalent_cents"] = bill.amount_cents * expected_per_month(bill.cadence)
    return enriched, status


@bp.get("/bills")
def list_bills():
    today = config.DEMO_TODAY
    bill_rows = bills_db.list_bills()
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_payments()]
    type_filter = request.args.get("type")
    status_filter = request.args.get("status")
    results = []
    for row in bill_rows:
        enriched, status = enrich_bill(row, payments, today)
        if row.get("status") != status:
            bills_db.update_bill(row["id"], {"status": status})
        if type_filter and enriched["type"] != type_filter:
            continue
        if status_filter and enriched["status"] != status_filter:
            continue
        results.append(enriched)
    return jsonify(results)


@bp.post("/bills")
def create_bill():
    payload = request.get_json(silent=True) or {}
    created = bills_db.create_bill(payload)
    return jsonify(created), 201


@bp.get("/bills/<int:bill_id>")
def get_bill(bill_id):
    row = bills_db.get_bill(bill_id)
    if row is None:
        return jsonify({"error": "bill not found"}), 404
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_bill_payments(bill_id)]
    enriched, status = enrich_bill(row, payments, config.DEMO_TODAY)
    if row.get("status") != status:
        bills_db.update_bill(bill_id, {"status": status})
    return jsonify(enriched)


@bp.put("/bills/<int:bill_id>")
def update_bill(bill_id):
    payload = request.get_json(silent=True) or {}
    updated = bills_db.update_bill(bill_id, payload)
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_bill_payments(bill_id)]
    enriched, status = enrich_bill(updated, payments, config.DEMO_TODAY)
    if updated.get("status") != status:
        updated = bills_db.update_bill(bill_id, {"status": status})
        enriched, _status = enrich_bill(updated, payments, config.DEMO_TODAY)
    return jsonify(enriched)


@bp.delete("/bills/<int:bill_id>")
def delete_bill(bill_id):
    return jsonify(bills_db.delete_bill(bill_id))


@bp.get("/bills/<int:bill_id>/payments")
def list_bill_payments(bill_id):
    return jsonify(bills_db.list_bill_payments(bill_id))


@bp.post("/bills/<int:bill_id>/confirm")
def confirm_bill(bill_id):
    updated = bills_db.update_bill(bill_id, {"confirmed_at": config.DEMO_TODAY.isoformat()})
    return jsonify(updated)
