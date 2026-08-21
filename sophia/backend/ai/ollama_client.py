"""Minimal client for the local Ollama chat API."""
import requests

from sophia.backend import config


def chat(model, messages, timeout=None):
    """POST a chat completion request to Ollama and return the parsed JSON response body."""
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
