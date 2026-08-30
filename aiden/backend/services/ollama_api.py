from functools import lru_cache

from openai import OpenAI

from ..helpers import get_env


def prompt(system_prompt: str, user_prompt: str, review: bool = False) -> str:
    # We intentionally want the review model to be a bit more deterministic,
    # so we lower the temperature a little bit. The client instance is cached
    # between calls, as a singleton instance.

    client = _get_client()
    temperature = 0.2 if review else 0.8
    model = get_env("OLLAMA_REVIEW_MODEL" if review else "OLLAMA_IMPLEMENTATION_MODEL")

    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=300,
        temperature=temperature)

    return response.output_text.strip()

@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    return OpenAI(base_url=get_env("OLLAMA_URL"), api_key="ollama", timeout=180)
