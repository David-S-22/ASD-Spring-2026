"""HTTP client for the bills database API (:6005)."""
from datetime import date

import requests

from sophia.backend import config
from sophia.backend.engine import Bill, Payment
from sophia.backend.services.errors import ServiceError


def _url(path):
    return f"{config.BILLS_DB_API_URL}{path}"


def _raise_for_status(response):
    """Raise a ServiceError carrying the bills-db API's own message and status for a 4xx
    response, so a value it rejects comes back as a clean 400/404, never an unhandled 500.
    """
    if 400 <= response.status_code < 500:
        try:
            message = response.json().get("error", response.text)
        except ValueError:
            message = response.text or f"bills-db returned {response.status_code}"
        raise ServiceError(message, status=response.status_code)
    response.raise_for_status()
    return response


def _parse_date(value):
    return date.fromisoformat(value) if value else None


def row_to_bill(row):
    """Convert a bills-db JSON row into an engine Bill."""
    return Bill(
        id=row["id"],
        name=row["name"],
        merchant=row["merchant"],
        amount_cents=row["amount_cents"],
        cadence=row["cadence"],
        next_billing_date=_parse_date(row["next_billing_date"]),
        type=row["type"],
        payment_method=row.get("payment_method"),
        end_date=_parse_date(row.get("end_date")),
        confirmed_at=_parse_date(row.get("confirmed_at")),
        created_at=_parse_date(row.get("created_at")),
        source=row.get("source") or "manual",
    )


def row_to_payment(row):
    """Convert a bills-db JSON row into an engine Payment."""
    return Payment(bill_id=row["bill_id"], date=_parse_date(row["date"]), amount_cents=row["amount_cents"])


def list_bills():
    response = requests.get(_url("/bills"), timeout=10)
    _raise_for_status(response)
    return response.json()


def get_bill(bill_id):
    response = requests.get(_url(f"/bills/{bill_id}"), timeout=10)
    if response.status_code == 404:
        return None
    _raise_for_status(response)
    return response.json()


def create_bill(payload):
    response = requests.post(_url("/bills"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def update_bill(bill_id, payload):
    response = requests.put(_url(f"/bills/{bill_id}"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def delete_bill(bill_id):
    response = requests.delete(_url(f"/bills/{bill_id}"), timeout=10)
    _raise_for_status(response)
    return response.json()


def list_bill_payments(bill_id):
    response = requests.get(_url(f"/bills/{bill_id}/payments"), timeout=10)
    _raise_for_status(response)
    return response.json()


def list_payments():
    response = requests.get(_url("/payments"), timeout=10)
    _raise_for_status(response)
    return response.json()


def create_payment(payload):
    response = requests.post(_url("/payments"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def get_payment(payment_id):
    response = requests.get(_url(f"/payments/{payment_id}"), timeout=10)
    if response.status_code == 404:
        return None
    _raise_for_status(response)
    return response.json()


def update_payment(payment_id, payload):
    response = requests.put(_url(f"/payments/{payment_id}"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def delete_payment(payment_id):
    response = requests.delete(_url(f"/payments/{payment_id}"), timeout=10)
    _raise_for_status(response)
    return response.json()


def list_disputes():
    response = requests.get(_url("/disputes"), timeout=10)
    _raise_for_status(response)
    return response.json()


def create_dispute(payload):
    response = requests.post(_url("/disputes"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def get_dispute(dispute_id):
    response = requests.get(_url(f"/disputes/{dispute_id}"), timeout=10)
    if response.status_code == 404:
        return None
    _raise_for_status(response)
    return response.json()


def update_dispute(dispute_id, payload):
    response = requests.put(_url(f"/disputes/{dispute_id}"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def delete_dispute(dispute_id):
    response = requests.delete(_url(f"/disputes/{dispute_id}"), timeout=10)
    _raise_for_status(response)
    return response.json()


def list_dispute_drafts(dispute_id):
    response = requests.get(_url(f"/disputes/{dispute_id}/drafts"), timeout=10)
    _raise_for_status(response)
    return response.json()


def create_dispute_draft(dispute_id, payload):
    response = requests.post(_url(f"/disputes/{dispute_id}/drafts"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def list_chat_messages():
    response = requests.get(_url("/chat_messages"), timeout=10)
    _raise_for_status(response)
    return response.json()


def create_chat_message(payload):
    response = requests.post(_url("/chat_messages"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def update_chat_message(message_id, payload):
    response = requests.put(_url(f"/chat_messages/{message_id}"), json=payload, timeout=10)
    _raise_for_status(response)
    return response.json()


def health():
    response = requests.get(_url("/health"), timeout=5)
    _raise_for_status(response)
    return response.json()
