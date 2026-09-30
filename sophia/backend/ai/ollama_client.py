"""Minimal client for the local Ollama chat API."""
import requests

from sophia.backend import config


def chat(model, messages, timeout=None, temperature=None):
    """POST a chat completion request to Ollama and return the parsed JSON response body; temperature defaults to config.AI_TEMPERATURE."""
    response = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "format": "json",
            "stream": False,
            "keep_alive": config.OLLAMA_KEEP_ALIVE,
            "options": {"temperature": config.AI_TEMPERATURE if temperature is None else temperature},
        },
        timeout=timeout or config.AI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
