import asyncio
from datetime import date
import json
import os
import pathlib
from typing import Any, List
from fastmcp import Client
from openai import OpenAI
from shared.backend import dto
from .helpers import fetch_categories, fetch_feedbacks, fetch_goals, fetch_suggestions
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/mcp")
url = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
timeout = float(os.environ.get("OLLAMA_TIMEOUT", "180"))
model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
search_model = os.environ.get("OLLAMA_TOOL_MODEL", "qwen2.5:3b")

client = OpenAI(base_url=url, api_key="ollama", timeout=timeout)


def load_prompt(prompt_name: str) -> str:
    filename = prompt_name if prompt_name.endswith(".txt") else f"{prompt_name}.txt"
    prompt_path = pathlib.Path(__file__).resolve().parent.parent / "prompts" / filename
    if prompt_path.is_file():
        return prompt_path.read_text(encoding="utf-8").strip()
    return ""


def format_planner_prompt(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
) -> str:
    def format_amount(val: Any) -> str:
        try:
            return f"${float(val):.2f}"
        except Exception:
            return f"${val}"

    past_suggestions = []
    for s in (suggestions or []):
        s_text = getattr(s, "suggestion", s.get("suggestion", "") if isinstance(s, dict) else "")
        s_acc = getattr(s, "accepted", s.get("accepted", False) if isinstance(s, dict) else False)
        s_fb = getattr(s, "feedback", s.get("feedback", None) if isinstance(s, dict) else None)
        status = "ACCEPTED" if s_acc else "REJECTED"
        if s_fb:
            past_suggestions.append(f'[{status}] "{s_text}" -> Feedback: "{s_fb}"')
        else:
            past_suggestions.append(f'[{status}] "{s_text}"')

    tables = {
        "active_goals": [
            {
                "goal": getattr(g, "name", g.get("name", "") if isinstance(g, dict) else ""),
                "target_amount": format_amount(getattr(g, "cost", g.get("cost", 0) if isinstance(g, dict) else 0)),
                "deadline": str(getattr(g, "date", g.get("date", "") if isinstance(g, dict) else ""))[:10],
            }
            for g in (goals or [])
        ],
        "past_suggestions": past_suggestions,
        "general_user_preferences": [
            {
                "rule": getattr(f, "feedback", f.get("feedback", "") if isinstance(f, dict) else ""),
            }
            for f in (feedbacks or [])
            if getattr(f, "suggestion_id", f.get("suggestion_id") if isinstance(f, dict) else None) is None
        ],
    }

    return f"User Financial Data:\n{json.dumps(tables, indent=2)}"


def call_mcp_server(name: str, arguments: dict) -> list:
    """Invokes a tool on the MCP server using FastMCP Client."""
    async def _call():
        async with Client(MCP_SERVER_URL) as client:
            res = await client.call_tool(name, arguments=arguments)
            return res.data

    return asyncio.run(_call())


def fetch_mcp_tools() -> list[dict]:
    """Fetches tool definitions dynamically from the FastMCP server and converts them to OpenAI format."""
    async def _fetch():
        async with Client(MCP_SERVER_URL) as client:
            tools = await client.list_tools()
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


def generate_transaction_search_args(feedbacks: List[dto.Feedback]) -> dict:
    tools = fetch_mcp_tools()
    if not tools:
        return {}

    categories = fetch_categories()
    today_str = os.environ.get("DEMO_TODAY", date.today().isoformat())
    feedback_text = "\n".join(f"- {f.feedback}" for f in feedbacks if getattr(f, "feedback", None))
    category_guideline = f"Valid categories are: {', '.join(categories)}. " if categories else ""
    search_prompt = (
        f"Today is {today_str}. Call search_transactions to inspect transactions.\n"
        "Guidelines:\n"
        "- Dates: If user feedback specifies a timeframe, adhere strictly to that preference; otherwise use a 3 to 6 month date range up to today.\n"
        f"- Categories: {category_guideline}"
        "Do NOT specify category_name unless the user explicitly requested to focus on a valid category in their feedback. "
        "Merchants (such as Spotify, Netflix, Anytime Fitness) are NOT category names. "
        "If no valid category preference was requested by the user, omit category_name completely so all transactions are retrieved."
    )
    if feedback_text:
        search_prompt += f"\nUser feedback preferences:\n{feedback_text}"

    if categories:
        for t in tools:
            if t.get("function", {}).get("name") == "search_transactions":
                t["function"]["parameters"].setdefault("properties", {}).setdefault("category_name", {})["enum"] = categories

    resp = client.chat.completions.create(
        model=search_model,
        messages=[{"role": "user", "content": search_prompt}],
        tools=tools,
        tool_choice="required",
        temperature=0.2,
    )

    tool_call = resp.choices[0].message.tool_calls[0]
    tool_args = json.loads(tool_call.function.arguments)
    if categories and tool_args.get("category_name") not in categories:
        tool_args.pop("category_name", None)
    return {k: v for k, v in tool_args.items() if v is not None and v != ""}


def generate_advice(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
) -> str:
    user_data = format_planner_prompt(goals, suggestions, feedbacks)

    # 1. Lower parameter model (qwen2.5:3b) determines dates and calls search_transactions tool
    search_args = generate_transaction_search_args(feedbacks)

    # 2. Call the MCP server over HTTP
    transactions = call_mcp_server("search_transactions", search_args)
    if not transactions:
        return "You don't have any transactions yet. Add transactions using the transactions tab."

    # 3. 8B model generates the final advice sentences
    system_prompt = load_prompt("savings_prompt.txt")
    advice_resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"{user_data}\n\n"
                    f"Retrieved Transactions from MCP search_transactions:\n{json.dumps(transactions, indent=2)}\n\n"
                    "Deliver 1 or 2 natural, well-phrased savings advice sentences that help the user reduce expenses toward an active goal, starting immediately with the first word of the advice."
                ),
            },
        ],
        temperature=0.4,
    )
    return (advice_resp.choices[0].message.content or "").strip()


def generate_savings_advice(db_url: str) -> str:
    goals = fetch_goals(db_url)
    if not goals:
        return (
            "You don't have any active savings goals yet. "
            "Add a goal in the Savings Goals table to receive personalized, adaptive savings advice!"
        )

    feedbacks = fetch_feedbacks(db_url)
    suggestions = fetch_suggestions(db_url)

    try:
        advice = generate_advice(goals, suggestions, feedbacks)
        if advice:
            return advice
        return "Error: Could not generate AI savings suggestion (empty response received from AI model)."
    except Exception as e:
        return f"Error: Could not generate AI savings suggestion ({e})."
