from functools import lru_cache

from openai import OpenAI

from .. import config


def prompt(*, system_prompt: str, user_prompt: str, model: str, temperature: float, output_tokens: int) -> str:
    # The client instance is cached between calls, as a singleton instance.

    client = _get_client()

    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=output_tokens,
        temperature=temperature)

    return response.output_text.strip()

@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    return OpenAI(base_url=config.OLLAMA_URL, api_key="ollama", timeout=180)
