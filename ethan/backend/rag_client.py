from __future__ import annotations

import numbers

import requests

from . import config
from .db_api import ServiceError


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    if not config.RAG_ENABLED:
        raise ServiceError("RAG mode is disabled.", 503, "rag_disabled")
    url = f"{config.RAG_SERVER_URL}{path}"
    try:
        if method == "GET":
            response = requests.get(url, timeout=config.RAG_TIMEOUT_SECONDS)
        else:
            response = requests.post(url, json=payload, timeout=config.RAG_TIMEOUT_SECONDS)
    except requests.Timeout:
        raise ServiceError("The RAG server did not respond in time.", 503, "rag_timeout") from None
    except requests.RequestException:
        raise ServiceError("The RAG server is unavailable.", 503, "rag_connection") from None

    if not 200 <= response.status_code < 300:
        raise ServiceError("The RAG server returned an error.", 502, "rag_http_error")
    try:
        body = response.json()
    except (ValueError, RecursionError):
        raise ServiceError("The RAG server returned an invalid response.", 502, "rag_invalid_response") from None
    if not isinstance(body, dict):
        raise ServiceError("The RAG server returned an invalid response.", 502, "rag_invalid_response")
    return body


def health() -> dict:
    body = _request("GET", "/health")
    if not isinstance(body.get("collections"), list):
        raise ServiceError("The RAG server returned an invalid response.", 502, "rag_invalid_response")
    return body


def retrieve(feature: str, question: str, k: int = 3, where: dict | None = None) -> list[dict]:
    payload = {"feature": feature, "question": question, "k": k}
    if where is not None:
        payload["where"] = where
    body = _request("POST", "/retrieve", payload)
    results = body.get("results")
    if not isinstance(results, list):
        raise ServiceError("The RAG server returned an invalid response.", 502, "rag_invalid_response")
    normalised: list[dict] = []
    for item in results:
        if not (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("text"), str)
            and isinstance(item.get("metadata"), dict)
            and isinstance(item.get("distance"), numbers.Real)
            and not isinstance(item.get("distance"), bool)
        ):
            raise ServiceError("The RAG server returned an invalid response.", 502, "rag_invalid_response")
        normalised.append(
            {
                "id": item["id"],
                "text": item["text"],
                "metadata": item["metadata"],
                "distance": float(item["distance"]),
            }
        )
    return normalised
