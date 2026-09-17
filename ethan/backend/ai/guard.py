from __future__ import annotations

import json

from .ollama_client import chat


def run(model, prompt_builder, validator, fallback, timeout=None):
    error = None
    for _ in range(2):
        messages = prompt_builder(error)
        try:
            response = chat(model, messages, timeout=timeout)
            content = response.get("message", {}).get("content", "")
            data = json.loads(content)
        except Exception as exc:
            error = str(exc)
            continue
        error = validator(data)
        if error is None:
            result = dict(data)
            result["fallback"] = False
            return result
    result = dict(fallback)
    result["fallback"] = True
    return result

