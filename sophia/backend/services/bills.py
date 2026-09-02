"""Bill CRUD and enrichment, shared by /api/bills and /ui/bills."""
from datetime import date, timedelta

from sophia.backend import config
from sophia.backend.clients import bills_db
from sophia.backend.engine import money
from sophia.backend.engine.calendar import usual_range
from sophia.backend.engine.dates import expected_per_month
from sophia.backend.engine.projection import project
from sophia.backend.engine.status import derive_status
from sophia.backend.services.errors import NotFound, ServiceError

REQUIRED_FIELDS = ["name", "merchant", "amount_cents", "cadence", "next_billing_date", "type"]
BOOLISH_TRUE = (1, "1", True, "on", "true", "True")


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


def _persist_status_if_drifted(bill_row, payments=None):
    """Sync the cached status column with derivation; returns the up-to-date row.

    Write paths only. Reads must stay side-effect free — they always return the
    derived status, so the stored column is just a cache for direct :6005 readers.
    """
    if payments is None:
        payments = [bills_db.row_to_payment(r) for r in bills_db.list_bill_payments(bill_row["id"])]
    status, _label = derive_status(bills_db.row_to_bill(bill_row), payments, config.DEMO_TODAY)
    if bill_row.get("status") != status:
        return bills_db.update_bill(bill_row["id"], {"status": status})
    return bill_row


def list_bills(type_filter=None, status_filter=None):
    today = config.DEMO_TODAY
    bill_rows = bills_db.list_bills()
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_payments()]
    results = []
    for row in bill_rows:
        enriched, _status = enrich_bill(row, payments, today)
        if type_filter and enriched["type"] != type_filter:
            continue
        if status_filter and enriched["status"] != status_filter:
            continue
        results.append(enriched)
    return results


def _clean_payload(payload, partial):
    cleaned = dict(payload)
    if not partial:
        missing = [f for f in REQUIRED_FIELDS if not cleaned.get(f)]
        if missing:
            raise ServiceError(f"missing required fields: {', '.join(missing)}")
    if cleaned.get("amount_cents") not in (None, ""):
        try:
            cleaned["amount_cents"] = int(cleaned["amount_cents"])
        except (TypeError, ValueError):
            raise ServiceError("amount_cents must be a whole number of cents")
    if "next_billing_date" in cleaned and cleaned["next_billing_date"]:
        try:
            date.fromisoformat(cleaned["next_billing_date"])
        except ValueError:
            raise ServiceError("next_billing_date must be YYYY-MM-DD")
    if "end_date" in cleaned and cleaned["end_date"]:
        try:
            date.fromisoformat(cleaned["end_date"])
        except ValueError:
            raise ServiceError("end_date must be YYYY-MM-DD")
    if "exclude_from_plan" in cleaned:
        cleaned["exclude_from_plan"] = 1 if cleaned["exclude_from_plan"] in BOOLISH_TRUE else 0
    return cleaned


def create_bill(payload):
    cleaned = _clean_payload(payload, partial=False)
    # Stamp created_at on the demo clock, not the DB's real UTC now. The app
    # reasons entirely in DEMO_TODAY, and projection drops occurrences before
    # created_at — a bill added with a next charge "before" the real date was
    # in the table but missing from the timeline and calendar. (The DB default
    # is also UTC, which in Australia/Sydney is yesterday until ~10am.)
    cleaned.setdefault("created_at", config.DEMO_TODAY.isoformat())
    created = bills_db.create_bill(cleaned)
    return _persist_status_if_drifted(created, payments=[])


def get_bill(bill_id):
    row = bills_db.get_bill(bill_id)
    if row is None:
        raise NotFound("bill not found")
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_bill_payments(bill_id)]
    enriched, _status = enrich_bill(row, payments, config.DEMO_TODAY)
    return enriched


def update_bill(bill_id, payload):
    if bills_db.get_bill(bill_id) is None:
        raise NotFound("bill not found")
    cleaned = _clean_payload(payload, partial=True)
    updated = bills_db.update_bill(bill_id, cleaned)
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_bill_payments(bill_id)]
    updated = _persist_status_if_drifted(updated, payments)
    enriched, _status = enrich_bill(updated, payments, config.DEMO_TODAY)
    return enriched


def delete_bill(bill_id):
    if bills_db.get_bill(bill_id) is None:
        raise NotFound("bill not found")
    return bills_db.delete_bill(bill_id)


def list_bill_payments(bill_id):
    return bills_db.list_bill_payments(bill_id)


def confirm_bill(bill_id):
    if bills_db.get_bill(bill_id) is None:
        raise NotFound("bill not found")
    return bills_db.update_bill(bill_id, {"confirmed_at": config.DEMO_TODAY.isoformat()})


def cancel_bill(bill_id, end_date):
    if not end_date:
        raise ServiceError("end_date is required")
    try:
        date.fromisoformat(end_date)
    except ValueError:
        raise ServiceError("end_date must be YYYY-MM-DD")
    if bills_db.get_bill(bill_id) is None:
        raise NotFound("bill not found")
    updated = bills_db.update_bill(bill_id, {"end_date": end_date})
    return _persist_status_if_drifted(updated)
