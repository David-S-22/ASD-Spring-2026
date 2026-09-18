from __future__ import annotations


def validate_chat_response(data):
    if not isinstance(data, dict):
        return "response must be a JSON object"
    mode = data.get("mode")
    if mode not in {"advice", "clarify", "proposal"}:
        return 'mode must be one of "advice", "clarify", or "proposal"'
    say = data.get("say")
    if not isinstance(say, str) or not say.strip() or len(say) > 500:
        return "say must be a non-empty string up to 500 characters"
    question = data.get("question")
    if question is not None and not isinstance(question, str):
        return "question must be a string when present"
    proposal = data.get("proposal")
    if mode == "proposal":
        if not isinstance(proposal, dict):
            return "proposal mode requires a proposal object"
        proposal_type = proposal.get("proposal_type")
        if not isinstance(proposal_type, str) or not proposal_type.strip():
            return "proposal_type must be a non-empty string"
        operations = proposal.get("operations")
        if not isinstance(operations, list) or not operations:
            return "proposal.operations must be a non-empty list"
        for operation in operations:
            if not isinstance(operation, dict):
                return "proposal operations must be objects"
            if operation.get("action") != "update_budget_line":
                return "proposal action is not supported"
            line_id = operation.get("budget_line_id")
            if isinstance(line_id, bool) or not isinstance(line_id, int):
                return "proposal budget_line_id must be an integer"
            fields = operation.get("fields")
            if not isinstance(fields, dict) or not fields:
                return "proposal fields must be a non-empty object"
            if not any(key in {"warn_at", "hard_cap"} for key in fields):
                return "proposal fields must include warn_at or hard_cap"
    elif proposal is not None and not isinstance(proposal, dict):
        return "proposal must be null or an object"
    return None
