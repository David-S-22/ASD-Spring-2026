import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from openai import OpenAI

from ..config import config


logger = logging.getLogger(__name__)

# Number of top alternative tokens to request log probabilities for. Only the
# chosen token's log prob is used to gauge confidence, but the Responses API
# requires this to be set for logprobs to be returned.
_TOP_LOGPROBS = 1


@dataclass(frozen=True)
class PromptResult:
    """The model's answer plus a confidence signal derived from log probs.

    ``mean_confidence`` is the mean per-token probability of the generated
    answer (each token's probability is ``exp(logprob)``), a value in ``(0, 1]``
    where higher means the model was more certain. It is ``None`` when the model
    server does not return log probabilities.
    """

    text: str
    mean_confidence: Optional[float]


def prompt(*, system_prompt: str, user_prompt: str, model: str, temperature: float, output_tokens: int) -> PromptResult:
    # The client instance is cached between calls, as a singleton instance.

    client = _get_client()

    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=output_tokens,
        temperature=temperature,
        top_logprobs=_TOP_LOGPROBS,
        include=["message.output_text.logprobs"])

    model_text = _extract_response_text(response)
    logger.debug("Model response for %s: %s", model, model_text)
    mean_confidence = _extract_mean_confidence(response)
    logger.debug("Model mean confidence for %s: %s", model, mean_confidence)

    return PromptResult(text=model_text, mean_confidence=mean_confidence)


def _response_payload(response: Any) -> Any:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if isinstance(response, dict):
        return response
    return vars(response)


def _extract_response_text(response: Any) -> str:
    """Return the final answer text, falling back to the raw response payload."""

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    payload = _response_payload(response)
    output = payload.get("output", payload) if isinstance(payload, dict) else payload
    texts: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "text" and isinstance(child, str) and child.strip():
                    texts.append(child.strip())
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(output)
    return "\n".join(texts)


def _extract_mean_confidence(response: Any) -> Optional[float]:
    """Return the mean per-token probability of the generated answer.

    The Responses API attaches a ``logprob`` to each output token. Each token's
    probability is ``exp(logprob)``; we average these to gauge how confident the
    model was overall. Nested ``top_logprobs`` entries (alternative tokens) are
    skipped so only the tokens the model actually produced are counted. Returns
    ``None`` when the server does not provide log probabilities.
    """

    probabilities: list[float] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "top_logprobs":
                    continue
                if key == "logprob" and isinstance(child, (int, float)) and not isinstance(child, bool):
                    probabilities.append(math.exp(float(child)))
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(_response_payload(response))

    if not probabilities:
        return None

    return sum(probabilities) / len(probabilities)


@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    return OpenAI(base_url=config.OLLAMA_URL, api_key="ollama", timeout=180)
