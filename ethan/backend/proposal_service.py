from __future__ import annotations

from . import db_api, summary_service
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


def _summary_snapshot(summary: dict, proposal: dict) -> dict:
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    lines = summary.get("budget_lines") if isinstance(summary.get("budget_lines"), list) else []
    return {
        "budget_id": proposal.get("budget_id"),
        "month": summary.get("budget", {}).get("month") if isinstance(summary.get("budget"), dict) else None,
        "budget_line_count": len([line for line in lines if isinstance(line, dict)]),
        "actual_spend_total": totals.get("actual_spend_total"),
        "projected_high_total": totals.get("projected_high_total"),
        "remaining_income_high": totals.get("remaining_income_high"),
    }


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
    before_summary = summary_service.build_budget_summary(str(proposal["budget_id"]))

    applied = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ServiceError("proposal operations must be JSON objects", 422, "invalid_field")
        action = operation.get("action")
        if action != "update_budget_line":
            raise ServiceError("proposal action is not supported", 422, "invalid_field")
        applied.append(_apply_update_budget_line(proposal, operation))

    updated_proposal = db_api.update_coach_proposal(str(proposal["id"]), {"status": "accepted"})
    after_summary = summary_service.build_budget_summary(str(proposal["budget_id"]))
    return {
        "proposal": updated_proposal,
        "applied": applied,
        "stage_trace": ["observe", "plan", "act", "observe", "adapt"],
        "agentic_workflow": {
            "observe_before": _summary_snapshot(before_summary, proposal),
            "plan": {
                "proposal_id": proposal.get("id"),
                "budget_id": proposal.get("budget_id"),
                "operation_count": len(operations),
                "supported_actions": ["update_budget_line"],
            },
            "act": {
                "applied_operation_count": len(applied),
                "applied_budget_line_ids": [
                    item.get("id")
                    for item in applied
                    if isinstance(item, dict) and isinstance(item.get("id"), int)
                ],
            },
            "observe_after": _summary_snapshot(after_summary, proposal),
            "adapt": {
                "proposal_status": updated_proposal.get("status"),
                "human_confirmation_required": True,
            },
        },
    }
