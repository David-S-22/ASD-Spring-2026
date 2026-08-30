from typing import Any, Optional
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
    if "suggestion" in d and "accepted" in d and (accepted_val := try_parse_bool(d["accepted"])) is not None:
        return dto.Suggestion(
            id=d.get("id"),
            suggestion=d["suggestion"],
            accepted=accepted_val,
        )
    if "feedback" in d:
        return dto.Feedback(id=d.get("id"), feedback=d["feedback"])
    return d

def load_prompt(prompt_to_load) -> str:
    return ""

object_hook = object_to_hook
