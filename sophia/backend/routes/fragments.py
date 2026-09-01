"""HTMX HTML fragment routes for the frontend, under /ui/*.

Every write handler here is parse form -> service call -> render: the
services module (shared with /api/*) does the actual work, this module only
turns a Flask form into plain arguments and turns the result into HTML plus
an HX-Trigger toast header.
"""
import json
import math
from datetime import date, datetime, timedelta

from flask import Blueprint, make_response, render_template, request

from sophia.backend import config
from sophia.backend.clients import bills_db
from sophia.backend.engine import Bill, money
from sophia.backend.engine.calendar import month_breakdown
from sophia.backend.engine.dates import add_months, expected_per_month
from sophia.backend.engine.projection import project, timeline as project_timeline
from sophia.backend.engine.status import derive_status
from sophia.backend.services import bills as bills_service
from sophia.backend.services import chat as chat_service
from sophia.backend.services import disputes as disputes_service
from sophia.backend.services import payments as payments_service
from sophia.backend.services.calendar import parse_year_month
from sophia.backend.services.errors import ServiceError

bp = Blueprint("fragments", __name__, url_prefix="/ui")

CADENCE_LABELS = {"weekly": "Week", "fortnightly": "Fortnight", "monthly": "Month"}
PAYMENT_METHOD_LABELS = {"direct_debit": "Direct debit", "card": "Card", "bpay": "BPAY", None: "—"}
UNIT_WORDS = {"weekly": ("week", "weeks"), "fortnightly": ("fortnight", "fortnights"), "monthly": ("month", "months")}
COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
KIND_LABELS = {"predicted": "Predicted", "overdue": "Overdue"}


@bp.errorhandler(ServiceError)
def handle_service_error(error):
    return render_template("error_fragment.html", message=error.message), 422


@bp.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, ServiceError):
        raise error
    return render_template("error_fragment.html", message="Something went wrong — try again."), 500


def _count_word(n):
    return COUNT_WORDS.get(n, str(n))


def _short_date(d):
    return f"{d.day} {d.strftime('%b')}"


def _day_month_label(d):
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def _toast_headers(text):
    return {"HX-Trigger": json.dumps({"toast": text})}


def _form_to_bill_payload(form):
    """Convert the add/edit bill form (dollars, checkbox) into a service payload (cents, 0/1)."""
    payload = form.to_dict()
    if "amount" in payload:
        raw = payload.pop("amount")
        try:
            payload["amount_cents"] = round(float(raw) * 100)
        except (TypeError, ValueError):
            payload["amount_cents"] = raw
    payload["exclude_from_plan"] = 1 if "exclude_from_plan" in payload else 0
    return payload


def _form_to_payment_payload(form):
    """Convert the record-payment form (dollars) into a service payload (cents)."""
    payload = form.to_dict()
    if "amount" in payload:
        raw = payload.pop("amount")
        try:
            payload["amount_cents"] = round(float(raw) * 100)
        except (TypeError, ValueError):
            payload["amount_cents"] = raw
    return payload


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


def _render_bills_table():
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
                "next_billing": _short_date(bill.next_billing_date),
                "payment_method_label": PAYMENT_METHOD_LABELS.get(bill.payment_method, bill.payment_method),
                "status": status,
                "status_label": label,
                "needs_confirmation": bill.source == "f4_handoff" and bill.confirmed_at is None,
            }
        )
    monthly_total = money.format_actual(sum(b.amount_cents * expected_per_month(b.cadence) for b in bills))
    return render_template("bills_table.html", bills=rows, monthly_total=monthly_total)


def _render_calendar_card(plan_month=None, oob=False):
    """Render the calendar card for plan_month (default: the month after today).

    Only this rendering excludes bills.exclude_from_plan (decision D) - the
    chat "total" answer and /api/upcoming keep including everything.
    """
    today = config.DEMO_TODAY
    if plan_month is None:
        plan_month = add_months(today.replace(day=1), 1)
    bills, payments = _load_bills_and_payments()
    planned_bills = [b for b in bills if not b.exclude_from_plan]
    bills_by_id = {bill.id: bill for bill in planned_bills}
    month_name = plan_month.strftime("%B")
    breakdown = month_breakdown(planned_bills, payments, plan_month.year, plan_month.month, today)
    return render_template(
        "calendar_card.html",
        month_name=month_name,
        total_high=money.format_estimate_single(breakdown.total_high_cents),
        has_extras=bool(breakdown.extras),
        usual_range=money.format_estimate(breakdown.usual_low_cents, breakdown.usual_high_cents),
        extras=[_extra_line_text(e, bills_by_id, month_name) for e in breakdown.extras],
        next_month_param=add_months(plan_month, 1).strftime("%Y-%m"),
        oob=oob,
    )


def _render_timeline(days=30, oob=False):
    today = config.DEMO_TODAY
    bills, payments = _load_bills_and_payments()
    occurrences = project_timeline(bills, payments, today, days)
    items = []
    for occ in occurrences:
        if occ.kind in ("overdue", "actual"):
            display_amount = money.format_actual(occ.amount_cents)
            tag = KIND_LABELS.get(occ.kind)
        else:
            display_amount = money.format_estimate_single(occ.amount_cents)
            tag = None if (occ.date - today).days < 30 else KIND_LABELS.get(occ.kind)
        items.append(
            {
                "day_label": _day_month_label(occ.date),
                "name": occ.name,
                "display_amount": display_amount,
                "kind": occ.kind,
                "tag": tag,
            }
        )
    return render_template("timeline.html", items=items, days=max(30, min(180, days)), oob=oob)


@bp.get("/bills")
def bills_table():
    return _render_bills_table()


@bp.get("/calendar")
def calendar_card():
    month_param = request.args.get("month")
    plan_month = None
    if month_param:
        year, month = parse_year_month(month_param)
        plan_month = date(year, month, 1)
    return _render_calendar_card(plan_month=plan_month)


@bp.get("/timeline")
def timeline_fragment():
    days = int(request.args.get("days", 30))
    return _render_timeline(days=days)


def _bills_write_response(toast_text, status=200, refresh_projection=True):
    html = _render_bills_table()
    if refresh_projection:
        html += _render_timeline(oob=True)
        html += _render_calendar_card(oob=True)
    response = make_response(html, status)
    response.headers.update(_toast_headers(toast_text))
    return response


@bp.get("/bills/new-form")
def bill_new_form():
    return render_template("bill_form.html", bill=None, action="/bills-backend/ui/bills")


@bp.get("/bills/<int:bill_id>/edit")
def bill_edit_form(bill_id):
    bill = bills_service.get_bill(bill_id)
    return render_template("bill_form.html", bill=bill, action=f"/bills-backend/ui/bills/{bill_id}/edit")


def _parse_handoff_subscription(args):
    """Validate the Feature 4 link-handoff query params into prefill values."""
    if args.get("source") != "f4":
        raise ServiceError("This link is missing source=f4 — check it came from Spending Alerts.")
    merchant = (args.get("merchant") or "").strip()
    if not merchant:
        raise ServiceError("The link needs a merchant name.")
    try:
        amount = float(args.get("amount", ""))
    except ValueError:
        raise ServiceError("The amount in the link isn't a number.")
    if not math.isfinite(amount):
        raise ServiceError("The amount in the link isn't a usable number.")
    if amount < 0:
        raise ServiceError("The amount in the link can't be negative.")
    cadence = args.get("cadence")
    if cadence not in CADENCE_LABELS:
        raise ServiceError("Cadence must be weekly, fortnightly or monthly.")
    try:
        first_seen = date.fromisoformat(args.get("first_seen", ""))
        last_seen = date.fromisoformat(args.get("last_seen", ""))
    except ValueError:
        raise ServiceError("first_seen and last_seen must be YYYY-MM-DD dates.")
    if first_seen > last_seen:
        raise ServiceError("first_seen can't be after last_seen.")
    try:
        occurrences = int(args.get("occurrences", ""))
    except ValueError:
        raise ServiceError("occurrences must be a whole number.")
    if occurrences < 1:
        raise ServiceError("occurrences must be at least 1.")
    return merchant, round(amount * 100), cadence, first_seen, last_seen, occurrences


def _next_billing_from(last_seen, cadence, merchant, amount_cents):
    """First projected occurrence strictly after last_seen, on the demo clock."""
    today = config.DEMO_TODAY
    if last_seen > today:
        return last_seen
    bill = Bill(
        id=0,
        name=merchant,
        merchant=merchant,
        amount_cents=amount_cents,
        cadence=cadence,
        next_billing_date=last_seen,
        type="subscription",
    )
    occurrences = project(bill, today, today + timedelta(days=400))
    return next((occ.date for occ in occurrences if occ.date > last_seen), last_seen)


@bp.get("/handoff/subscription")
def handoff_subscription_form():
    merchant, amount_cents, cadence, first_seen, last_seen, occurrences = _parse_handoff_subscription(request.args)
    bill = {
        "name": merchant,
        "merchant": merchant,
        "amount_cents": amount_cents,
        "cadence": cadence,
        "next_billing_date": _next_billing_from(last_seen, cadence, merchant, amount_cents).isoformat(),
        "type": "subscription",
        "payment_method": None,
        "source": "f4_handoff",
    }
    evidence = {
        "occurrences": occurrences,
        "first_seen": first_seen.isoformat(),
        "last_seen": last_seen.isoformat(),
        "low_confidence": request.args.get("confidence") == "low",
        "return_url": request.args.get("return_url"),
    }
    return render_template("bill_form.html", bill=bill, action="/bills-backend/ui/bills", evidence=evidence)


@bp.post("/bills")
def bills_create():
    bills_service.create_bill(_form_to_bill_payload(request.form))
    return _bills_write_response("Done — change saved.", status=201)


@bp.post("/bills/<int:bill_id>/edit")
def bills_edit(bill_id):
    bills_service.update_bill(bill_id, _form_to_bill_payload(request.form))
    return _bills_write_response("Done — change saved.")


@bp.post("/bills/<int:bill_id>/delete")
def bills_delete(bill_id):
    bills_service.delete_bill(bill_id)
    return _bills_write_response("Done — removed.")


@bp.get("/bills/<int:bill_id>/cancel-form")
def bill_cancel_form(bill_id):
    bill = bills_service.get_bill(bill_id)
    return render_template("cancel_form.html", bill=bill)


@bp.post("/bills/<int:bill_id>/cancel")
def bills_cancel(bill_id):
    bills_service.cancel_bill(bill_id, request.form.get("end_date"))
    return _bills_write_response("Done — change saved.")


@bp.post("/bills/<int:bill_id>/confirm")
def bills_confirm(bill_id):
    bills_service.confirm_bill(bill_id)
    return _bills_write_response("Done — change saved.", refresh_projection=False)


@bp.get("/bills/<int:bill_id>/payment-form")
def payment_form(bill_id):
    bill = bills_service.get_bill(bill_id)
    return render_template("payment_form.html", bill=bill, today=config.DEMO_TODAY.isoformat())


@bp.post("/payments")
def payments_create():
    payments_service.create_payment(_form_to_payment_payload(request.form))
    return _bills_write_response("Done — change saved.", status=201)


@bp.get("/bills/<int:bill_id>/dispute-form")
def dispute_form(bill_id):
    bill = bills_service.get_bill(bill_id)
    return render_template("dispute_form.html", bill=bill)


def _render_dispute_panel(dispute_id=None, bill_id=None, version=None, oob=False):
    disputes = bills_db.list_disputes()
    dispute = None
    if dispute_id is not None:
        dispute = next((d for d in disputes if d["id"] == dispute_id), None)
    elif bill_id is not None:
        dispute = next((d for d in disputes if d["bill_id"] == bill_id), None)
    elif disputes:
        dispute = disputes[0]

    if dispute is None:
        return render_template("dispute_panel.html", dispute=None, draft=None, context_line=None, versions=[], selected_version=None, oob=oob)

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
        oob=oob,
    )


@bp.get("/disputes")
def dispute_panel():
    return _render_dispute_panel(
        dispute_id=request.args.get("dispute_id", type=int),
        bill_id=request.args.get("bill_id", type=int),
        version=request.args.get("version", type=int),
    )


def _dispute_write_response(dispute_id, toast_text, status=200):
    html = _render_dispute_panel(dispute_id=dispute_id)
    response = make_response(html, status)
    response.headers.update(_toast_headers(toast_text))
    return response


@bp.post("/disputes")
def disputes_create():
    dispute = disputes_service.create_dispute(request.form.get("bill_id", type=int), request.form.get("reason"))
    html = _render_dispute_panel(dispute_id=dispute["id"])
    response = make_response(html, 201)
    response.headers["HX-Trigger"] = json.dumps({"toast": "Done — change saved.", "switchTab": "disputes"})
    return response


@bp.post("/disputes/<int:dispute_id>/status")
def disputes_status(dispute_id):
    disputes_service.update_status(dispute_id, request.form.get("status"))
    return _dispute_write_response(dispute_id, "Done — change saved.")


@bp.post("/disputes/<int:dispute_id>/regenerate")
def disputes_regenerate(dispute_id):
    disputes_service.regenerate(
        dispute_id, edited_letter=request.form.get("edited_letter"), feedback=request.form.get("feedback")
    )
    return _dispute_write_response(dispute_id, "Done — change saved.")


def _render_disputes_tab():
    disputes = bills_db.list_disputes()
    bills_by_id = {b["id"]: b for b in bills_db.list_bills()}
    rows = []
    for d in disputes:
        bill = bills_by_id.get(d["bill_id"], {})
        rows.append(
            {
                "id": d["id"],
                "bill_name": bill.get("name", "Unknown"),
                "reason": d["reason"],
                "status": d["status"],
                "opened_at": _short_date(date.fromisoformat(d["opened_at"])),
            }
        )
    return render_template("disputes_tab.html", disputes=rows)


@bp.get("/disputes-tab")
def disputes_tab():
    return _render_disputes_tab()


@bp.get("/chat")
def chat_panel():
    return _render_chat_panel()


def _render_chat_panel():
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
        if preview:
            preview["message_id"] = row["id"]
        messages.append(
            {
                "role": row["role"],
                "content": row["content"],
                "heading": heading if show_heading else None,
                "preview": preview,
                "applied": bool(row.get("applied")),
            }
        )
    return render_template("chat_panel.html", messages=messages)


def _history_heading(created_at, today):
    parsed = datetime.fromisoformat(created_at).date()
    if parsed == today:
        return None
    return f"Earlier — {parsed.strftime('%a')} {parsed.day} {parsed.strftime('%b')}"


@bp.post("/chat")
def chat_send():
    result = chat_service.send_message(request.form.get("message", ""))
    reply_html = render_template(
        "chat_reply.html", reply=result["reply"], preview=result["preview"], fallback=result["fallback"]
    )
    response = make_response(reply_html, 200)
    response.headers.update(_toast_headers("Done — change saved."))
    return response


@bp.post("/chat/apply")
def chat_apply():
    fields = json.loads(request.form.get("fields") or "{}")
    message_id = request.form.get("message_id", type=int)
    chat_service.apply(
        request.form.get("op"),
        request.form.get("entity"),
        _coerce_id(request.form.get("id")),
        fields,
        message_id=message_id,
    )
    applied_html = render_template("chat_applied.html")
    html = applied_html + _render_bills_table_oob() + _render_timeline(oob=True) + _render_calendar_card(oob=True)
    response = make_response(html, 200)
    response.headers.update(_toast_headers("Done — change saved."))
    return response


def _render_bills_table_oob():
    html = _render_bills_table()
    return html.replace('id="bills-table"', 'id="bills-table" hx-swap-oob="true"', 1)


def _coerce_id(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


@bp.get("/modal")
def modal():
    return render_template(
        "modal.html", confirm_url=request.args.get("confirm_url", ""), confirm_payload=request.args.get("payload", "{}")
    )


@bp.get("/toast")
def toast():
    return render_template("toast.html", text=request.args.get("text", "Done — change saved."))
