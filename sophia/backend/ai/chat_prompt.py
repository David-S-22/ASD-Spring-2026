"""Prompt and fallback for the Ask Tally chat assistant. First-cut copy, polished later."""

RESPONSE_SHAPE = (
    'Respond with JSON only, no prose: {"op": "create"|"read"|"update"|"delete"|null, '
    '"entity": "bill"|"payment"|"dispute"|null, "id": int or null, "fields": object or null, '
    '"question": "total"|"barely_using"|"upcoming"|"none"|null, "say": str}. say must be at most 300 characters.'
)

FALLBACK = {
    "op": None,
    "entity": None,
    "id": None,
    "fields": None,
    "question": "none",
    "say": "Tally couldn't understand that — try rephrasing.",
}


def build(message, history, error=None):
    system = f"You are Tally, a bills and subscriptions assistant. {RESPONSE_SHAPE}"
    messages = [{"role": "system", "content": system}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})
    if error:
        messages.append({"role": "user", "content": f"Your last response was invalid: {error}. Try again, JSON only."})
    return messages
