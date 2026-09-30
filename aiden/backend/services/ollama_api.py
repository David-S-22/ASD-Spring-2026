import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from openai import OpenAI
from openai.types.responses.tool_param import Mcp

from ..config import config


logger = logging.getLogger(__name__)

# Number of top alternative tokens to request alongside each generated token.
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

    mcp = Mcp(
        type="mcp",
        server_label="mcp-server",
        server_url=config.MCP_SERVER_URL,
        require_approval="never",
    )

    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=output_tokens,
        tools=[mcp],
        temperature=temperature,
        top_logprobs=_TOP_LOGPROBS,
        include=["message.output_text.logprobs"],
        extra_body={"think": True},
    )

    if thinking := _extract_thinking(response):
        logger.debug("Model thinking trace for %s: %s", model, thinking)
    model_text = _extract_response_text(response)
    logger.debug("Model response for %s: %s", model, model_text)
    mean_confidence = _extract_mean_confidence(response)
    logger.debug("Model mean confidence for %s: %s", model, mean_confidence)
    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.debug("Model usage for %s: %s", model, usage)

    return PromptResult(text=model_text, mean_confidence=mean_confidence)


def _response_payload(response: Any) -> Any:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if isinstance(response, dict):
        return response
    return vars(response)


def _extract_thinking(response: Any) -> Optional[str]:
    """Read Ollama's optional thinking trace without exposing it in API output."""

    traces: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            thinking = value.get("thinking")
            if isinstance(thinking, str) and thinking.strip():
                traces.append(thinking.strip())
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(_response_payload(response))
    return "\n".join(traces) or None


def _extract_response_text(response: Any) -> str:
    """Return the final answer even when the SDK leaves output_text empty."""

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    payload = _response_payload(response)
    output = payload.get("output", payload) if isinstance(payload, dict) else payload
    texts: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"thinking", "reasoning", "reasoning_content"}:
                    continue
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

    The model attaches a ``logprob`` to each output token. Each token's
    probability is ``exp(logprob)``; we average these to gauge how confident the
    model was overall. Nested ``top_logprobs`` entries (alternative tokens) are
    skipped so only the tokens the model actually produced are counted. Returns
    ``None`` when the server does not provide log probabilities.
    """

    probabilities: list[float] = []
    logprob_arrays: list[tuple[str, str, Optional[int]]] = []

    def collect(value: Any, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "top_logprobs":
                    continue
                child_path = f"{path}.{key}"
                if key == "logprobs":
                    entry_count = len(child) if isinstance(child, list) else None
                    logprob_arrays.append(
                        (child_path, type(child).__name__, entry_count)
                    )
                if (
                    key == "logprob"
                    and isinstance(child, (int, float))
                    and not isinstance(child, bool)
                ):
                    probabilities.append(math.exp(float(child)))
                else:
                    collect(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, f"{path}[{index}]")

    collect(_response_payload(response))
    logger.debug(
        "Logprob extraction: fields=%s, generated-token scores=%d",
        logprob_arrays,
        len(probabilities),
    )

    if not probabilities:
        return None

    return sum(probabilities) / len(probabilities)


@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    return OpenAI(base_url=config.OLLAMA_URL, api_key="ollama", timeout=180)
