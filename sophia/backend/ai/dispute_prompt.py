"""Prompt and fallback for drafting a bill dispute letter."""

ESCALATION_DEFAULT = ["Merchant support", "Your bank's dispute team", "Australian Financial Complaints Authority (AFCA)"]

RESPONSE_SHAPE = (
    "Respond with JSON only, no prose, no markdown fences, exactly these keys: "
    '{"letter_text": "<80-2500 chars>", "steps": ["<2-8 short imperative steps>"], '
    '"escalation": ["<1-5 escalation contacts, ordered easiest first>"], '
    '"payment_method_note": "<string, or null>"}.'
)

SYSTEM = (
    "You write short, factual bill dispute letters and a step-by-step checklist for an "
    "Australian consumer. Never invent account numbers, reference numbers, phone numbers, "
    "emails, or dates that were not given to you. escalation entries are channel names only, "
    "e.g. Merchant support or Your bank's dispute team, never invented contact details. "
    "Never include legal threats. Never claim to send anything yourself - this letter is a "
    f"draft the user will send themselves. {RESPONSE_SHAPE}"
)


def _payment_lines(payments):
    if not payments:
        return "No payment history on file."
    lines = [f"{p.date.isoformat()}: ${p.amount_cents / 100:.2f}" for p in payments[-6:]]
    return "Last payments: " + "; ".join(lines)


def build(bill, reason, payments=None, previous_letter=None, edited_letter=None, feedback=None, error=None):
    user_lines = [
        f"Bill: {bill.name} ({bill.merchant}), amount ${bill.amount_cents / 100:.2f}, cadence: {bill.cadence}.",
        f"Payment method: {bill.payment_method or 'not recorded'}.",
        _payment_lines(payments),
        f"Reason for dispute: {reason}.",
    ]
    if previous_letter:
        user_lines.append(f"Previous draft letter: {previous_letter}")
    if edited_letter:
        user_lines.append(f"The user edited the letter to: {edited_letter}")
    if feedback:
        user_lines.append(f"Revise using this feedback: {feedback}")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(user_lines)}]
    if error:
        messages.append({"role": "user", "content": f"Your last response was invalid: {error}. Reply again, JSON only."})
    return messages


def _mentions_authority_removal(steps):
    """True if a step already covers removing the direct-debit authority.

    Checks each step on its own (not the joined blob) so "Australian
    Financial Complaints Authority" in an escalation-flavoured step never
    false-positives just because it contains the word "authority".
    """
    for step in steps:
        lowered = step.lower()
        if "direct debit" in lowered:
            return True
        if "authority" in lowered and "financial complaints authority" not in lowered:
            return True
    return False


def enforce_payment_method_step(data, bill):
    """Append the code-enforced direct-debit or card step when the AI response omits it."""
    steps = list(data.get("steps", []))
    if bill.payment_method == "direct_debit" and not _mentions_authority_removal(steps):
        steps.append(
            "Ask the merchant — or your bank — to remove the direct-debit authority. "
            "Cancelling the subscription alone does not stop direct-debit payments."
        )
    elif bill.payment_method == "card" and not any(
        "cancel" in s.lower() and "account page" in s.lower() for s in steps
    ):
        steps.append("Cancel the subscription from the app's account page to stop future charges.")
    data["steps"] = steps
    return data


def fallback_draft(bill, reason):
    letter_text = (
        f"I'm writing to dispute a charge from {bill.merchant} for {bill.name}. "
        f"Reason for the dispute: {reason}. Please review this charge against my billing "
        "history and let me know how it will be resolved. I'm happy to provide further "
        "detail if needed."
    )
    steps = [
        "Check your billing history in the merchant's app or website for this charge.",
        "Contact the merchant's support team in writing and describe the discrepancy.",
        "Keep a copy of your correspondence in case you need to escalate.",
    ]
    data = {
        "letter_text": letter_text,
        "steps": steps,
        "escalation": list(ESCALATION_DEFAULT),
        "payment_method_note": None,
    }
    return enforce_payment_method_step(data, bill)
