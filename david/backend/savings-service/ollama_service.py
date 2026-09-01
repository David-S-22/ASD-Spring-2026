import json
import os
import pathlib
from typing import List, Optional
from openai import OpenAI
from shared.backend import dto
from .helpers import fetch_feedbacks, fetch_goals, fetch_suggestions, fetch_transactions

url = os.environ.get("OLLAMA_URL", "http://ollama:11434/v1")
timeout = float(os.environ.get("OLLAMA_TIMEOUT", "180"))
model = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
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
            for t in (transactions or [])
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


def generate_plan(
    goals: List[dto.Goal],
    suggestions: List[dto.Suggestion],
    feedbacks: List[dto.Feedback],
    transactions: List[dto.Transaction],
) -> str:
    planning_prompt = load_prompt("planning_prompt.txt")
    if not planning_prompt:
        planning_prompt = (
            "You are a financial planner. Analyze the data and return a JSON plan with: "
            "target_category, merchants, suggested_action, estimated_savings, goals."
        )

    user_prompt = format_planner_prompt(goals, suggestions, feedbacks, transactions)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": planning_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=250,
    )
    return (response.choices[0].message.content or "").strip()


def generate_action(plan: str) -> str:
    action_prompt = load_prompt("action_prompt.txt")
    if not action_prompt:
        action_prompt = (
            "You are a personal financial coach. Convert the provided savings plan into "
            "1 or 2 plain text advice sentences directly addressing the user."
        )

    user_prompt = (
        f"Savings Plan:\n{plan}\n\n"
        "Convert this plan into 1 or 2 plain text advice sentences for the user."
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": action_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=150,
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
        plan = generate_plan(goals, suggestions, feedbacks, transactions)
        advice = generate_action(plan)
        if advice:
            return advice
        return "Error: Could not generate AI savings suggestion (empty response received from AI model)."
    except Exception as e:
        return f"Error: Could not generate AI savings suggestion ({e})."
