import logging
from functools import lru_cache

from openai import OpenAI
from openai.types.responses.tool_param import Mcp

from ..helpers import get_env


logger = logging.getLogger(__name__)


def prompt(*, system_prompt: str, user_prompt: str, model: str, temperature: float, output_tokens: int) -> str:
    # The client instance is cached between calls, as a singleton instance.

    client = _get_client()

    mcp = Mcp(
        type="mcp",
        server_label="mcp-server",
        server_url="https://google.com",
        require_approval="never"
    )

    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=output_tokens,
        tools=[mcp],
        temperature=temperature)

    response.reasoning

    logger.debug("Model response for %s: %s", model, response.output_text)
    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.debug("Model usage for %s: %s", model, usage)

    return response.output_text.strip()

@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    return OpenAI(base_url=get_env("OLLAMA_URL"), api_key="ollama", timeout=180)
