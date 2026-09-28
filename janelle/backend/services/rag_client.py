"""Small client for the shared RAG context-retrieval server.

Every failure is raised as ``RAGError`` with a safe code. The original
exception text and response bodies are never logged or re-raised.
"""
import numbers

import requests

from .. import config


SAFE_MESSAGES = {
    "rag_disabled": "RAG mode is disabled.",
    "rag_connection": "The RAG server is unavailable.",
    "rag_timeout": "The RAG server did not respond in time.",
    "rag_http_error": "The RAG server returned an error.",
    "rag_invalid_response": "The RAG server returned an invalid response.",
}


class RAGError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        self.message = message or SAFE_MESSAGES.get(
            code,
            "The RAG request failed.",
        )
        super().__init__(self.message)


def _request(method, path, payload=None):
    if not config.RAG_ENABLED:
        raise RAGError("rag_disabled")

    try:
        url = f"{config.RAG_SERVER_URL}{path}"
        if method == "GET":
            response = requests.get(
                url,
                timeout=config.RAG_TIMEOUT_SECONDS,
            )
        else:
            response = requests.post(
                url,
                json=payload,
                timeout=config.RAG_TIMEOUT_SECONDS,
            )
    except requests.Timeout:
        raise RAGError("rag_timeout") from None
    except requests.RequestException:
        raise RAGError("rag_connection") from None

    if not 200 <= response.status_code < 300:
        raise RAGError("rag_http_error")

    try:
        body = response.json()
    except (ValueError, RecursionError):
        raise RAGError("rag_invalid_response") from None
    if not isinstance(body, dict):
        raise RAGError("rag_invalid_response")
    return body


def health():
    """Return the server health body, including its collection names."""
    body = _request("GET", "/health")
    if not isinstance(body.get("collections"), list):
        raise RAGError("rag_invalid_response")
    return body


def refresh(feature, ids, documents, metadatas=None):
    """Rebuild one collection and return ``{"feature", "total"}``."""
    body = _request("POST", "/refresh", {
        "feature": feature,
        "ids": list(ids),
        "documents": list(documents),
        "metadatas": None if metadatas is None else list(metadatas),
    })
    total = body.get("total")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or not isinstance(body.get("feature"), str)
    ):
        raise RAGError("rag_invalid_response")
    return {"feature": body["feature"], "total": total}


def _valid_result(item):
    return (
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("text"), str)
        and isinstance(item.get("metadata"), dict)
        and isinstance(item.get("distance"), numbers.Real)
        and not isinstance(item.get("distance"), bool)
    )


def retrieve(feature, question, k=3, where=None):
    """Return ``[{"id", "text", "metadata", "distance"}]`` closest first."""
    payload = {"feature": feature, "question": question, "k": k}
    if where is not None:
        payload["where"] = where
    body = _request("POST", "/retrieve", payload)

    results = body.get("results")
    if not isinstance(results, list) or not all(
        _valid_result(item) for item in results
    ):
        raise RAGError("rag_invalid_response")
    return [
        {
            "id": item["id"],
            "text": item["text"],
            "metadata": item["metadata"],
            "distance": float(item["distance"]),
        }
        for item in results
    ]
