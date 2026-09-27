import asyncio
import json
import math
import os
import pathlib
from typing import Any, Literal
from fastmcp import Client
from openai import OpenAI

ConfidenceCategory = Literal["High", "Medium", "Low"]

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/mcp")
OLLAMA_API_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "180"))
planner_model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
search_model = os.environ.get("OLLAMA_TOOL_MODEL", "qwen2.5:3b")
classifier_model = os.environ.get("OLLAMA_CLASSIFIER_MODEL", "qwen2.5:3b")

client = OpenAI(base_url=OLLAMA_API_URL, api_key="ollama", timeout=OLLAMA_TIMEOUT)


def load_prompt(prompt_name: str) -> str:
    """Loads a prompt template file from the prompts directory."""
    filename = prompt_name if prompt_name.endswith(".txt") else f"{prompt_name}.txt"
    prompt_path = pathlib.Path(__file__).resolve().parent.parent / "prompts" / filename
    return prompt_path.read_text(encoding="utf-8").strip()


def _format_messages(prompt: str, system_prompt: str | None = None) -> list[dict[str, str]]:
    """Formats prompt and optional system_prompt as standard message dicts."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def prompt_text(
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    temperature: float = 0.0,
) -> str:
    """Prompts the AI model to generate a plain-text response."""
    messages = _format_messages(prompt, system_prompt=system_prompt)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


def calculate_confidence_category(
    logprobs_content: list[Any] | None,
) -> ConfidenceCategory:
    """
    Calculates the confidence category ('High', 'Medium', 'Low') from token log probabilities
    returned directly by Ollama, ensuring the LLM does not fabricate confidence.
    """
    if not logprobs_content:
        return "Medium"

    token_probs = [
        math.exp(getattr(token_info, "logprob", 0.0))
        for token_info in logprobs_content
        if getattr(token_info, "logprob", None) is not None
    ]

    if not token_probs:
        return "Medium"

    avg_prob = sum(token_probs) / len(token_probs)
    if avg_prob >= 0.70:
        return "High"
    elif avg_prob >= 0.40:
        return "Medium"
    return "Low"


def prompt_text_and_calculate_confidence(
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    temperature: float = 0.0,
) -> tuple[str, ConfidenceCategory]:
    """
    Prompts Ollama with logprobs enabled to generate text, then calculates
    the model confidence category directly from token log probabilities.
    """
    messages = _format_messages(prompt, system_prompt=system_prompt)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        logprobs=True,
    )
    choice = resp.choices[0]
    content = (choice.message.content or "").strip()

    logprobs_obj = getattr(choice, "logprobs", None)
    logprobs_content = getattr(logprobs_obj, "content", None) if logprobs_obj else None
    confidence_category = calculate_confidence_category(logprobs_content)

    return content, confidence_category


def prompt_json(
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Prompts the AI model with JSON mode enabled and parses the JSON response into a dict."""
    messages = _format_messages(prompt, system_prompt=system_prompt)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    content = (resp.choices[0].message.content or "").strip()
    return json.loads(content)


def prompt_structured_schema(
    prompt: str,
    schema: dict[str, Any],
    model: str,
    system_prompt: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Prompts the AI model with grammar-constrained JSON schema decoding and returns the parsed dict."""
    messages = _format_messages(prompt, system_prompt=system_prompt)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "StructuredOutput",
                "schema": schema,
            },
        },
    )
    content = (resp.choices[0].message.content or "").strip()
    return json.loads(content)


def prompt_tool_call(
    prompt: str | list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
    system_prompt: str | None = None,
    temperature: float = 0.0,
) -> tuple[str, dict[str, Any], str]:
    """
    Prompts the AI model with available tools to select an appropriate tool and arguments.
    Accepts either a string prompt or an existing list of message dicts for multi-turn loops.
    Returns a tuple of (tool_name, arguments_dict, tool_call_id).
    """
    if isinstance(prompt, list):
        messages = prompt
    else:
        messages = _format_messages(prompt, system_prompt=system_prompt)

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        tools=tools,
        tool_choice="required",
    )
    choice = resp.choices[0]
    tool_calls = getattr(choice.message, "tool_calls", None)
    if not tool_calls:
        return "", {}, "call_1"

    tool_call = tool_calls[0]
    tool_call_id = str(getattr(tool_call, "id", "call_1") or "call_1")
    tool_name = str(getattr(getattr(tool_call, "function", None), "name", "") or "")
    tool_args_str = getattr(getattr(tool_call, "function", None), "arguments", "{}") or "{}"
    try:
        tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
    except Exception:
        tool_args = {}

    return tool_name, tool_args, tool_call_id


def execute_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | list[dict[str, Any]] | Any:
    """Executes a tool on the FastMCP server with the given arguments and returns the result data."""
    async def _call():
        async with Client(MCP_SERVER_URL) as mcp_client:
            res = await mcp_client.call_tool(tool_name, arguments=arguments)
            return res.data

    return asyncio.run(_call())


def fetch_mcp_tools() -> list[dict[str, Any]]:
    """Fetches tool definitions dynamically from the FastMCP server and converts them to OpenAI format."""
    async def _fetch():
        async with Client(MCP_SERVER_URL) as mcp_client:
            tools = await mcp_client.list_tools()
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.input_schema,
                    },
                }
                for tool in tools
            ]

    try:
        return asyncio.run(_fetch())
    except Exception:
        return []
