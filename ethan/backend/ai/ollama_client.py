from __future__ import annotations

import requests

from .. import config


def chat(model: str, messages: list[dict], timeout: float | None = None) -> dict:
    response = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2},
        },
        timeout=timeout or config.AI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
