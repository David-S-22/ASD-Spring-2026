"""Coordinate the transaction planning and confirmation workflow."""

import re
from copy import deepcopy
from threading import Lock
from time import monotonic
from uuid import uuid4

from .. import config
from . import chat_service, ollama_service
from .agent_cycle import SAFE_FAILURE, run_cycle


_REQUESTS = {}
_REQUEST_LOCK = Lock()
_REPLANABLE_CODES = {
    "category_mismatch",
    "invalid_amount",
    "invalid_filter",
    "unsupported_fields",
}


def orchestrate_transaction_request(message, db_url):
    message = chat_service.validate_message(message)
    raw_categories = chat_service.database_request(
        "get",
        f"{db_url}/categories",
        list,
    )
    categories, names, ids = chat_service.build_category_lookup(raw_categories)
    request_id = str(uuid4())
    context = {
        "message": message,
        "db_url": db_url,
        "categories": categories,
        "category_names": names,
        "category_ids": ids,
        "phase": "initial",
    }
    cycle_result = run_cycle(
        context,
        plan=plan_transaction,
        act=act_on_plan,
        observe=observe_action,
        adapt=adapt_to_observation,
        max_iterations=config.AGENT_MAX_ITERATIONS,
    )
    raise_cycle_error(cycle_result)
    response = deepcopy(cycle_result.get("result") or failed_response())
    action = last_cycle_value(cycle_result, "action")

    category_selection = response.get("category_selection")
    if (
        category_selection is not None
        and category_selection.get("requires_user_response")
    ):
        register_category_request(
            request_id,
            action["pending_category"],
        )
    if response.get("preview") is not None:
        response["preview"]["request_id"] = request_id
        register_initial_preview(request_id, response["preview"], message)

    return attach_agent(response, request_id, cycle_result)


def run_category_selection(payload, db_url):
    if not isinstance(payload, dict):
        raise chat_service.ChatError(
            "category selection must be a JSON object",
            "invalid_category_selection",
            400,
        )
    unknown = sorted(
        set(payload) - {"request_id", "category_id", "category_proposal"}
    )
    if unknown:
        raise chat_service.ChatError(
            f"unsupported fields: {', '.join(unknown)}",
            "unsupported_fields",
            422,
        )

    request_id = require_request_id(payload.get("request_id"))
    selected_category_id = chat_service.require_positive_id(
        payload.get("category_id")
    )
    pending = begin_category_selection(request_id)
    try:
        raw_categories = chat_service.database_request(
            "get",
            f"{db_url}/categories",
            list,
        )
        categories, names, ids = chat_service.build_category_lookup(
            raw_categories
        )
        if selected_category_id not in names:
            raise chat_service.ChatError(
                "category not found",
                "category_not_found",
                422,
            )

        suggested_category_id = pending.get("suggested_category_id")
        if suggested_category_id == selected_category_id:
            source = "ai_suggestion"
        elif suggested_category_id is not None:
            source = "user_override"
        else:
            source = "user"
        category_selection = {
            "source": source,
            "suggested_category_id": suggested_category_id,
            "suggested_category_name": names.get(suggested_category_id),
            "selected_category_id": selected_category_id,
            "selected_category_name": names[selected_category_id],
            "requires_user_response": False,
        }
        plan = {
            **pending["plan"],
            "fields": {
                **pending["fields"],
                "category_id": selected_category_id,
            },
            "fallback": False,
            "planning_error": None,
            "retryable": False,
        }
        context = {
            "message": pending["message"],
            "db_url": db_url,
            "categories": categories,
            "category_names": names,
            "category_ids": ids,
            "category_selection": category_selection,
            "selection_plan": plan,
            "phase": "category_selection",
        }
        cycle_result = run_cycle(
            context,
            plan=lambda current: current["selection_plan"],
            act=act_on_plan,
            observe=observe_action,
            adapt=adapt_to_observation,
            max_iterations=1,
        )
        raise_cycle_error(cycle_result)
        response = deepcopy(
            cycle_result.get("result") or failed_response()
        )
        response = attach_agent(response, request_id, cycle_result)
        if response.get("preview") is not None:
            response["preview"]["request_id"] = request_id
            register_selected_preview(request_id, response["preview"])
        else:
            restore_category_request(request_id, pending)
        return response
    except Exception:
        restore_category_request(request_id, pending)
        raise


def run_confirmed_transaction(payload, db_url):
    if not isinstance(payload, dict):
        raise chat_service.ChatError(
            "confirmation must be a JSON object",
            "invalid_preview",
            400,
        )
    if "preview" in payload:
        unknown = sorted(set(payload) - {"preview", "request_id"})
        if unknown:
            raise chat_service.ChatError(
                f"unsupported fields: {', '.join(unknown)}",
                "unsupported_fields",
                422,
            )
    preview = payload.get("preview") if "preview" in payload else payload
    if not isinstance(preview, dict):
        raise chat_service.ChatError(
            "preview must be a JSON object",
            "invalid_preview",
            400,
        )
    request_id = payload.get("request_id") or preview.get("request_id")
    if (
        payload.get("request_id") is not None
        and preview.get("request_id") is not None
        and payload["request_id"] != preview["request_id"]
    ):
        raise tampered_preview_error()
    request_id = require_request_id(request_id)
    replay, trusted_preview = begin_apply(request_id, preview)
    if replay:
        return trusted_preview

    context = {
        "db_url": db_url,
        "preview": trusted_preview,
        "allow_suggested_category": True,
        "phase": "confirmed",
    }
    cycle_result = run_cycle(
        context,
        plan=plan_confirmed_transaction,
        act=act_on_confirmed_transaction,
        observe=observe_action,
        adapt=adapt_to_observation,
        max_iterations=1,
    )
    try:
        raise_cycle_error(cycle_result)
        response = deepcopy(cycle_result.get("result") or failed_response())
        response = attach_agent(
            response,
            request_id,
            cycle_result,
        )
        complete_apply(request_id, response)
        return response
    except Exception:
        fail_apply(request_id)
        raise


def plan_transaction(context):
    plan = ollama_service.create_plan(
        context["message"],
        context["categories"],
        context.get("previous_observation"),
    )
    grounding_error = ollama_service.write_grounding_error(
        plan,
        context["message"],
        context["categories"],
    )
    if not plan.get("fallback") and grounding_error is not None:
        return {
            **ollama_service.FALLBACK,
            "fallback": True,
            "planning_error": grounding_error,
            "retryable": True,
        }
    transaction_id = plan.get("transaction_id")
    if (
        not plan.get("fallback")
        and transaction_id is not None
        and not transaction_id_is_grounded(
            context["message"],
            transaction_id,
        )
    ):
        if plan.get("filters"):
            plan = {
                **plan,
                "transaction_id": None,
            }
        else:
            plan = {
                **ollama_service.FALLBACK,
                "fallback": True,
                "planning_error": (
                    "transaction_id must be explicitly present in the "
                    "user request or replaced with safe filters"
                ),
                "retryable": True,
            }
    return plan


def plan_confirmed_transaction(context):
    preview = context["preview"]
    return {
        "operation": preview.get("operation"),
        "transaction_id": preview.get("transaction_id"),
        "fields": deepcopy(preview.get("fields", {})),
        "filters": {},
        "calculation": "none",
        "handoff": "none",
        "reply": "Apply the confirmed server-validated preview.",
        "fallback": False,
        "planning_error": None,
        "retryable": False,
    }


def act_on_plan(plan, context):
    if plan.get("fallback"):
        return {
            "type": "validation",
            "status": "failed",
            "error": {
                "message": plan.get("planning_error")
                or "the transaction plan was invalid",
                "code": plan.get("planning_error") or "invalid_plan",
                "status": 422,
            },
            "replanable": bool(plan.get("retryable")),
            "result": failed_response(plan.get("reply")),
        }

    try:
        if plan["operation"] == "read":
            load_available_transactions(plan, context)
            result = chat_service.execute_read_plan(
                plan,
                context["db_url"],
                context,
            )
            return {
                "type": "query",
                "status": "succeeded",
                "result": result,
                "database_calls": ["GET /transactions"],
            }
        if plan["operation"] == "create":
            return act_on_create(plan, context)

        load_available_transactions(plan, context)
        result = chat_service.execute_write_preview(
            plan,
            context["db_url"],
            context,
        )
        if result.get("requires_clarification"):
            return {
                "type": "target_resolution",
                "status": "succeeded",
                "result": result,
                "matches": result.get("matches", []),
                "database_calls": ["GET /transactions"],
            }
        if result.get("preview") is None:
            return {
                "type": "no_change",
                "status": "succeeded",
                "result": result,
                "database_calls": ["GET /transactions"],
            }
        return {
            "type": "preview",
            "status": "succeeded",
            "result": result,
            "preview": result["preview"],
            "database_calls": ["GET /transactions"],
        }
    except chat_service.ChatError as error:
        return error_action(error)


def act_on_create(plan, context):
    fields = plan.get("fields")
    if not isinstance(fields, dict):
        return error_action(
            chat_service.ChatError(
                "fields must be an object",
                "invalid_preview",
                422,
            )
        )
    base_fields = {
        key: value
        for key, value in fields.items()
        if key not in {"category", "category_id"}
    }
    try:
        clean = chat_service.validate_write_fields(
            base_fields,
            context["category_names"],
            context["category_ids"],
            create=True,
            require_category=False,
        )
    except chat_service.ChatError as error:
        if error.code == "missing_fields":
            result = missing_fields_response(
                plan,
                error.details.get("missing_fields", []),
            )
            return {
                "type": "missing_fields",
                "status": "blocked",
                "result": result,
                "missing_fields": error.details.get("missing_fields", []),
                "database_calls": [],
            }
        return error_action(error)

    selection = context.get("category_selection")
    if selection is not None:
        clean["category_id"] = selection["selected_category_id"]
        result = create_preview_response(plan, clean, context, selection)
        return {
            "type": "preview",
            "status": "succeeded",
            "result": result,
            "preview": result["preview"],
            "database_calls": [],
        }

    explicit_category = ollama_service.explicit_category_in_message(
        context["message"],
        context["categories"],
    )
    if explicit_category is not None:
        clean["category_id"] = context["category_ids"][
            explicit_category.casefold()
        ]
        selection = {
            "source": "user",
            "suggested_category_id": None,
            "suggested_category_name": None,
            "selected_category_id": clean["category_id"],
            "selected_category_name": explicit_category,
            "requires_user_response": False,
        }
        result = create_preview_response(plan, clean, context, selection)
        return {
            "type": "preview",
            "status": "succeeded",
            "result": result,
            "preview": result["preview"],
            "database_calls": [],
        }

    suggested_category_id = corrected_category_suggestion(
        clean["merchant"],
        context,
    )
    if suggested_category_id is None:
        suggested_category_id = resolve_suggested_category(
            fields,
            context["category_names"],
            context["category_ids"],
        )
    suggested_category_name = context["category_names"].get(
        suggested_category_id
    )
    category_selection = {
        "source": "ai_suggestion",
        "suggested_category_id": suggested_category_id,
        "suggested_category_name": suggested_category_name,
        "selected_category_id": None,
        "selected_category_name": None,
        "requires_user_response": True,
    }
    result = {
        **chat_service.build_base_response(plan),
        "reply": (
            f"I suggest {suggested_category_name}. "
            f"Use {suggested_category_name}, or choose another category."
            if suggested_category_name is not None
            else "Choose a category before I prepare this transaction."
        ),
        "requires_clarification": True,
        "category_selection": category_selection,
        "categories": deepcopy(context["categories"]),
    }
    return {
        "type": "category_selection",
        "status": "succeeded",
        "result": result,
        "pending_category": {
            "message": context["message"],
            "plan": deepcopy(plan),
            "fields": clean,
            "suggested_category_id": suggested_category_id,
        },
        "database_calls": ["GET /category-corrections"],
    }


def act_on_confirmed_transaction(plan, context):
    try:
        result = chat_service.execute_confirmed_write(
            context["preview"],
            context["db_url"],
            allow_suggested_category=context["allow_suggested_category"],
        )
    except chat_service.ChatError as error:
        return error_action(error, replanable=False)

    operation = result["operation"]
    if result.get("verified") is not True:
        return {
            "type": "confirmed_write_unverified",
            "status": "failed",
            "verified": False,
            "result": {
                **result,
                "reply": (
                    "The write may have completed, but Tally could not "
                    "verify the result. Refresh transactions before "
                    "starting a new request; do not retry this confirmation."
                ),
                "requires_confirmation": False,
                "requires_clarification": False,
                "preview": None,
                "fallback": True,
                "saved": False,
            },
            "database_calls": confirmed_database_calls(operation),
        }
    reply = {
        "create": "Your transaction was added successfully.",
        "update": "Your transaction was updated successfully.",
        "delete": "Your transaction was deleted successfully.",
    }[operation]
    return {
        "type": "confirmed_write",
        "status": "succeeded",
        "verified": result.get("verified") is True,
        "result": {
            **result,
            "reply": reply,
            "requires_confirmation": False,
            "requires_clarification": False,
            "preview": None,
            "fallback": False,
            "saved": True,
        },
        "database_calls": confirmed_database_calls(operation),
    }


def observe_action(plan, action, context):
    observation = {
        "status": action["status"],
        "phase": context.get("phase", "initial"),
        "action_type": action["type"],
        "match_count": None,
        "matched_transaction_ids": [],
        "analytics": None,
        "before": None,
        "after": None,
        "category_selection": None,
        "verified": action.get("verified"),
        "error": action.get("error"),
    }
    result = action.get("result") or {}
    if action["type"] == "query":
        rows = result.get("transactions", [])
        observation["match_count"] = len(rows)
        observation["matched_transaction_ids"] = [
            row["id"] for row in rows
        ]
        observation["analytics"] = result.get("analytics")
    elif action["type"] == "target_resolution":
        matches = action.get("matches", [])
        observation["match_count"] = len(matches)
        observation["matched_transaction_ids"] = [
            row["id"] for row in matches
        ]
    elif action["type"] == "preview":
        preview = action["preview"]
        observation["match_count"] = (
            0 if preview["operation"] == "create" else 1
        )
        if preview.get("transaction_id") is not None:
            observation["matched_transaction_ids"] = [
                preview["transaction_id"]
            ]
        observation["before"] = preview.get("before")
        observation["after"] = preview.get("after")
        observation["category_selection"] = result.get(
            "category_selection"
        )
    elif action["type"] == "category_selection":
        observation["category_selection"] = result["category_selection"]
    return observation


def adapt_to_observation(plan, action, observation, context):
    deterministic = deterministic_adaptation(
        plan,
        action,
        observation,
        context,
    )
    decision = deterministic["decision"]
    message = deterministic["message"]

    result = adaptation_result(
        action.get("result"),
        decision,
        message,
    )
    return {
        "decision": decision,
        "message": message,
        "revised_plan": None,
        "result": result,
    }


def deterministic_adaptation(plan, action, observation, context):
    action_type = action["type"]
    result = action.get("result") or {}
    if action_type == "query":
        return {
            "decision": "complete",
            "message": result["reply"],
        }
    if action_type == "preview":
        return {
            "decision": "confirm",
            "message": (
                "Check the details below, then confirm when everything "
                "looks right."
            ),
        }
    if action_type in {"category_selection", "missing_fields", "target_resolution"}:
        return {
            "decision": "clarify",
            "message": result["reply"],
        }
    if action_type == "no_change":
        return {
            "decision": "complete",
            "message": result["reply"],
        }
    if action_type == "confirmed_write":
        return {
            "decision": "complete",
            "message": result["reply"],
        }
    if action_type == "confirmed_write_unverified":
        return {
            "decision": "failed",
            "message": result["reply"],
        }
    if (
        action.get("replanable")
        and context.get("previous_observation") is None
    ):
        return {
            "decision": "replan",
            "message": "The transaction plan needs one safe correction.",
        }
    return {
        "decision": "failed",
        "message": result.get("reply") or SAFE_FAILURE["reply"],
    }


def adaptation_result(result, decision, message):
    if decision == "replan":
        return None
    if decision == "failed":
        if result and result.get("write_outcome_unknown"):
            return deepcopy(result)
        return failed_response(message)

    response = deepcopy(result or failed_response(message))
    if decision == "confirm":
        response["reply"] = message
        response["requires_confirmation"] = True
        response["requires_clarification"] = False
    elif decision == "clarify":
        response["reply"] = message
        response["requires_confirmation"] = False
        response["requires_clarification"] = True
        selection = response.get("category_selection")
        if (
            selection is None
            or not selection.get("requires_user_response", False)
        ):
            response["preview"] = None
    else:
        response["requires_confirmation"] = False
        response["requires_clarification"] = False
    return response


def create_preview_response(plan, fields, context, category_selection):
    preview_plan = {
        **plan,
        "fields": fields,
    }
    result = chat_service.execute_write_preview(
        preview_plan,
        context["db_url"],
        context,
    )
    result["category_selection"] = deepcopy(category_selection)
    result["preview"]["category_selection"] = deepcopy(category_selection)
    if category_selection["source"] == "user_override":
        result["preview"]["suggested_category_id"] = category_selection[
            "suggested_category_id"
        ]
    return result


def resolve_suggested_category(fields, names, ids):
    try:
        return chat_service.resolve_category_id(
            fields.get("category_id"),
            fields.get("category"),
            names,
            ids,
        )
    except chat_service.ChatError:
        return None


def corrected_category_suggestion(merchant, context):
    corrections = chat_service.database_request(
        "get",
        f"{context['db_url']}/category-corrections",
        list,
        params={"merchant": merchant, "limit": 10},
    )
    candidates = []
    for correction in corrections:
        category_id = correction.get("user_category_id")
        if (
            not chat_service.is_positive_integer(category_id)
            or category_id not in context["category_names"]
        ):
            raise chat_service.invalid_database_error()
        candidates.append(category_id)
    if not candidates:
        return None
    counts = {
        category_id: candidates.count(category_id)
        for category_id in set(candidates)
    }
    return max(
        counts,
        key=lambda category_id: (
            counts[category_id],
            -candidates.index(category_id),
        ),
    )


def missing_fields_response(plan, missing):
    labels = {
        "date": "date",
        "merchant": "merchant",
        "description": "description",
        "amount": "amount",
    }
    requested = [labels[item] for item in missing if item in labels]
    if len(requested) == 1:
        detail = requested[0]
    elif len(requested) == 2:
        detail = f"{requested[0]} and {requested[1]}"
    else:
        detail = ", ".join(requested[:-1]) + f", and {requested[-1]}"
    return {
        **chat_service.build_base_response(plan),
        "reply": f"What {detail} should I use for this transaction?",
        "requires_clarification": True,
    }


def error_action(error, replanable=None):
    if replanable is None:
        replanable = error.code in _REPLANABLE_CODES
    return {
        "type": "error",
        "status": "failed",
        "error": {
            "message": error.message,
            "code": error.code,
            "status": error.status,
            **error.details,
        },
        "replanable": replanable,
        "result": failed_response(error.message),
    }


def failed_response(reply=None):
    return {
        "reply": reply or SAFE_FAILURE["reply"],
        "operation": None,
        "handoff": "none",
        "requires_confirmation": False,
        "requires_clarification": False,
        "preview": None,
        "fallback": True,
    }


def attach_agent(response, request_id, cycle_result):
    response["agent"] = {
        "request_id": request_id,
        "status": cycle_result["status"],
        "models": {"planner": config.CHAT_MODEL},
        "trace": (
            build_trace(cycle_result.get("cycles", []))
            if config.AGENT_TRACE_ENABLED
            else []
        ),
    }
    return response


def build_trace(cycles):
    trace = []
    for cycle in cycles:
        iteration = cycle["iteration"]
        if "plan" in cycle:
            trace.append({
                "stage": "PLAN",
                "status": (
                    "failed"
                    if cycle["plan"].get("fallback")
                    else "succeeded"
                ),
                "summary": plan_summary(cycle["plan"]),
                "iteration": iteration,
            })
        if "action" in cycle:
            trace.append({
                "stage": "ACT",
                "status": cycle["action"]["status"],
                "summary": action_summary(cycle["action"]),
                "iteration": iteration,
            })
        if "observation" in cycle:
            trace.append({
                "stage": "OBSERVE",
                "status": cycle["observation"]["status"],
                "summary": observation_summary(cycle["observation"]),
                "iteration": iteration,
            })
        if "adaptation" in cycle:
            trace.append({
                "stage": "ADAPT",
                "status": cycle["adaptation"]["decision"],
                "summary": cycle["adaptation"]["message"],
                "iteration": iteration,
            })
        if "error" in cycle:
            trace.append({
                "stage": cycle["error"]["stage"],
                "status": "failed",
                "summary": "The stage failed safely.",
                "iteration": iteration,
            })
    return trace


def plan_summary(plan):
    if plan.get("fallback"):
        return "The planner response was rejected safely."
    return f"Understood this as a {plan['operation']} request."


def action_summary(action):
    summaries = {
        "category_selection": "Prepared a category choice without saving.",
        "confirmed_write": "Applied one confirmed transaction write.",
        "confirmed_write_unverified": (
            "Applied a write but could not verify its final state."
        ),
        "error": "Blocked the action safely.",
        "missing_fields": "Found required transaction details were missing.",
        "no_change": "Found the requested values were already current.",
        "preview": "Prepared a non-mutating transaction preview.",
        "query": "Queried transactions using trusted application code.",
        "target_resolution": "Resolved the possible transaction targets.",
        "validation": "Rejected an invalid transaction plan.",
    }
    return summaries.get(action["type"], "Completed the trusted action.")


def observation_summary(observation):
    action_type = observation["action_type"]
    if action_type == "query":
        return (
            f"Found {observation['match_count']} matching "
            "transaction(s) and calculated the result."
        )
    if action_type == "target_resolution":
        return (
            f"Found {observation['match_count']} possible "
            "transaction target(s)."
        )
    if action_type == "category_selection":
        suggestion = observation["category_selection"].get(
            "suggested_category_name"
        )
        return (
            f"Suggested {suggestion} and waited for the user's choice."
            if suggestion
            else "No valid category suggestion was available."
        )
    if action_type == "preview":
        return "Recorded the complete before and after preview."
    if action_type == "confirmed_write":
        return "Verified the persisted transaction result."
    if action_type == "confirmed_write_unverified":
        return "The final persisted state could not be verified."
    if observation.get("error"):
        return "Observed a blocked or failed action."
    return "Observed the trusted action result."


def confirmed_database_calls(operation):
    if operation == "create":
        return ["POST /transactions"]
    if operation == "update":
        return [
            "GET /transactions/{id}",
            "PATCH /transactions/{id}",
        ]
    return [
        "GET /transactions/{id}",
        "DELETE /transactions/{id}",
        "GET /transactions/{id}",
    ]


def load_available_transactions(plan, context):
    if (
        not isinstance(plan.get("filters"), dict)
        or plan["filters"].get("merchant") is None
        or "available_transactions" in context
    ):
        return
    rows = chat_service.database_request(
        "get",
        f"{context['db_url']}/transactions",
        list,
    )
    context["available_transactions"] = [
        chat_service.transaction_row(row, context["category_names"])
        for row in rows
    ]


def transaction_id_is_grounded(message, transaction_id):
    escaped_id = re.escape(str(transaction_id))
    patterns = (
        rf"\btransaction(?:\s+id)?\s*(?:[:=#-]\s*)?{escaped_id}\b",
        rf"\bid\s*(?:[:=#-]\s*)?{escaped_id}\b",
        rf"(?<![a-z0-9])#{escaped_id}\b",
    )
    return any(
        re.search(pattern, message, re.IGNORECASE)
        for pattern in patterns
    )


def raise_cycle_error(cycle_result):
    action = last_cycle_value(cycle_result, "action")
    error = action.get("error") if isinstance(action, dict) else None
    if (
        error
        and action["type"] == "error"
        and not action.get("replanable")
    ):
        raise chat_service.ChatError(
            error["message"],
            error["code"],
            error["status"],
            **{
                key: value
                for key, value in error.items()
                if key not in {"message", "code", "status"}
            },
        )


def last_cycle_value(cycle_result, key):
    for cycle in reversed(cycle_result.get("cycles", [])):
        if key in cycle:
            return cycle[key]
    return {}


def require_request_id(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 100
    ):
        raise chat_service.ChatError(
            "request_id is invalid",
            "invalid_request_id",
            422,
        )
    return value.strip()


def register_category_request(request_id, pending):
    with _REQUEST_LOCK:
        cleanup_requests()
        _REQUESTS[request_id] = {
            "status": "category",
            "value": deepcopy(pending),
            "context": pending["message"],
            "expires_at": monotonic() + config.AGENT_REQUEST_TTL_SECONDS,
        }


def begin_category_selection(request_id):
    with _REQUEST_LOCK:
        cleanup_requests()
        item = _REQUESTS.get(request_id)
        if item is None or item["status"] != "category":
            raise request_state_error()
        item["status"] = "selecting"
        item["expires_at"] = (
            monotonic() + config.AGENT_REQUEST_TTL_SECONDS
        )
        return deepcopy(item["value"])


def restore_category_request(request_id, pending):
    with _REQUEST_LOCK:
        item = _REQUESTS.get(request_id)
        if item is None or item["status"] != "selecting":
            return
        item["status"] = "category"
        item["value"] = deepcopy(pending)
        item["expires_at"] = (
            monotonic() + config.AGENT_REQUEST_TTL_SECONDS
        )


def register_initial_preview(request_id, preview, message):
    with _REQUEST_LOCK:
        cleanup_requests()
        if request_id in _REQUESTS:
            raise request_state_error()
        _REQUESTS[request_id] = {
            "status": "preview",
            "value": deepcopy(preview),
            "context": message,
            "expires_at": monotonic() + config.AGENT_REQUEST_TTL_SECONDS,
        }


def register_selected_preview(request_id, preview):
    with _REQUEST_LOCK:
        cleanup_requests()
        item = _REQUESTS.get(request_id)
        if item is None or item["status"] != "selecting":
            raise request_state_error()
        item["status"] = "preview"
        item["value"] = deepcopy(preview)
        item["expires_at"] = (
            monotonic() + config.AGENT_REQUEST_TTL_SECONDS
        )


def get_preview_request_context(request_id):
    request_id = require_request_id(request_id)
    with _REQUEST_LOCK:
        cleanup_requests()
        item = _REQUESTS.get(request_id)
        if item is None or item["status"] != "preview":
            raise request_state_error()
        context = item.get("context")
        if not isinstance(context, str) or not context:
            raise request_state_error()
        return context


def begin_apply(request_id, preview):
    candidate = deepcopy(preview)
    candidate["request_id"] = request_id
    with _REQUEST_LOCK:
        cleanup_requests()
        item = _REQUESTS.get(request_id)
        if item is None:
            raise request_state_error()
        if item["status"] == "completed":
            if candidate != item["preview"]:
                raise tampered_preview_error()
            return True, deepcopy(item["result"])
        if item["status"] == "applying":
            raise chat_service.ChatError(
                "this confirmation is already being applied",
                "request_in_progress",
                409,
            )
        if item["status"] != "preview":
            raise request_state_error()
        if candidate != item["value"]:
            raise tampered_preview_error()
        stored = deepcopy(item["value"])
        item["status"] = "applying"
        item["preview"] = deepcopy(stored)
        item["expires_at"] = monotonic() + config.AGENT_REQUEST_TTL_SECONDS
        return False, stored


def complete_apply(request_id, result):
    with _REQUEST_LOCK:
        item = _REQUESTS.get(request_id)
        if item is None or item["status"] != "applying":
            raise request_state_error()
        item["status"] = "completed"
        item["result"] = deepcopy(result)
        item["expires_at"] = monotonic() + config.AGENT_REQUEST_TTL_SECONDS


def fail_apply(request_id):
    with _REQUEST_LOCK:
        item = _REQUESTS.get(request_id)
        if item is None:
            return
        item["status"] = "failed"
        item["expires_at"] = monotonic() + config.AGENT_REQUEST_TTL_SECONDS


def cleanup_requests():
    now = monotonic()
    expired = [
        request_id
        for request_id, item in _REQUESTS.items()
        if item["expires_at"] <= now
    ]
    for request_id in expired:
        del _REQUESTS[request_id]


def reset_transaction_requests():
    with _REQUEST_LOCK:
        _REQUESTS.clear()


def request_state_error():
    return chat_service.ChatError(
        "the agent request is missing, expired, or no longer active",
        "agent_request_unavailable",
        409,
    )


def tampered_preview_error():
    return chat_service.ChatError(
        "the confirmation preview does not match the server-issued preview",
        "invalid_preview",
        422,
    )
