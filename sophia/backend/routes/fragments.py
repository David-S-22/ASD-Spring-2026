"""HTMX HTML fragment routes for the frontend, under /ui/*."""
import json

from flask import Blueprint, render_template, request

from sophia.backend import config
from sophia.backend.clients import bills_db
from sophia.backend.engine import money
from sophia.backend.engine.calendar import month_breakdown
from sophia.backend.engine.projection import timeline as project_timeline
from sophia.backend.engine.status import derive_status

bp = Blueprint("fragments", __name__, url_prefix="/ui")

CADENCE_LABELS = {"weekly": "Week", "fortnightly": "Fortnight", "monthly": "Month"}
PAYMENT_METHOD_LABELS = {"direct_debit": "Direct debit", "card": "Card", "bpay": "BPAY", None: "—"}


def _day_month_label(d):
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def _load_bills_and_payments():
    bills = [bills_db.row_to_bill(r) for r in bills_db.list_bills()]
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_payments()]
    return bills, payments


@bp.get("/bills")
def bills_table():
    today = config.DEMO_TODAY
    bills, payments = _load_bills_and_payments()
    rows = []
    for bill in bills:
        status, label = derive_status(bill, payments, today)
        rows.append(
            {
                "id": bill.id,
                "name": bill.name,
                "amount": money.format_actual(bill.amount_cents),
                "cadence_label": CADENCE_LABELS.get(bill.cadence, bill.cadence),
                "next_occurrence": bill.next_billing_date.isoformat(),
                "payment_method_label": PAYMENT_METHOD_LABELS.get(bill.payment_method, bill.payment_method),
                "status": status,
                "status_label": label,
                "needs_confirmation": bill.confirmed_at is None,
            }
        )
    return render_template("bills_table.html", bills=rows)


@bp.get("/calendar")
def calendar_card():
    today = config.DEMO_TODAY
    bills, payments = _load_bills_and_payments()
    breakdown = month_breakdown(bills, payments, today.year, today.month, today)
    return render_template(
        "calendar_card.html",
        month_name=today.strftime("%B"),
        total_high=money.format_estimate_single(breakdown.total_high_cents),
        has_extras=bool(breakdown.extras),
        usual_range=money.format_estimate(breakdown.usual_low_cents, breakdown.usual_high_cents),
        extras=[{"name": e.name, "amount": money.format_actual(e.amount_cents)} for e in breakdown.extras],
    )


@bp.get("/timeline")
def timeline_fragment():
    today = config.DEMO_TODAY
    days = int(request.args.get("days", 30))
    bills, payments = _load_bills_and_payments()
    occurrences = project_timeline(bills, payments, today, days)
    items = [
        {
            "day_label": _day_month_label(occ.date),
            "name": occ.name,
            "display_amount": money.format_actual(occ.amount_cents)
            if occ.kind == "actual"
            else money.format_estimate_single(occ.amount_cents),
            "kind": occ.kind,
        }
        for occ in occurrences
    ]
    return render_template("timeline.html", items=items)


@bp.get("/disputes")
def dispute_panel():
    bill_id = request.args.get("bill_id", type=int)
    disputes = bills_db.list_disputes()
    if bill_id is not None:
        disputes = [d for d in disputes if d["bill_id"] == bill_id]
    if not disputes:
        return render_template("dispute_panel.html", dispute=None, draft=None, context_line=None)
    dispute = disputes[0]
    drafts = bills_db.list_dispute_drafts(dispute["id"])
    latest = drafts[-1] if drafts else None
    draft = None
    if latest:
        steps_data = json.loads(latest["steps_json"])
        draft = {"letter_text": latest["letter_text"], "steps": steps_data["steps"], "escalation": steps_data["escalation"]}
    bill_row = bills_db.get_bill(dispute["bill_id"])
    context_line = None
    if bill_row and bill_row["next_billing_date"] > config.DEMO_TODAY.isoformat():
        context_line = f"Next billing is {bill_row['next_billing_date']}. Cancel before then and you won't be charged."
    return render_template("dispute_panel.html", dispute=dispute, draft=draft, context_line=context_line)


@bp.get("/chat")
def chat_panel():
    history = bills_db.list_chat_messages()
    return render_template("chat_panel.html", history=history)


@bp.get("/modal")
def modal():
    return render_template(
        "modal.html", confirm_url=request.args.get("confirm_url", ""), confirm_payload=request.args.get("payload", "{}")
    )


@bp.get("/toast")
def toast():
    return render_template("toast.html", text=request.args.get("text", "Done — change saved."))
