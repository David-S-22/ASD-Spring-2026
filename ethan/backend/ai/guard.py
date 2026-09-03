from __future__ import annotations

import json

import requests

from .ollama_client import chat


def run(model: str, build_prompt, validator, fallback: dict) -> dict:
    error = None
    for _attempt in range(2):
        try:
            response = chat(model, build_prompt(error))
            payload = json.loads(response["message"]["content"])
        except requests.RequestException:
            return {**fallback, "fallback": True}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RecursionError) as parse_error:
            error = str(parse_error)
            continue
        validation_error = validator(payload)
        if validation_error is None:
            return {**payload, "fallback": False}
        error = validation_error
    return {**fallback, "fallback": True}
