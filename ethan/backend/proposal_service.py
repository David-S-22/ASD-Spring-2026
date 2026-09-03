from __future__ import annotations

from . import db_api
from .db_api import ServiceError


def _proposal_id_text(proposal_id: object) -> str:
    if isinstance(proposal_id, bool) or not isinstance(proposal_id, (int, str)):
        raise ServiceError("proposal_id must be an integer", 422, "invalid_field")
    value = str(proposal_id).strip()
    if not value.isdigit() or int(value) < 1:
        raise ServiceError("proposal_id must be an integer", 422, "invalid_field")
    return value


def _fields_payload(fields: object) -> dict:
    if not isinstance(fields, dict):
        raise ServiceError("proposal operation fields must be a JSON object", 422, "invalid_field")
    allowed_fields = {"warn_at", "hard_cap"}
    payload = {key: value for key, value in fields.items() if key in allowed_fields}
    if not payload:
        raise ServiceError("proposal operation must include warn_at or hard_cap", 422, "invalid_field")
    return payload


def _apply_update_budget_line(proposal: dict, operation: dict) -> dict:
    line_id = operation.get("budget_line_id")
    if isinstance(line_id, bool) or not isinstance(line_id, int):
        raise ServiceError("proposal operation budget_line_id must be an integer", 422, "invalid_field")
    budget_line = db_api.get_budget_line(str(line_id))
    if budget_line.get("budget_id") != proposal.get("budget_id"):
        raise ServiceError("proposal budget line does not belong to this budget", 409, "proposal_conflict")
    return db_api.update_budget_line(str(line_id), _fields_payload(operation.get("fields")))


def apply(proposal_id: object) -> dict:
    proposal = db_api.get_coach_proposal(_proposal_id_text(proposal_id))
    if proposal.get("status") != "proposed":
        raise ServiceError("proposal has already been decided", 409, "proposal_already_decided")
    proposal_json = proposal.get("proposal_json")
    if not isinstance(proposal_json, dict):
        raise ServiceError("proposal_json must be a JSON object", 422, "invalid_field")
    operations = proposal_json.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ServiceError("proposal must contain at least one operation", 422, "invalid_field")

    applied = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ServiceError("proposal operations must be JSON objects", 422, "invalid_field")
        action = operation.get("action")
        if action != "update_budget_line":
            raise ServiceError("proposal action is not supported", 422, "invalid_field")
        applied.append(_apply_update_budget_line(proposal, operation))

    updated_proposal = db_api.update_coach_proposal(str(proposal["id"]), {"status": "accepted"})
    return {"proposal": updated_proposal, "applied": applied}
