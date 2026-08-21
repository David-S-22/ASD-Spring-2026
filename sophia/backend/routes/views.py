"""JSON API routes for the timeline and calendar views."""
from datetime import timedelta

from flask import Blueprint, jsonify, request

from sophia.backend import config
from sophia.backend.clients import bills_db
from sophia.backend.engine import money
from sophia.backend.engine.calendar import month_breakdown
from sophia.backend.engine.projection import timeline as project_timeline

bp = Blueprint("views", __name__, url_prefix="/api")


def _load_bills_and_payments():
    bills = [bills_db.row_to_bill(r) for r in bills_db.list_bills()]
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_payments()]
    return bills, payments


def _display_amount(occ):
    return money.format_actual(occ.amount_cents) if occ.kind == "actual" else money.format_estimate_single(occ.amount_cents)


@bp.get("/timeline")
def timeline():
    today = config.DEMO_TODAY
    days = int(request.args.get("days", 30))
    bills, payments = _load_bills_and_payments()
    merchant_by_id = {bill.id: bill.merchant for bill in bills}
    occurrences = project_timeline(bills, payments, today, days)
    clamped_days = max(30, min(180, days))
    window_end = today + timedelta(days=clamped_days)
    items = [
        {
            "date": occ.date.isoformat(),
            "bill_id": occ.bill_id,
            "name": occ.name,
            "merchant": merchant_by_id.get(occ.bill_id, ""),
            "amount": money.format_actual(occ.amount_cents),
            "amount_cents": occ.amount_cents,
            "display_amount": _display_amount(occ),
            "kind": occ.kind,
            "within_30_days": today <= occ.date < min(window_end, today + timedelta(days=30)),
        }
        for occ in occurrences
    ]
    return jsonify({"today": today.isoformat(), "days": clamped_days, "items": items})


def _breakdown_payload(breakdown):
    return {
        "year": breakdown.year,
        "month": breakdown.month,
        "usual_low_cents": breakdown.usual_low_cents,
        "usual_high_cents": breakdown.usual_high_cents,
        "usual_low": money.format_actual(breakdown.usual_low_cents),
        "usual_high": money.format_actual(breakdown.usual_high_cents),
        "extras": [
            {"bill_id": e.bill_id, "name": e.name, "reason": e.reason, "amount_cents": e.amount_cents, "count": e.count}
            for e in breakdown.extras
        ],
        "ends": [
            {"bill_id": e.bill_id, "name": e.name, "reason": e.reason, "amount_cents": e.amount_cents, "count": e.count}
            for e in breakdown.ends
        ],
        "total_high_cents": breakdown.total_high_cents,
        "total_high": money.format_actual(breakdown.total_high_cents),
    }


@bp.get("/calendar/<year_month>")
def calendar_month(year_month):
    year_str, month_str = year_month.split("-")
    bills, payments = _load_bills_and_payments()
    breakdown = month_breakdown(bills, payments, int(year_str), int(month_str), config.DEMO_TODAY)
    return jsonify(_breakdown_payload(breakdown))


@bp.get("/calendar")
def calendar_range():
    from_param = request.args.get("from")
    months = int(request.args.get("months", 6))
    if from_param:
        year_str, month_str = from_param.split("-")
        year, month = int(year_str), int(month_str)
    else:
        year, month = config.DEMO_TODAY.year, config.DEMO_TODAY.month
    bills, payments = _load_bills_and_payments()
    results = []
    for offset in range(months):
        month_index = month - 1 + offset
        target_year = year + month_index // 12
        target_month = month_index % 12 + 1
        breakdown = month_breakdown(bills, payments, target_year, target_month, config.DEMO_TODAY)
        results.append(_breakdown_payload(breakdown))
    return jsonify({"months": results})


@bp.get("/upcoming")
def upcoming():
    today = config.DEMO_TODAY
    days = int(request.args.get("days", 90))
    bills, payments = _load_bills_and_payments()
    breakdown = month_breakdown(bills, payments, today.year, today.month, today)
    occurrences = project_timeline(bills, payments, today, days)
    items = [
        {"date": occ.date.isoformat(), "bill_id": occ.bill_id, "name": occ.name, "amount_cents": occ.amount_cents, "kind": occ.kind}
        for occ in occurrences
    ]
    return jsonify(
        {
            "today": today.isoformat(),
            "monthly_committed_cents": breakdown.total_high_cents,
            "items": items,
        }
    )
