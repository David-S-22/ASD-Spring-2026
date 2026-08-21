"""Prompt and fallback for drafting a bill dispute letter. First-cut copy, polished later."""

ESCALATION_DEFAULT = ["Merchant support", "Your bank's dispute team", "Australian Financial Complaints Authority (AFCA)"]

RESPONSE_SHAPE = (
    'Respond with JSON only, no prose: {"letter_text": str, "steps": [str, ...], '
    '"escalation": [str, ...], "payment_method_note": str or null}. letter_text must be '
    "80-2500 characters, steps 2-8 items, escalation 1-5 items."
)


def build(bill, reason, feedback=None, error=None):
    system = (
        "You write short, factual bill dispute letters and a step-by-step checklist for an "
        f"Australian consumer. {RESPONSE_SHAPE}"
    )
    user = (
        f"Bill: {bill.name} ({bill.merchant}), amount ${bill.amount_cents / 100:.2f}, "
        f"cadence: {bill.cadence}, payment method: {bill.payment_method or 'unknown'}. "
        f"Reason for dispute: {reason}."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if feedback:
        messages.append({"role": "user", "content": f"Revise the letter with this feedback: {feedback}"})
    if error:
        messages.append({"role": "user", "content": f"Your last response was invalid: {error}. Try again, JSON only."})
    return messages


def enforce_payment_method_step(data, bill):
    """Append the code-enforced direct-debit or card step when the AI response omits it."""
    steps = list(data.get("steps", []))
    lowered = " ".join(steps).lower()
    if bill.payment_method == "direct_debit" and "authority" not in lowered and "direct debit" not in lowered:
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
