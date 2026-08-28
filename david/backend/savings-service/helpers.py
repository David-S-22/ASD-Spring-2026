from dateutil import parser
from shared.backend import dto


def object_to_hook(d: dict):
    if "name" in d and "cost" in d and "date" in d:
        return dto.Goal(
            id=d.get("id"),
            name=d["name"],
            cost=d["cost"],
            date=parser.parse(d["date"]),
        )
    if "suggestion" in d:
        return dto.Suggestion(id=d.get("id"), suggestion=d["suggestion"])
    if "feedback" in d:
        return dto.Feedback(id=d.get("id"), feedback=d["feedback"])
    return d


object_hook = object_to_hook
