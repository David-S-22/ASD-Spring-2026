import logging
from functools import lru_cache
from typing import Any, Optional

from openai import OpenAI
from openai.types.responses.tool_param import Mcp

from ..config import config


logger = logging.getLogger(__name__)


def prompt(*, system_prompt: str, user_prompt: str, model: str, temperature: float, output_tokens: int) -> str:
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
        extra_body={"think": True},
    )

    if thinking := _extract_thinking(response):
        logger.debug("Model thinking trace for %s: %s", model, thinking)
    model_text = _extract_response_text(response)
    logger.debug("Model response for %s: %s", model, model_text)
    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.debug("Model usage for %s: %s", model, usage)

    return model_text


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


@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    return OpenAI(base_url=config.OLLAMA_URL, api_key="ollama", timeout=180)
