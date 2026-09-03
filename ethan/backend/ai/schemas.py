from __future__ import annotations


CHAT_MODES = {"advice", "clarify", "proposal"}


def _validate_proposal(data: object) -> str | None:
    if not isinstance(data, dict):
        return "proposal must be a JSON object"
    proposal_type = data.get("proposal_type")
    if not isinstance(proposal_type, str) or not proposal_type.strip():
        return "proposal_type must be a non-empty string"
    operations = data.get("operations")
    if not isinstance(operations, list) or not operations:
        return "proposal operations must be a non-empty list"
    for operation in operations:
        if not isinstance(operation, dict):
            return "proposal operations must be JSON objects"
        if operation.get("action") != "update_budget_line":
            return "proposal action must be update_budget_line"
        line_id = operation.get("budget_line_id")
        if isinstance(line_id, bool) or not isinstance(line_id, int):
            return "proposal budget_line_id must be an integer"
        fields = operation.get("fields")
        if not isinstance(fields, dict):
            return "proposal fields must be a JSON object"
        allowed_fields = {"warn_at", "hard_cap"}
        if not any(field in fields for field in allowed_fields):
            return "proposal fields must include warn_at or hard_cap"
        for field_name, field_value in fields.items():
            if field_name not in allowed_fields:
                return "proposal fields may only include warn_at or hard_cap"
            if isinstance(field_value, bool) or not isinstance(field_value, int):
                return "proposal field values must be integers"
        warn_at = fields.get("warn_at")
        hard_cap = fields.get("hard_cap")
        if isinstance(warn_at, int) and isinstance(hard_cap, int) and warn_at > hard_cap:
            return "proposal warn_at must be less than or equal to hard_cap"
    return None


def validate_chat_response(data: object) -> str | None:
    if not isinstance(data, dict):
        return "response must be a JSON object"
    mode = data.get("mode")
    if mode not in CHAT_MODES:
        return f"mode must be one of {sorted(CHAT_MODES)}"
    say = data.get("say")
    if not isinstance(say, str) or not say.strip() or len(say) > 500:
        return "say must be a non-empty string of at most 500 characters"
    question = data.get("question")
    if question is not None and not isinstance(question, str):
        return "question must be a string when present"
    proposal = data.get("proposal")
    if mode == "proposal":
        validation_error = _validate_proposal(proposal)
        if validation_error is not None:
            return validation_error
    elif proposal is not None:
        return "proposal must be null unless mode is proposal"
    return None
