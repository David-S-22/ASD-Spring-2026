"""Chat resolution and apply, shared by /api/chat(/apply) and /ui/chat(/apply).

send_message() only ever calls bills_db.create_chat_message - it never
touches bills, payments, or disputes directly. apply() is the only path
that writes those, always through the same CRUD calls a manual edit uses.
"""
import json
from datetime import date, timedelta

from sophia.backend import config
from sophia.backend.ai import chat_prompt, guard
from sophia.backend.ai.schemas import validate_chat_response
from sophia.backend.clients import bills_db, transactions
from sophia.backend.engine import BARELY_USING_THRESHOLD, money
from sophia.backend.engine.calendar import month_breakdown
from sophia.backend.engine.dates import expected_per_month
from sophia.backend.engine.projection import project
from sophia.backend.services import bills as bills_service
from sophia.backend.services import disputes as disputes_service
from sophia.backend.services import payments as payments_service
from sophia.backend.services.errors import NotFound, ServiceError

# The model is asked for the real column names, but a small model drifts, and
# it drifts predictably: it says "amount" in dollars where the column is
# amount_cents, and "next" where the column is next_billing_date. Those two are
# translated here rather than widened into the whitelist, so the whitelist keeps
# doing its job -- a genuinely invented field still fails loudly.
#
# Deliberately narrow. Mapping every plausible synonym would turn a strict
# allowlist into a guessing game, and a wrong guess writes bad data silently.
CHAT_FIELD_ALIASES = {
    "bill": {
        "amount": "amount_cents",
        "next": "next_billing_date",
        "next_date": "next_billing_date",
        "next_billing": "next_billing_date",
    },
    "payment": {"amount": "amount_cents"},
}

# Values the model states in dollars; stored in cents.
DOLLAR_VALUED_ALIASES = {"amount"}

BILL_FIELD_WHITELIST = {
    "bill": {
        "name", "merchant", "amount_cents", "cadence", "next_billing_date", "type",
        "payment_method", "end_date", "exclude_from_plan",
    },
    "payment": {"bill_id", "date", "amount_cents"},
    "dispute": {"bill_id", "reason", "status"},
}

# Keys the model may not send raw, even though the whitelist accepts them as
# alias *targets*. The prompt asks for dollars under "amount" and the one
# conversion lives in _normalise_chat_fields; a model that emits amount_cents
# itself is emitting a unit nothing verified ("amount_cents": 15 for a $15
# bill stores 15 cents, silently). Refusing the raw key makes that drift fail
# loudly instead.
RAW_KEY_BLOCKLIST = {"amount_cents"}

_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _count_word(n):
    return _COUNT_WORDS.get(n, str(n))


def _recent_history():
    rows = bills_db.list_chat_messages()
    return [{"role": r["role"], "content": r["content"]} for r in rows[-10:]]


def _answer_total():
    """Answer the "what do my bills add up to" question with both figures.

    There are two defensible totals and they do not match. The table header
    shows the ongoing monthly rate -- every bill scaled to a month -- while this
    answer is about the calendar month actually in view, where a five-Monday
    month or a bill that starts mid-month changes the number. Quoting only the
    second put "around $1,695" two inches from a header reading $1,731.95, and
    from the user's chair that is the app disagreeing with itself. Naming both,
    and what each measures, costs one clause.
    """
    today = config.DEMO_TODAY
    bills = [bills_db.row_to_bill(r) for r in bills_db.list_bills()]
    payments = [bills_db.row_to_payment(r) for r in bills_db.list_payments()]
    breakdown = month_breakdown(bills, payments, today.year, today.month, today)
    monthly_rate = sum(b.amount_cents * expected_per_month(b.cadence) for b in bills)
    return (
        f"{today.strftime('%B')} is set to cost around "
        f"{money.format_estimate_single(breakdown.total_high_cents)}. "
        f"Your ongoing monthly total across all bills is {money.format_actual(monthly_rate)}."
    )


def _answer_barely_using():
    """A subscription counts as barely used once it has been billed at least
    BARELY_USING_THRESHOLD times since confirmed_at (or created_at when confirmed_at
    is null) - it keeps charging even though the user hasn't re-confirmed they still
    want it. Transaction history for the merchant since that date is supporting
    evidence only, never a second threshold that could exclude a flagged subscription.
    """
    bill_rows = bills_db.list_bills()
    payment_rows = bills_db.list_payments()
    sentences = []
    for row in bill_rows:
        if row["type"] != "subscription":
            continue
        since = row.get("confirmed_at") or row.get("created_at")
        count = sum(1 for p in payment_rows if p["bill_id"] == row["id"] and (since is None or p["date"] >= since))
        if count < BARELY_USING_THRESHOLD:
            continue
        transaction_rows, _source = transactions.list_transactions(merchant=row["merchant"], since=since)
        amount = money.format_actual(row["amount_cents"])
        sentence = (
            f"{row['name']} has billed {_count_word(count)} times since you last "
            f"confirmed you're using it — worth a look at {amount}/month."
        )
        if not transaction_rows:
            sentence += " No recent activity for that merchant either."
        sentences.append(sentence)
    if not sentences:
        return "Everything looks actively used — nothing has billed repeatedly since you last confirmed it."
    return " ".join(sentences)


def _answer_upcoming():
    today = config.DEMO_TODAY
    bills = [bills_db.row_to_bill(r) for r in bills_db.list_bills()]
    window_end = today + timedelta(days=7)
    names = []
    for bill in bills:
        names.extend(occ.name for occ in project(bill, today, window_end))
    if not names:
        return "Nothing is due in the next 7 days."
    return f"Coming up this week: {', '.join(names)}."


def _resolve_question(question):
    if question == "total":
        return _answer_total()
    if question == "barely_using":
        return _answer_barely_using()
    if question == "upcoming":
        return _answer_upcoming()
    return None


def _build_preview(data):
    op, entity = data.get("op"), data.get("entity")
    if not op or not entity:
        return None
    if op == "read":
        # A read is a question, not a change; there is nothing to apply and a
        # Confirm button for it could only end in "unsupported op 'read'".
        return None
    return {"op": op, "entity": entity, "id": data.get("id"), "fields": data.get("fields")}


# What a bill create must carry before it is worth proposing. merchant is
# excluded: _normalise_chat_fields falls back to the name, honestly.
CREATE_REQUIRED = ["name", "amount_cents", "cadence", "next_billing_date", "type"]

MISSING_FIELD_QUESTIONS = {
    "name": "what the bill is called",
    "amount_cents": "the amount (in dollars)",
    "cadence": "how often it bills (weekly, fortnightly or monthly)",
    "next_billing_date": "the next billing date",
    "type": "whether it's a bill or a subscription",
}


def _vet_proposal(preview):
    """Vet a proposal *before* it reaches the user.

    Returns (canonical_fields, None) when the proposal is appliable — fields
    normalised onto real columns, dollars already in cents — or (None, reply)
    when it is not: the reply asks for what's missing instead of presenting
    an approve button that can only fail. This is the deterministic backstop
    beneath the prompt's "ask, don't invent" instruction: even if the model
    ignores it and emits an under-specified create, no appliable proposal
    exists until the user has supplied the details.
    """
    try:
        fields = _normalise_chat_fields(preview["entity"], preview["op"], preview["fields"] or {})
        allowed = BILL_FIELD_WHITELIST[preview["entity"]]
        for key in fields:
            if key not in allowed:
                raise ServiceError(f"field '{key}' cannot be set via chat")
        for key in ("next_billing_date", "end_date", "date"):
            if fields.get(key):
                date.fromisoformat(str(fields[key]))
    except ServiceError as error:
        return None, f"Tally couldn't turn that into a change ({error.message}) — try rephrasing."
    except ValueError:
        return None, "Tally needs dates as a real calendar date (like 5 September) — try rephrasing."
    if preview["entity"] == "bill" and preview["op"] == "create":
        missing = [f for f in CREATE_REQUIRED if not fields.get(f)]
        if missing:
            wants = ", ".join(MISSING_FIELD_QUESTIONS[f] for f in missing)
            return None, f"Happy to add that — I just need {wants}. I won't guess details you haven't given me."
    return fields, None


def send_message(message):
    if not message:
        raise ServiceError("message is required")
    history = _recent_history()
    bills_db.create_chat_message({"role": "user", "content": message})

    bills = bills_db.list_bills()
    data = guard.run(
        config.CHAT_MODEL,
        lambda error: chat_prompt.build(message, history, bills=bills, error=error),
        validate_chat_response,
        chat_prompt.FALLBACK,
    )

    reply = _resolve_question(data.get("question")) or data.get("say", "")
    preview = _build_preview(data)
    canonical_fields = None
    if preview:
        canonical_fields, reply_override = _vet_proposal(preview)
        if reply_override:
            reply = reply_override
            preview = None

    assistant_row = bills_db.create_chat_message(
        {"role": "assistant", "content": reply, "op_json": json.dumps(preview) if preview else None}
    )
    if preview:
        preview["message_id"] = assistant_row["id"]
        # The proposal becomes a pending suggestion the moment it exists, so
        # the same row backs the chat card and the Suggestions panel, and
        # approving in either place resolves both.
        suggestion = bills_db.create_suggestion(
            {
                "op": preview["op"],
                "entity": preview["entity"],
                "entity_id": preview.get("id"),
                "payload_json": json.dumps(canonical_fields or {}),
                "message_id": assistant_row["id"],
            }
        )
        preview["suggestion_id"] = suggestion["id"]
    return {"reply": reply, "op": preview["op"] if preview else None, "preview": preview, "fallback": data.get("fallback", False)}


def _normalise_chat_fields(entity, op, fields):
    """Translate the model's field names onto the real columns.

    Runs before the whitelist check, so an alias is accepted and anything still
    unrecognised afterwards is rejected exactly as before.
    """
    aliases = CHAT_FIELD_ALIASES.get(entity, {})
    out = {}
    for key, value in fields.items():
        if key in RAW_KEY_BLOCKLIST:
            raise ServiceError(f"field '{key}' cannot be set via chat — state the amount in dollars")
        target = aliases.get(key, key)
        if key in DOLLAR_VALUED_ALIASES:
            try:
                value = money.parse_dollars_to_cents(value)
            except ValueError:
                raise ServiceError(f"'{key}' must be an amount, got {value!r}")
        if target in out and out[target] != value:
            raise ServiceError(f"conflicting values for '{target}'")
        out[target] = value

    # A bill needs a merchant and the request rarely names one separately --
    # "add Disney Plus" gives the name and nothing else. Falling back to the
    # name keeps the row valid and honest: it says what the user actually told
    # us rather than inventing a trading entity.
    if entity == "bill" and op == "create" and not out.get("merchant") and out.get("name"):
        out["merchant"] = out["name"]
    return out


def _execute(op, entity, entity_id, clean_fields):
    """Perform an already-normalised, whitelisted change.

    Bill and payment writes go through the services layer — the same
    validation and status-sync a manual edit gets — never the raw DB client.
    The DB API checks enums and integer types but not date *format*: a chat
    update that stored next_billing_date="early September" used to 500 every
    bills read from then on. services/bills._clean_payload is what refuses it.
    """
    if entity == "bill" and op == "update":
        return bills_service.update_bill(entity_id, clean_fields)
    if entity == "bill" and op == "create":
        return bills_service.create_bill({**clean_fields, "source": "chat"})
    if entity == "bill" and op == "delete":
        return bills_service.delete_bill(entity_id)
    if entity == "payment" and op == "create":
        return payments_service.create_payment(clean_fields)
    if entity == "payment" and op == "delete":
        return payments_service.delete_payment(entity_id)
    if entity == "dispute" and op == "update":
        return bills_db.update_dispute(entity_id, clean_fields)
    if entity == "dispute" and op == "create":
        bill_row = bills_db.get_bill(clean_fields.get("bill_id"))
        if bill_row is None:
            raise NotFound("bill not found")
        reason = clean_fields.get("reason", "")
        result = bills_db.create_dispute({"bill_id": bill_row["id"], "reason": reason})
        draft = disputes_service.draft_for_bill(bill_row, reason)
        bills_db.create_dispute_draft(
            result["id"],
            {"letter_text": draft["letter_text"], "steps_json": {"steps": draft["steps"], "escalation": draft["escalation"]}},
        )
        result["draft"] = draft
        return result
    raise ServiceError(f"unsupported op '{op}' for entity '{entity}'")


def _bill_name(entity_id):
    row = bills_db.get_bill(entity_id) if entity_id else None
    return row["name"] if row else None


def _change_summary(op, entity, entity_id, fields, bill_name=None):
    """One honest sentence describing a change, for the chat transcript the
    model reads back. Names beat ids: 'deleted bill 4' tells the model less
    than 'deleted Netflix'."""
    label = f"{entity} {entity_id}" if entity_id else entity
    if entity == "bill" and bill_name:
        label = f"bill '{bill_name}'"
    elif entity == "bill" and fields.get("name"):
        label = f"bill '{fields['name']}'"
    if op == "create":
        detail = ", ".join(f"{k}={v}" for k, v in fields.items() if k != "name")
        return f"added {label}" + (f" ({detail})" if detail else "")
    if op == "update":
        detail = ", ".join(f"{k} → {v}" for k, v in fields.items())
        return f"updated {label}" + (f" ({detail})" if detail else "")
    return f"deleted {label}"


def _record_outcome(content, applied=False):
    bills_db.create_chat_message({"role": "assistant", "content": content, "applied": applied})


def apply(op, entity, entity_id, fields, message_id=None):
    """Direct apply for /api/chat/apply and /ui/chat/apply (raw model-shaped
    fields, dollars under 'amount'). The suggestions flow uses approve_suggestion
    below; both record an honest outcome the model sees on its next turn."""
    fields = fields or {}
    if entity not in BILL_FIELD_WHITELIST:
        raise ServiceError("unknown entity")
    fields = _normalise_chat_fields(entity, op, fields)
    allowed = BILL_FIELD_WHITELIST[entity]
    for key in fields:
        if key not in allowed:
            raise ServiceError(f"field '{key}' cannot be set via chat")
    clean_fields = dict(fields)

    bill_name = _bill_name(entity_id) if entity == "bill" and op in ("update", "delete") else None
    try:
        result = _execute(op, entity, entity_id, clean_fields)
    except ServiceError as error:
        # A failed change used to vanish from the transcript: the user saw an
        # error fragment, the model saw nothing, and its next turn happily
        # repeated that the change was made. The failure is now on the record.
        _record_outcome(f"[change failed: {error.message} — nothing was changed]")
        raise

    if message_id:
        bills_db.update_chat_message(message_id, {"applied": 1})
    summary = _change_summary(op, entity, entity_id, clean_fields, bill_name)
    _record_outcome(f"[change applied: {summary}]", applied=True)
    return result


def approve_suggestion(suggestion_id):
    """Apply a pending suggestion. Claims the row first (an atomic
    pending→applied transition in the DB), so two racing approves — or a
    double-clicked button — cannot both execute the change."""
    row = bills_db.get_suggestion(suggestion_id)
    if row is None:
        raise NotFound("suggestion not found")
    bills_db.update_suggestion(suggestion_id, {"status": "applied"})

    fields = json.loads(row["payload_json"]) if row["payload_json"] else {}
    bill_name = _bill_name(row["entity_id"]) if row["entity"] == "bill" and row["op"] in ("update", "delete") else None
    try:
        result = _execute(row["op"], row["entity"], row["entity_id"], fields)
    except ServiceError as error:
        bills_db.update_suggestion(suggestion_id, {"status": "failed", "error": error.message})
        _record_outcome(
            f"[suggestion #{suggestion_id} FAILED to apply: {error.message} — nothing was changed]"
        )
        raise
    if row["message_id"]:
        bills_db.update_chat_message(row["message_id"], {"applied": 1})
    summary = _change_summary(row["op"], row["entity"], row["entity_id"], fields, bill_name)
    _record_outcome(f"[suggestion #{suggestion_id} approved and applied: {summary}]", applied=True)
    return result


def reject_suggestion(suggestion_id):
    """Reject a pending suggestion (or dismiss a failed one). Recorded in the
    transcript so the model's next turn knows the change was NOT made."""
    row = bills_db.get_suggestion(suggestion_id)
    if row is None:
        raise NotFound("suggestion not found")
    updated = bills_db.update_suggestion(suggestion_id, {"status": "rejected"})
    fields = json.loads(row["payload_json"]) if row["payload_json"] else {}
    bill_name = _bill_name(row["entity_id"]) if row["entity"] == "bill" else None
    summary = _change_summary(row["op"], row["entity"], row["entity_id"], fields, bill_name)
    _record_outcome(f"[suggestion #{suggestion_id} rejected by the user — NOT applied: {summary}]")
    return updated
