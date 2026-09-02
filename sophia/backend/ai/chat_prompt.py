"""Prompt and fallback for the Ask Tally chat assistant.

Kept short on purpose: accuracy degrades with long context, so the bills
list is compact and there are only as many few-shot examples as needed to
pin down the op grammar.
"""

RESPONSE_SHAPE = (
    'Respond with JSON only, no prose, exactly these keys: {"op": "create"|"read"|"update"|"delete"|null, '
    '"entity": "bill"|"payment"|"dispute"|null, "id": <int or null>, "fields": <object or null>, '
    '"question": "total"|"barely_using"|"upcoming"|"none", "say": "<string, max 300 chars>"}. '
    'Use "question" for a question about the bills, "op"/"entity"/"fields" for a change the user wants made, '
    "and null op when nothing needs to change."
)

# Amount is asked for in dollars, not cents, and that is deliberate. The column
# is amount_cents, but a model told to emit cents sometimes emits dollars into
# it -- "amount_cents": 15 for a $15 bill stores fifteen cents and nothing
# complains. Dollars in, converted in one place on the way through.
BILL_FIELDS = (
    'To add a bill, "fields" needs: "name", "merchant", "amount" (in dollars), '
    '"cadence" ("weekly"|"fortnightly"|"monthly"), "next_billing_date" (YYYY-MM-DD), '
    '"type" ("bill"|"subscription"), and "payment_method" when the user says how it is paid. '
    "Use the merchant the user names, or repeat the name when they do not name one."
)

FEW_SHOT = [
    ("What do my bills add up to?", '{"op": null, "entity": null, "id": null, "fields": null, "question": "total", "say": "Here is this month\'s total."}'),
    ("Which subscriptions am I barely using?", '{"op": null, "entity": null, "id": null, "fields": null, "question": "barely_using", "say": "Checking which subscriptions keep billing without a recent confirm."}'),
    ("I cancelled Spotify from September — remove the future payments", '{"op": "update", "entity": "bill", "id": 3, "fields": {"end_date": "2026-09-16"}, "question": "none", "say": "Marking Spotify as ending after 16 Sep."}'),
    ("Draft a note to dispute my GymCo charge", '{"op": "create", "entity": "dispute", "id": null, "fields": {"bill_id": 6, "reason": "Charged after I cancelled"}, "question": "none", "say": "Drafting a dispute letter for GymCo."}'),
    ("Add Disney Plus, $15 a month, first charge 5 September, paid by card", '{"op": "create", "entity": "bill", "id": null, "fields": {"name": "Disney Plus", "merchant": "Disney Plus", "amount": 15.0, "cadence": "monthly", "next_billing_date": "2026-09-05", "type": "subscription", "payment_method": "card"}, "question": "none", "say": "Adding Disney Plus at $15 a month from 5 Sep."}'),
]

FALLBACK = {
    "op": None,
    "entity": None,
    "id": None,
    "fields": None,
    "question": "none",
    "say": "Tally couldn't understand that — try rephrasing.",
}


def _bill_line(bill_row):
    return (
        f"{bill_row['id']} {bill_row['name']} ${bill_row['amount_cents'] / 100:.2f} "
        f"{bill_row['cadence']} next={bill_row['next_billing_date']} {bill_row['type']}"
    )


def build(message, history, bills=None, error=None):
    system_parts = [f"You are Tally, a bills and subscriptions assistant. {RESPONSE_SHAPE}", BILL_FIELDS]
    if bills:
        system_parts.append("Bills (id name amount cadence next=date type):\n" + "\n".join(_bill_line(b) for b in bills))
    messages = [{"role": "system", "content": "\n".join(system_parts)}]
    for user_text, assistant_json in FEW_SHOT:
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_json})
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})
    if error:
        messages.append({"role": "user", "content": f"Your last response was invalid: {error}. Reply again, JSON only."})
    return messages
