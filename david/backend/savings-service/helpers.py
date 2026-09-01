from typing import Any, List, Optional
import requests
from dateutil import parser
from shared.backend import dto

def try_parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        val_lower = value.strip().lower()
        if val_lower == "true":
            return True
        if val_lower == "false":
            return False
    return None


def object_to_hook(d: dict):
    if "name" in d and "cost" in d and "date" in d:
        return dto.Goal(
            id=d.get("id"),
            name=d["name"],
            cost=d["cost"],
            date=parser.parse(d["date"]),
        )
    if "merchant" in d and "amount" in d and "date" in d:
        return dto.Transaction(
            id=d.get("id"),
            amount=float(d["amount"]),
            merchant=d["merchant"],
            date=parser.parse(d["date"]) if isinstance(d["date"], str) else d["date"],
            description=d.get("description", ""),
            category_id=d.get("category_id", 0),
        )
    if "suggestion" in d and "accepted" in d and (accepted_val := try_parse_bool(d["accepted"])) is not None:
        return dto.Suggestion(
            id=d.get("id"),
            suggestion=d["suggestion"],
            accepted=accepted_val,
        )
    if "feedback" in d:
        return dto.Feedback(id=d.get("id"), feedback=d["feedback"])
    return d


object_hook = object_to_hook


def fetch_goals(db_url: str) -> List[dto.Goal]:
    try:
        resp = requests.get(f"{db_url.rstrip('/')}/goals")
        if resp.ok:
            return resp.json(object_hook=object_to_hook)
    except Exception:
        pass
    return []


def fetch_suggestions(db_url: str) -> List[dto.Suggestion]:
    try:
        resp = requests.get(f"{db_url.rstrip('/')}/suggestions")
        if resp.ok:
            return resp.json(object_hook=object_to_hook)
    except Exception:
        pass
    return []


def fetch_feedbacks(db_url: str) -> List[dto.Feedback]:
    try:
        resp = requests.get(f"{db_url.rstrip('/')}/feedbacks")
        if resp.ok:
            return resp.json(object_hook=object_to_hook)
    except Exception:
        pass
    return []


def fetch_transactions(transactions_db_url: str) -> List[dto.Transaction]:
    try:
        resp = requests.get(f"{transactions_db_url.rstrip('/')}/transactions")
        if resp.ok:
            return resp.json(object_hook=object_to_hook)
    except Exception:
        pass
    return []

