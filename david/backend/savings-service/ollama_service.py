import asyncio
import json
import os
import pathlib
from typing import Any, Optional
from fastmcp import Client
from openai import OpenAI

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/mcp")
OLLAMA_API_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "180"))
planner_model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
search_model = os.environ.get("OLLAMA_TOOL_MODEL", "qwen2.5:3b")
classifier_model = os.environ.get("OLLAMA_CLASSIFIER_MODEL", "qwen2.5:0.5b")

client = OpenAI(base_url=OLLAMA_API_URL, api_key="ollama", timeout=OLLAMA_TIMEOUT)


def load_prompt(prompt_name: str) -> str:
    """Loads a prompt template file from the prompts directory."""
    filename = prompt_name if prompt_name.endswith(".txt") else f"{prompt_name}.txt"
    prompt_path = pathlib.Path(__file__).resolve().parent.parent / "prompts" / filename
    return prompt_path.read_text(encoding="utf-8").strip()


def _format_messages(prompt: str, system_prompt: Optional[str] = None) -> list[dict]:
    """Formats prompt and optional system_prompt as standard message dicts."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def prompt_model(
    prompt: str,
    model: str,
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = 0.0,
) -> Any:
    """Sends a prompt to the AI model and returns its response (as text, or parsed as a JSON dictionary if json_mode=True)."""
    messages = _format_messages(prompt, system_prompt=system_prompt)
    if json_mode:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = (resp.choices[0].message.content or "").strip()
        return json.loads(content)

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


def generate_tool_call_arguments(
    prompt: str,
    tools: list[dict],
    model: str,
    temperature: float = 0.0,
) -> dict:
    """
    Prompts the AI model to inspect the prompt and select input arguments for a tool/function call.

    Instead of generating conversational text, the model evaluates the prompt against
    the provided tool definitions and returns the arguments needed to invoke the tool.
    """
    messages = _format_messages(prompt)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        tools=tools,
        tool_choice="required",
    )
    tool_call = resp.choices[0].message.tool_calls[0]
    return json.loads(tool_call.function.arguments)


def execute_mcp_tool(tool_name: str, arguments: dict) -> list:
    """Executes a tool on the FastMCP server with the given arguments and returns the result data."""
    async def _call():
        async with Client(MCP_SERVER_URL) as mcp_client:
            res = await mcp_client.call_tool(tool_name, arguments=arguments)
            return res.data

    return asyncio.run(_call())


def fetch_mcp_tools() -> list[dict]:
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
