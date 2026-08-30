from openai import OpenAI

from ..helpers import get_env


_implementation_model = get_env("OLLAMA_IMPLEMENTATION_MODEL")
_review_model = get_env("OLLAMA_REVIEW_MODEL")
_ollama_url = get_env("OLLAMA_URL")
_client = OpenAI(base_url=_ollama_url, api_key="ollama", timeout=180)


def prompt(system_prompt: str, user_prompt: str, review: bool = False) -> str:
    # We intentionally want the review model to be a bit more deterministic,
    # so we lower the temperature a little bit

    response = _client.responses.create(
        model=_review_model if review else _implementation_model,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=300,
        temperature=0.2 if review else 0.8)

    return response.output_text.strip()
