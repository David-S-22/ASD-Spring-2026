import logging
import os
from typing import Any, List, Optional
import requests
from dateutil import parser
from shared.backend import dto

logger = logging.getLogger(__name__)

TRANSACTIONS_DB_URL = os.environ.get("TRANSACTIONS_DB_URL", "http://localhost:6001")

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
            feedback=d.get("feedback"),
        )
    if "feedback" in d:
        return dto.Feedback(
            id=d.get("id"),
            feedback=d["feedback"],
            suggestion_id=d.get("suggestion_id"),
            category_id=d.get("category_id"),
            timeframe=d.get("timeframe"),
        )
    if "name" in d and "id" in d and ("type" in d or "cost" not in d):
        return dto.Category(
            id=d.get("id"),
            name=d["name"],
            type=d.get("type"),
        )
    return d


object_hook = object_to_hook


def fetch_goals(db_url: str) -> List[dto.Goal]:
    try:
        resp = requests.get(f"{db_url.rstrip('/')}/goals", timeout=5)
        if resp.ok:
            return resp.json(object_hook=object_to_hook)
    except Exception as e:
        logger.warning(f"Error fetching goals from {db_url}: {e}")
    return []


def fetch_suggestions(db_url: str) -> List[dto.Suggestion]:
    try:
        resp = requests.get(f"{db_url.rstrip('/')}/suggestions", timeout=5)
        if resp.ok:
            return resp.json(object_hook=object_to_hook)
    except Exception as e:
        logger.warning(f"Error fetching suggestions from {db_url}: {e}")
    return []


def fetch_feedbacks(db_url: str) -> List[dto.Feedback]:
    try:
        resp = requests.get(f"{db_url.rstrip('/')}/feedbacks", timeout=5)
        if resp.ok:
            return resp.json(object_hook=object_to_hook)
    except Exception as e:
        logger.warning(f"Error fetching feedbacks from {db_url}: {e}")
    return []


def fetch_categories(tx_url: Optional[str] = None) -> List[dto.Category]:
    url = (tx_url or TRANSACTIONS_DB_URL).rstrip("/")
    try:
        resp = requests.get(f"{url}/categories", timeout=5)
        if resp.ok:
            data = resp.json(object_hook=object_to_hook)
            categories = []
            for item in data:
                if isinstance(item, dto.Category):
                    category = item
                elif isinstance(item, dict) and "id" in item and "name" in item:
                    category = dto.Category(id=item["id"], name=item["name"], type=item.get("type"))
                else:
                    continue
                if category.name and category.name.strip().lower() != "uncategorised":
                    categories.append(category)
            return categories
    except Exception as e:
        logger.warning(f"Error fetching categories from {url}: {e}")
    return []


