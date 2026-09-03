import json
import os
import pathlib
from typing import Any, List, Optional
from openai import OpenAI
from shared.backend import dto
from .helpers import fetch_feedbacks, fetch_goals, fetch_suggestions, fetch_transactions

url = os.environ.get("OLLAMA_URL", "http://ollama:11434/v1")
timeout = float(os.environ.get("OLLAMA_TIMEOUT", "180"))
model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
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
    transactions: Optional[List[dto.Transaction]] = None,
) -> str:
    def format_amount(val: Any) -> str:
        try:
            return f"${float(val):.2f}"
        except Exception:
            return f"${val}"

    # Cap transactions at the latest 15 to keep prompt processing fast on CPU
    recent_txs = (transactions or [])[-15:]

    tables = {
        "active_goals": [
            {
                "goal": getattr(g, "name", g.get("name", "") if isinstance(g, dict) else ""),
                "target_amount": format_amount(getattr(g, "cost", g.get("cost", 0) if isinstance(g, dict) else 0)),
                "deadline": str(getattr(g, "date", g.get("date", "") if isinstance(g, dict) else ""))[:10],
            }
            for g in (goals or [])
        ],
        "recent_transactions": [
            {
                "merchant": getattr(t, "merchant", t.get("merchant", "") if isinstance(t, dict) else ""),
                "amount": format_amount(getattr(t, "amount", t.get("amount", 0) if isinstance(t, dict) else 0)),
                "date": str(getattr(t, "date", t.get("date", "") if isinstance(t, dict) else ""))[:10],
            }
            for t in recent_txs
        ],
        "past_suggestions": [
            {
                "suggestion": getattr(s, "suggestion", s.get("suggestion", "") if isinstance(s, dict) else ""),
                "outcome": "Accepted by user" if getattr(s, "accepted", s.get("accepted", False) if isinstance(s, dict) else False) else "Rejected by user",
            }
            for s in (suggestions or [])
        ],
        "user_feedback_rules": [
            {
                "rule": getattr(f, "feedback", f.get("feedback", "") if isinstance(f, dict) else ""),
            }
            for f in (feedbacks or [])
        ],
    }

    return f"User Financial Data:\n{json.dumps(tables, indent=2)}"


def generate_advice(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
    transactions: List[dto.Transaction],
) -> str:
    system_prompt = load_prompt("savings_prompt.txt")
    if not system_prompt:
        system_prompt = (
            "You are a personal financial coach. Analyze the user's financial data "
            "(goals, transactions, past suggestions, feedback rules) and output 1 or 2 "
            "plain text advice sentences directly addressing the user."
        )

    user_prompt = format_planner_prompt(goals, suggestions, feedbacks, transactions)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=250,
    )
    return (response.choices[0].message.content or "").strip()


def generate_savings_advice(
    db_url: str,
    transactions_db_url: str,
) -> str:
    goals = fetch_goals(db_url)
    if not goals:
        return (
            "You don't have any active savings goals yet. "
            "Add a goal in the Savings Goals table to receive personalized, adaptive savings advice!"
        )

    transactions = fetch_transactions(transactions_db_url)
    if not transactions:
        return "You don't have any transactions yet. Add transactions using the transactions tab."

    suggestions = fetch_suggestions(db_url)
    feedbacks = fetch_feedbacks(db_url)

    try:
        advice = generate_advice(goals, suggestions, feedbacks, transactions)
        if advice:
            return advice
        return "Error: Could not generate AI savings suggestion (empty response received from AI model)."
    except Exception as e:
        return f"Error: Could not generate AI savings suggestion ({e})."
