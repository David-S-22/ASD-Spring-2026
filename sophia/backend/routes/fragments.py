"""HTMX HTML fragment routes for the frontend, under /ui/*.

Every write handler here is parse form -> service call -> render: the
services module (shared with /api/*) does the actual work, this module only
turns a Flask form into plain arguments and turns the result into HTML plus
an HX-Trigger toast header.
"""
import json
import math
from datetime import date, timedelta

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
                # derive_status returns "paid" for a bill whose current cycle is
                # settled, but relabels it "Due <date>" when the next charge is
                # within 7 days. Correct on both counts, and confusing together:
                # a green paid chip reading "Due 25 Aug" scans as money already
                # handled. The tone is presentation only -- `status` is what the
                # JSON API publishes and is untouched.
                "status_tone": "upcoming" if status == "paid" and label.startswith("Due ") else status,
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


# --- suggestions: the approve/reject window ---------------------------------

SUGGESTION_FIELD_LABELS = {
    "name": "Name", "merchant": "Merchant", "amount_cents": "Amount", "cadence": "Every",
    "next_billing_date": "Next billing", "type": "Type", "payment_method": "Paid by",
    "end_date": "Ends", "exclude_from_plan": "Excluded from plan", "bill_id": "Bill",
    "date": "Date", "reason": "Reason", "status": "Status",
}


def _suggestion_display_value(field, value):
    if value is None or value == "":
        return "—"
    if field == "amount_cents":
        return money.format_actual(int(value))
    if field == "cadence":
        return CADENCE_LABELS.get(value, value)
    if field == "payment_method":
        return PAYMENT_METHOD_LABELS.get(value, value)
    if field == "exclude_from_plan":
        return "yes" if value in (1, "1", True) else "no"
    return str(value)


def _detail_row(field, new_value, old_value=None):
    return {
        "label": SUGGESTION_FIELD_LABELS.get(field, field),
        "new": _suggestion_display_value(field, new_value),
        "old": _suggestion_display_value(field, old_value) if old_value is not None else None,
    }


BILL_SNAPSHOT_FIELDS = ("amount_cents", "cadence", "next_billing_date", "type", "payment_method")


def _suggestion_view(row):
    """Build the render model for one suggestion: a title naming the change, and
    field-level rows — a before/after diff for updates, the doomed row for
    deletes, the full proposal for creates. The user approves what they can
    read, never a bare Confirm button."""
    fields = json.loads(row["payload_json"]) if row["payload_json"] else {}
    op, entity, entity_id = row["op"], row["entity"], row["entity_id"]
    bill = None
    warning = None
    if entity == "bill" and entity_id:
        bill = bills_db.get_bill(entity_id)
    elif entity in ("payment", "dispute") and fields.get("bill_id"):
        bill = bills_db.get_bill(fields["bill_id"])
    bill_label = bill["name"] if bill else (f"bill {entity_id}" if entity_id else "a bill")

    rows = []
    if entity == "bill" and op == "create":
        title = f"Add bill: {fields.get('name', '?')}"
        rows = [_detail_row(f, fields[f]) for f in
                ("name", "merchant", "amount_cents", "cadence", "next_billing_date", "type", "payment_method", "end_date")
                if f in fields]
    elif entity == "bill" and op == "update":
        title = f"Update {bill_label}"
        if bill is None:
            warning = "This bill no longer exists — approving will fail."
        rows = [_detail_row(f, value, bill.get(f) if bill else None) for f, value in fields.items()]
    elif entity == "bill" and op == "delete":
        title = f"Delete {bill_label}"
        if bill is None:
            warning = "This bill no longer exists — approving will fail."
        else:
            rows = [_detail_row(f, bill.get(f)) for f in BILL_SNAPSHOT_FIELDS]
    elif entity == "payment":
        title = f"Record payment for {bill_label}" if op == "create" else f"Delete payment {entity_id}"
        rows = [_detail_row(f, fields[f]) for f in ("date", "amount_cents") if f in fields]
    else:
        title = f"Open dispute for {bill_label}" if op == "create" else f"Update dispute {entity_id}"
        rows = [_detail_row(f, fields[f]) for f in ("reason", "status") if f in fields]

    return {
        "id": row["id"], "status": row["status"], "error": row.get("error"),
        "title": title, "rows": rows, "warning": warning,
    }


def _render_suggestions_panel(oob=False):
    all_rows = bills_db.list_suggestions()
    visible = [r for r in all_rows if r["status"] in ("pending", "failed")]
    pending_count = sum(1 for r in visible if r["status"] == "pending")
    return render_template(
        "suggestions_panel.html",
        suggestions=[_suggestion_view(r) for r in visible],
        pending_count=pending_count,
        oob=oob,
    )


@bp.get("/suggestions")
def suggestions_panel():
    return _render_suggestions_panel()


def _suggestion_action_response(action, suggestion_id):
    """Approve or reject, then tell every surface the truth: the refreshed
    panel is the primary swap, the bills views ride along OOB when something
    was applied, and a suggestionResolved trigger lets the chat's inline card
    flip to the same resolved state."""
    toast = None
    try:
        if action == "approve":
            chat_service.approve_suggestion(suggestion_id)
            toast = "Done — change saved."
        else:
            chat_service.reject_suggestion(suggestion_id)
            toast = "Dismissed — nothing was changed."
    except ServiceError as error:
        toast = f"Couldn't apply: {error.message}" if action == "approve" else error.message

    row = bills_db.get_suggestion(suggestion_id)
    status = row["status"] if row else "failed"
    html = _render_suggestions_panel()
    if status == "applied":
        html += _render_bills_table_oob() + _render_timeline(oob=True) + _render_calendar_card(oob=True)
    response = make_response(html, 200)
    response.headers["HX-Trigger"] = json.dumps(
        {"toast": toast, "suggestionResolved": {"id": suggestion_id, "status": status}}
    )
    return response


@bp.post("/suggestions/<int:suggestion_id>/approve")
def suggestion_approve(suggestion_id):
    return _suggestion_action_response("approve", suggestion_id)


@bp.post("/suggestions/<int:suggestion_id>/reject")
def suggestion_reject(suggestion_id):
    return _suggestion_action_response("reject", suggestion_id)


@bp.get("/chat")
def chat_panel():
    return _render_chat_panel()


def _render_chat_panel():
    """Open the panel clean rather than replaying stored history.

    The seeded conversation stays in the database -- the ten chat_messages rows
    are part of the seed the spec asks for, and services.chat still reads the
    last ten of them as context for the model, so the assistant is no less
    informed. What changes is only that the panel does not render them on open:
    a fresh panel is a fresh conversation, not somebody else's transcript from
    17 August.

    Messages sent during a session are appended by htmx (hx-swap="beforeend" on
    .history) and stay visible until the panel is re-fetched, at which point it
    returns to the welcome state.
    """
    return render_template("chat_panel.html", messages=[])


@bp.post("/chat")
def chat_send():
    result = chat_service.send_message(request.form.get("message", ""))
    suggestion_view = None
    if result["preview"] and result["preview"].get("suggestion_id"):
        suggestion_row = bills_db.get_suggestion(result["preview"]["suggestion_id"])
        if suggestion_row:
            suggestion_view = _suggestion_view(suggestion_row)
    reply_html = render_template(
        "chat_reply.html", reply=result["reply"], suggestion=suggestion_view, fallback=result["fallback"]
    )
    if suggestion_view:
        # The panel is the other surface showing this proposal; refresh it so
        # the badge and card appear the moment the reply does.
        reply_html += _render_suggestions_panel(oob=True)
    # No toast. Asking Tally something writes nothing the user cares about --
    # the reply appearing in the panel is the feedback, and "Done - change
    # saved." on a question told them their data had changed when it had not.
    # The apply route below is the one that changes something, and it still says
    # so.
    return make_response(reply_html, 200)


@bp.post("/chat/apply")
def chat_apply():
    try:
        fields = json.loads(request.form.get("fields") or "{}")
    except ValueError:
        raise ServiceError("fields must be JSON")
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
