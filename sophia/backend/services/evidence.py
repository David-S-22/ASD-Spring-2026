"""Grounded answers about the user's bills: retrieve through MCP, gate in code, generate through the guard."""
import logging
import re

from sophia.backend import config
from sophia.backend.ai import grounded_prompt, guard
from sophia.backend.ai.schemas import validate_grounded_answer
from sophia.backend.services import tools as tools_service
from sophia.backend.services.errors import ModeError, ServiceError

logger = logging.getLogger(__name__)

FEATURE = "billing"
INSUFFICIENT_ANSWER = "Tally couldn't find a bill that covers that."
FALLBACK_ANSWER = "Tally found matching bills but couldn't put an answer together; try again."
SOURCE_PATTERN = re.compile(r"^bill-(\d+)-.*\.md$")
RETRIEVAL_MARGIN = 3
TITLE_SUFFIX = re.compile(r"\s*\((bill|subscription)\)$")


def _valid_chunk(item):
    """True when a retrieved item has a string id and text, a metadata dict and a numeric distance."""
    return (
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("text"), str)
        and isinstance(item.get("metadata"), dict)
        and isinstance(item.get("distance"), (int, float))
        and not isinstance(item.get("distance"), bool)
    )


def retrieve(question, k):
    """Return (at most k bill chunks closest first, duration_ms) from retrieve_context, fetching RETRIEVAL_MARGIN extra so the shared billing folder's other files never take a bill's slot; a tool error means the RAG server is down."""
    data, duration_ms = tools_service.call_allowed_tool(tools_service.RETRIEVAL_TOOL, {"feature": FEATURE, "question": question, "k": k + RETRIEVAL_MARGIN})
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not all(_valid_chunk(item) for item in results):
        raise ModeError("mcp_invalid_result")
    chunks = [
        {"id": r["id"], "source": str(r["metadata"].get("source", "")), "text": r["text"], "distance": float(r["distance"])}
        for r in results
    ]
    own_chunks = [chunk for chunk in chunks if SOURCE_PATTERN.match(chunk["source"])]
    return sorted(own_chunks, key=lambda chunk: chunk["distance"])[:k], duration_ms


def confidence_for(chunks):
    """Confidence from the closest chunk in the list: high below RAG_HIGH, medium below RAG_MEDIUM, low otherwise."""
    if not chunks:
        return "none"
    best = min(chunk["distance"] for chunk in chunks)
    if best < config.RAG_HIGH:
        return "high"
    if best < config.RAG_MEDIUM:
        return "medium"
    return "low"


def _citation(chunk):
    """Shape one cited chunk as {source, bill_id, title, distance} for the chips."""
    match = SOURCE_PATTERN.match(chunk["source"])
    first_line = chunk["text"].splitlines()[0] if chunk["text"] else chunk["source"]
    title = TITLE_SUFFIX.sub("", first_line.lstrip("# ").strip())
    return {"source": chunk["source"], "bill_id": int(match.group(1)) if match else None, "title": title, "distance": round(chunk["distance"], 3)}


def _card(answer, citations, confidence, insufficient, retrieval, fallback, duration_ms):
    """Shape the evidence response dict the JSON and UI routes both return."""
    return {"answer": answer, "citations": citations, "confidence": confidence, "insufficient": insufficient,
            "retrieval": retrieval, "fallback": fallback, "duration_ms": duration_ms}


def ask(question):
    """Answer question from the bills corpus only; ModeError when a mode is off or the MCP call fails."""
    tools_service.require_modes(tools_service.RETRIEVAL_TOOL)
    if not isinstance(question, str) or not question.strip():
        raise ServiceError("question is required")
    question = question.strip()
    k = config.RAG_TOP_K
    chunks, duration_ms = retrieve(question, k)
    retrieval = [{"id": c["id"], "source": c["source"], "distance": round(c["distance"], 3)} for c in chunks]
    survivors = [c for c in chunks if c["distance"] <= config.RAG_LOW]
    best = retrieval[0]["distance"] if retrieval else None
    if not survivors:
        logger.info("RAG_TOOL feature=%s k=%s kept=%s best=%s confidence=none insufficient=true duration_ms=%s",
                    FEATURE, k, len(chunks), best, duration_ms)
        return _card(answer=INSUFFICIENT_ANSWER, citations=[], confidence="none", insufficient=True, retrieval=retrieval, fallback=False, duration_ms=duration_ms)
    data = guard.run(
        config.CHAT_MODEL,
        lambda error: grounded_prompt.build(question, survivors, error=error),
        validate_grounded_answer,
        grounded_prompt.FALLBACK,
        timeout=config.GROUNDED_TIMEOUT_SECONDS,
    )
    if data["fallback"]:
        logger.info("RAG_TOOL feature=%s k=%s kept=%s best=%s confidence=none insufficient=true fallback=true duration_ms=%s",
                    FEATURE, k, len(chunks), best, duration_ms)
        return _card(answer=FALLBACK_ANSWER, citations=[], confidence="none", insufficient=True, retrieval=retrieval, fallback=True, duration_ms=duration_ms)
    by_source = {c["source"]: c for c in survivors}
    cited = [by_source[s] for s in dict.fromkeys(data["cited"]) if s in by_source]
    insufficient = bool(data["insufficient"]) or not cited
    confidence = "none" if insufficient else confidence_for(cited)
    logger.info("RAG_TOOL feature=%s k=%s kept=%s best=%s confidence=%s insufficient=%s duration_ms=%s",
                FEATURE, k, len(chunks), best, confidence, str(insufficient).lower(), duration_ms)
    if insufficient:
        return _card(answer=INSUFFICIENT_ANSWER, citations=[], confidence="none", insufficient=True, retrieval=retrieval, fallback=False, duration_ms=duration_ms)
    return _card(answer=data["answer"], citations=[_citation(c) for c in cited], confidence=confidence, insufficient=False, retrieval=retrieval, fallback=False, duration_ms=duration_ms)
