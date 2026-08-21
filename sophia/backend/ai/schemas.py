"""Hand-written validators for the two AI response shapes. No jsonschema/pydantic."""


def validate_dispute_draft(data):
    """Return an error message string, or None when data satisfies the dispute-draft shape."""
    if not isinstance(data, dict):
        return "response must be a JSON object"
    letter_text = data.get("letter_text")
    if not isinstance(letter_text, str) or not (80 <= len(letter_text) <= 2500):
        return "letter_text must be a string of 80-2500 characters"
    steps = data.get("steps")
    if not isinstance(steps, list) or not (2 <= len(steps) <= 8) or not all(isinstance(s, str) for s in steps):
        return "steps must be a list of 2-8 strings"
    escalation = data.get("escalation")
    if not isinstance(escalation, list) or not (1 <= len(escalation) <= 5) or not all(
        isinstance(s, str) for s in escalation
    ):
        return "escalation must be a list of 1-5 strings"
    note = data.get("payment_method_note")
    if note is not None and not isinstance(note, str):
        return "payment_method_note must be a string when present"
    return None


CHAT_OPS = {"create", "read", "update", "delete"}
CHAT_ENTITIES = {"bill", "payment", "dispute"}
CHAT_QUESTIONS = {"total", "barely_using", "upcoming", "none"}


def validate_chat_response(data):
    """Return an error message string, or None when data satisfies the chat-response shape."""
    if not isinstance(data, dict):
        return "response must be a JSON object"
    op = data.get("op")
    if op is not None and op not in CHAT_OPS:
        return f"op must be one of {sorted(CHAT_OPS)}"
    entity = data.get("entity")
    if entity is not None and entity not in CHAT_ENTITIES:
        return f"entity must be one of {sorted(CHAT_ENTITIES)}"
    if "id" in data and data["id"] is not None and not isinstance(data["id"], int):
        return "id must be an integer when present"
    if "fields" in data and data["fields"] is not None and not isinstance(data["fields"], dict):
        return "fields must be an object when present"
    question = data.get("question")
    if question is not None and question not in CHAT_QUESTIONS:
        return f"question must be one of {sorted(CHAT_QUESTIONS)}"
    say = data.get("say")
    if not isinstance(say, str) or len(say) > 300:
        return "say must be a string of at most 300 characters"
    return None
