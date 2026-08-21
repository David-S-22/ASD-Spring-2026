"""HTMX HTML fragment routes for the frontend, under /ui/*."""
import json
from datetime import date, datetime

from flask import Blueprint, render_template, request

from sophia.backend import config
from sophia.backend.clients import bills_db
from sophia.backend.engine import money
from sophia.backend.engine.calendar import month_breakdown
from sophia.backend.engine.dates import add_months, expected_per_month
from sophia.backend.engine.projection import timeline as project_timeline
from sophia.backend.engine.status import derive_status

bp = Blueprint("fragments", __name__, url_prefix="/ui")

CADENCE_LABELS = {"weekly": "Week", "fortnightly": "Fortnight", "monthly": "Month"}
PAYMENT_METHOD_LABELS = {"direct_debit": "Direct debit", "card": "Card", "bpay": "BPAY", None: "—"}
UNIT_WORDS = {"weekly": ("week", "weeks"), "fortnightly": ("fortnight", "fortnights"), "monthly": ("month", "months")}
COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _count_word(n):
    return COUNT_WORDS.get(n, str(n))


def _short_date(d):
    return f"{d.day} {d.strftime('%b')}"


def _day_month_label(d):
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def _load_bills_and_payments():
    bills = [bills_db.row_to_bill(r) for r in bills_db.list_bills()]
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_payments()]
    return bills, payments


def _extra_line_text(extra, bills_by_id, month_name):
    amount = money.format_actual(extra.amount_cents)
    if extra.reason == "starts":
        return f"{extra.name} starts +{amount}"
    if extra.reason == "extra_occurrence":
        bill = bills_by_id.get(extra.bill_id)
        cadence = bill.cadence if bill else "monthly"
        total = expected_per_month(cadence) + extra.count
        singular, plural = UNIT_WORDS.get(cadence, (cadence, cadence))
        unit = singular if total == 1 else plural
        return f"Extra {extra.name} payment — {_count_word(total)} {unit} land in {month_name} +{amount}"
    return f"{extra.name} +{amount}"


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
                "next_occurrence": _short_date(bill.next_billing_date),
                "payment_method_label": PAYMENT_METHOD_LABELS.get(bill.payment_method, bill.payment_method),
                "status": status,
                "status_label": label,
                "needs_confirmation": bill.source == "f4_handoff" and bill.confirmed_at is None,
            }
        )
    monthly_total = money.format_actual(sum(b.amount_cents * expected_per_month(b.cadence) for b in bills))
    return render_template("bills_table.html", bills=rows, monthly_total=monthly_total)


@bp.get("/calendar")
def calendar_card():
    today = config.DEMO_TODAY
    bills, payments = _load_bills_and_payments()
    bills_by_id = {bill.id: bill for bill in bills}
    plan_month = add_months(today.replace(day=1), 1)
    month_name = plan_month.strftime("%B")
    breakdown = month_breakdown(bills, payments, plan_month.year, plan_month.month, today)
    return render_template(
        "calendar_card.html",
        month_name=month_name,
        total_high=money.format_estimate_single(breakdown.total_high_cents),
        has_extras=bool(breakdown.extras),
        usual_range=money.format_estimate(breakdown.usual_low_cents, breakdown.usual_high_cents),
        extras=[_extra_line_text(e, bills_by_id, month_name) for e in breakdown.extras],
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
            "within_30_days": (occ.date - today).days < 30,
        }
        for occ in occurrences
    ]
    return render_template("timeline.html", items=items, days=max(30, min(180, days)))


@bp.get("/disputes")
def dispute_panel():
    bill_id = request.args.get("bill_id", type=int)
    dispute_id = request.args.get("dispute_id", type=int)
    version = request.args.get("version", type=int)

    disputes = bills_db.list_disputes()
    dispute = None
    if dispute_id is not None:
        dispute = next((d for d in disputes if d["id"] == dispute_id), None)
    elif bill_id is not None:
        dispute = next((d for d in disputes if d["bill_id"] == bill_id), None)
    elif disputes:
        dispute = disputes[0]

    if dispute is None:
        return render_template("dispute_panel.html", dispute=None, draft=None, context_line=None, versions=[], selected_version=None)

    drafts = bills_db.list_dispute_drafts(dispute["id"])
    versions = [d["version"] for d in drafts]
    chosen = next((d for d in drafts if d["version"] == version), None) or (drafts[-1] if drafts else None)
    draft = None
    if chosen:
        steps_data = json.loads(chosen["steps_json"])
        draft = {"letter_text": chosen["letter_text"], "steps": steps_data["steps"], "escalation": steps_data["escalation"]}

    bill_row = bills_db.get_bill(dispute["bill_id"])
    context_line = None
    if bill_row and bill_row["next_billing_date"] > config.DEMO_TODAY.isoformat():
        next_date = _day_month_label(date.fromisoformat(bill_row["next_billing_date"]))
        context_line = f"Next billing is {next_date}. Cancel before then and you won't be charged."

    return render_template(
        "dispute_panel.html",
        dispute=dispute,
        draft=draft,
        context_line=context_line,
        versions=versions,
        selected_version=chosen["version"] if chosen else None,
    )


def _history_heading(created_at, today):
    parsed = datetime.fromisoformat(created_at).date()
    if parsed == today:
        return None
    return f"Earlier — {parsed.strftime('%a')} {parsed.day} {parsed.strftime('%b')}"


@bp.get("/chat")
def chat_panel():
    today = config.DEMO_TODAY
    rows = bills_db.list_chat_messages()
    messages = []
    seen_headings = set()
    for row in rows:
        heading = _history_heading(row["created_at"], today)
        show_heading = heading is not None and heading not in seen_headings
        if show_heading:
            seen_headings.add(heading)
        preview = json.loads(row["op_json"]) if row.get("op_json") else None
        messages.append(
            {
                "role": row["role"],
                "content": row["content"],
                "heading": heading if show_heading else None,
                "preview": preview,
            }
        )
    return render_template("chat_panel.html", messages=messages)


@bp.get("/modal")
def modal():
    return render_template(
        "modal.html", confirm_url=request.args.get("confirm_url", ""), confirm_payload=request.args.get("payload", "{}")
    )


@bp.get("/toast")
def toast():
    return render_template("toast.html", text=request.args.get("text", "Done — change saved."))
