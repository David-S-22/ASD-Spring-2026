"""Grounded category suggestion for a Tally create without a category.

Wraps ``rag_answer.grounded_answer`` with the switch check, the question
built from merchant and description only, degradation of every ``RAGError``
to an ``unavailable`` grounding, and the ``RAG_GROUNDING`` log record.
"""
import time

from .. import config
from . import rag_answer
from .rag_client import RAGError


def build_question(fields):
    merchant = str(fields.get("merchant") or "").strip()
    description = str(fields.get("description") or "").strip()
    return f"Merchant: {merchant}; Description: {description}"


def grounded_category_suggestion(fields, context):
    """Return ``(category_id or None, grounding)`` for a create."""
    started = time.perf_counter()
    if not config.RAG_ENABLED:
        grounding = {"status": "disabled"}
        log_grounding(context, grounding, started)
        return None, grounding

    question = build_question(fields)
    try:
        grounding = rag_answer.grounded_answer(
            question,
            context["categories"],
        )
    except RAGError as error:
        grounding = {"status": "unavailable", "error": error.code}
        log_grounding(context, grounding, started)
        return None, grounding

    if grounding.get("insufficient_context"):
        log_grounding(context, grounding, started)
        return None, grounding

    category_id = context["category_ids"].get(
        str(grounding.get("answer") or "").casefold()
    )
    if category_id is None:
        grounding = {
            **grounding,
            "status": "unavailable",
            "error": "no_category_resolved",
        }
        log_grounding(context, grounding, started)
        return None, grounding

    log_grounding(context, grounding, started)
    return category_id, grounding


def log_grounding(context, grounding, started):
    """Emit one RAG_GROUNDING record; never includes text or excerpts."""
    if not config.AGENT_LOG_ENABLED:
        return
    from .transaction_orchestrator import log_workflow_event

    attempted = grounding["status"] != "disabled"
    log_workflow_event({
        "event": "RAG_GROUNDING",
        "request_id": context.get("request_id"),
        "phase": context.get("phase", "initial"),
        "iteration": context.get("iteration"),
        "stage": "ACT",
        "collections": (
            [config.RAG_RECORDS_COLLECTION, config.RAG_GUIDE_COLLECTION]
            if attempted
            else []
        ),
        "retrieved": grounding.get("retrieved", 0),
        "survivors": grounding.get("survivors", 0),
        "best_distance": grounding.get("best_distance"),
        "model_probability": grounding.get("model_probability"),
        "confidence": grounding.get("confidence"),
        "status": grounding["status"],
        "derived_from_votes": grounding.get("derived_from_votes", False),
        "uncited": grounding.get("uncited", False),
        "citations": len(grounding.get("citations") or []),
        "model": config.RAG_MODEL if attempted else None,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "error": grounding.get("error"),
    })
