"""Parse one safe transaction operation from Ollama."""

import json
import math
import re
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import requests

from . import config


KEYS = {
    "operation", "transaction_id", "fields", "filters", "calculation",
    "handoff", "reply",
}
OPERATIONS = {"create", "read", "update", "delete"}
CALCULATIONS = {"none", "count", "sum", "average", "largest"}
HANDOFFS = {"none"}
FIELDS = {
    "date", "merchant", "description", "amount", "category", "category_id",
}
FILTERS = {
    "q", "date", "dates", "date_from", "date_to", "since", "merchant",
    "category", "category_id", "min_amount", "max_amount",
}
DATE_FILTERS = {"date", "dates", "date_from", "date_to", "since"}
DATE_INTENT = re.compile(
    r"\b(?:"
    r"today|tonight|yesterday|tomorrow|"
    r"(?:this|last|previous|past|next)\s+"
    r"(?:day|week|fortnight|month|quarter|year)s?|"
    r"(?:last|past|next)\s+\d+\s+"
    r"(?:day|week|fortnight|month|quarter|year)s?|"
    r"since|before|after|between|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december"
    r")\b|"
    r"\b(?:19|20)\d{2}(?:-\d{1,2}(?:-\d{1,2})?)?\b|"
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    re.IGNORECASE,
)
LIST_INTENT = re.compile(
    r"\b(?:list|show|find)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?"
    r"(?:purchases|transactions|expenses)\b",
    re.IGNORECASE,
)
RANKING_INTENT = re.compile(
    r"\b(?:biggest|largest|highest|most expensive)\b",
    re.IGNORECASE,
)
AMOUNT_BETWEEN = re.compile(
    r"\bbetween\s+\$?([0-9][0-9,]*(?:\.\d{1,2})?)\s+and\s+"
    r"\$?([0-9][0-9,]*(?:\.\d{1,2})?)\b",
    re.IGNORECASE,
)
MIN_AMOUNT = re.compile(
    r"\b(at least|more than|greater than|over|above)\s+"
    r"\$?([0-9][0-9,]*(?:\.\d{1,2})?)\b",
    re.IGNORECASE,
)
MAX_AMOUNT = re.compile(
    r"\b(at most|less than|under|below)\s+"
    r"\$?([0-9][0-9,]*(?:\.\d{1,2})?)\b",
    re.IGNORECASE,
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
MONTH_NAMES = "|".join(MONTHS)
DAY_MONTH = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{MONTH_NAMES})(?:\s+(?P<year>\d{{4}}))?\b",
    re.IGNORECASE,
)
MONTH_DAY = re.compile(
    rf"\b(?P<month>{MONTH_NAMES})\s+"
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?"
    rf"(?:,?\s+(?P<year>\d{{4}}))?\b",
    re.IGNORECASE,
)
DATE_RANGE_INTENT = re.compile(
    r"\bbetween\b|\bfrom\b.+\b(?:to|through|until)\b",
    re.IGNORECASE,
)
CATEGORY_ALIASES = {
    "Dining": re.compile(
        r"\b(?:eating|dining)\s+out\b|\brestaurants?\b",
        re.IGNORECASE,
    ),
    "Groceries": re.compile(
        r"\bgrocer(?:y|ies)\b|\bsupermarkets?\b",
        re.IGNORECASE,
    ),
}
FALLBACK = {
    "operation": "read",
    "transaction_id": None,
    "fields": {},
    "filters": {},
    "calculation": "none",
    "handoff": "none",
    "reply": "I could not safely understand that request. No changes were made.",
}


def parse_chat(message, transactions, categories):
    error = None
    for _attempt in range(2):
        try:
            response = requests.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={
                    "model": config.CHAT_MODEL,
                    "messages": _messages(message, transactions, categories, error),
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0},
                },
                timeout=config.AI_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = json.loads(response.json()["message"]["content"])
        except requests.RequestException as request_error:
            return {
                **FALLBACK,
                "reply": (
                    "Tally could not reach the AI service. "
                    "No changes were made."
                ),
                "fallback": True,
            }
        except (KeyError, TypeError, ValueError, RecursionError) as response_error:
            error = str(response_error)
            continue

        error = validate_chat_response(data, categories)
        if error is None:
            data = _normalize_read_query(data, message, categories)
            error = _semantic_error(data, message)
        if error is None:
            return {**data, "fallback": False}
    return {**FALLBACK, "fallback": True}


def validate_chat_response(data, categories=()):
    if not isinstance(data, dict):
        return "response must be a JSON object"
    if missing := sorted(KEYS - set(data)):
        return f"missing keys: {', '.join(missing)}"
    if unknown := sorted(set(data) - KEYS):
        return f"unsupported keys: {', '.join(unknown)}"

    operation = data["operation"]
    transaction_id = data["transaction_id"]
    fields = data["fields"]
    filters = data["filters"]
    calculation = data["calculation"]
    if operation not in OPERATIONS:
        return f"operation must be one of {sorted(OPERATIONS)}"
    if transaction_id is not None and not _positive_id(transaction_id):
        return "transaction_id must be a positive integer or null"
    if not isinstance(fields, dict) or not isinstance(filters, dict):
        return "fields and filters must be JSON objects"
    if unknown := sorted(set(fields) - FIELDS):
        return f"unsupported fields: {', '.join(unknown)}"
    if unknown := sorted(set(filters) - FILTERS):
        return f"unsupported filters: {', '.join(unknown)}"
    if _invalid_calculation(calculation):
        return (
            "calculation must be count, sum, average, largest, none, "
            "or a unique list"
        )
    if data["handoff"] not in HANDOFFS:
        return f"handoff must be one of {sorted(HANDOFFS)}"
    if not _one_line(data["reply"], 300):
        return "reply must be one non-empty line of at most 300 characters"

    for source, keys in (
        (fields, {"date", "merchant", "description", "category"}),
        (
            filters,
            {
                "q", "date", "date_from", "date_to", "since", "merchant",
                "category",
            },
        ),
    ):
        if any(value is not None and not _one_line(value) for key in keys if (value := source.get(key)) is not None):
            return "text fields must be non-empty strings"
    for source, keys in (
        (fields, {"amount"}),
        (filters, {"min_amount", "max_amount"}),
    ):
        if any(value is not None and not _number(value) for key in keys if (value := source.get(key)) is not None):
            return "amount fields must be finite numbers"
    for source in (fields, filters):
        value = source.get("category_id")
        if value is not None and not _positive_id(value):
            return "category_id must be a positive integer"
    dates = filters.get("dates")
    if dates is not None and (
        not isinstance(dates, list)
        or not dates
        or len(dates) > 31
        or any(not _iso_date(value) for value in dates)
        or len(dates) != len(set(dates))
    ):
        return "dates must be a unique list of 1 to 31 ISO dates"
    for key in ("date", "date_from", "date_to", "since"):
        value = filters.get(key)
        if value is not None and not _iso_date(value):
            return f"{key} must be an ISO date"
    if error := _category_error(fields, filters, categories):
        return error
    exact_date_filters = (
        filters.get("date") is not None,
        filters.get("dates") is not None,
    )
    if sum(exact_date_filters) > 1 or (
        any(exact_date_filters)
        and any(
            filters.get(key) is not None
            for key in ("date_from", "date_to", "since")
        )
    ):
        return (
            "date or dates cannot be combined with date_from, date_to, "
            "or since"
        )

    if operation == "create":
        if transaction_id is not None:
            return "create must not include transaction_id"
        missing = [
            key for key in ("date", "merchant", "description", "amount")
            if fields.get(key) is None
        ]
        if missing:
            return f"create is missing fields: {', '.join(missing)}"
    if operation == "update" and (
        not fields or (transaction_id is None and not filters)
    ):
        return "update requires fields and transaction_id or filters"
    if operation == "delete":
        if fields:
            return "delete fields must be empty"
        if transaction_id is None and not filters:
            return "delete requires transaction_id or filters"
    return None


def _messages(message, transactions, categories, error):
    prompt = (
        Path(__file__).resolve().parent / "prompts" / "chat_prompt.txt"
    ).read_text(encoding="utf-8").strip()
    today = date.today()
    last_week_end = today - timedelta(days=today.weekday() + 1)
    last_week_start = last_week_end - timedelta(days=6)
    august_year = today.year if today.month >= 8 else today.year - 1
    august_start = date(august_year, 8, 1)
    august_end = date(
        august_year,
        8,
        monthrange(august_year, 8)[1],
    )
    june_year = today.year if (today.month, today.day) >= (6, 10) else today.year - 1
    june_tenth = date(june_year, 6, 10)
    july_year = today.year if (today.month, today.day) >= (7, 15) else today.year - 1
    july_fifteenth = date(july_year, 7, 15)
    context = (
        f"{prompt}\n\nToday: {today.isoformat()}."
        f"\nPrevious calendar week: {last_week_start.isoformat()} "
        f"to {last_week_end.isoformat()}."
        f"\nCategories: {json.dumps(categories, separators=(',', ':'))}"
        f"\nRecent transactions: "
        f"{json.dumps(_transaction_context(transactions), separators=(',', ':'))}"
    )
    examples = [
        (
            "What did I spend at Woolworths in August?",
            {
                "operation": "read",
                "transaction_id": None,
                "fields": {},
                "filters": {
                    "date_from": august_start.isoformat(),
                    "date_to": august_end.isoformat(),
                    "merchant": "Woolworths",
                },
                "calculation": "sum",
                "handoff": "none",
                "reply": "I will total your August Woolworths transactions.",
            },
        ),
        (
            "Show my biggest purchases in August",
            {
                "operation": "read",
                "transaction_id": None,
                "fields": {},
                "filters": {
                    "date_from": august_start.isoformat(),
                    "date_to": august_end.isoformat(),
                },
                "calculation": "largest",
                "handoff": "none",
                "reply": "I will rank your August purchases by amount.",
            },
        ),
        (
            "How much did eating out cost me last week?",
            {
                "operation": "read",
                "transaction_id": None,
                "fields": {},
                "filters": {
                    "date_from": last_week_start.isoformat(),
                    "date_to": last_week_end.isoformat(),
                    "category": "Dining",
                },
                "calculation": "sum",
                "handoff": "none",
                "reply": "I will total your Dining transactions from last week.",
            },
        ),
        (
            "List all purchases spent on the 10th June",
            {
                "operation": "read",
                "transaction_id": None,
                "fields": {},
                "filters": {"date": june_tenth.isoformat()},
                "calculation": "none",
                "handoff": "none",
                "reply": "I will list every purchase from 10 June.",
            },
        ),
        (
            "List all purchases spent on the 10th June and the 15th July",
            {
                "operation": "read",
                "transaction_id": None,
                "fields": {},
                "filters": {
                    "dates": [
                        june_tenth.isoformat(),
                        july_fifteenth.isoformat(),
                    ],
                },
                "calculation": "none",
                "handoff": "none",
                "reply": "I will list purchases from both requested dates.",
            },
        ),
        (
            "List all purchases spent with Anytime Fitness",
            {
                "operation": "read",
                "transaction_id": None,
                "fields": {},
                "filters": {"q": "Anytime Fitness"},
                "calculation": "none",
                "handoff": "none",
                "reply": "I will find merchant or description matches.",
            },
        ),
        (
            "List all purchases over $100",
            {
                "operation": "read",
                "transaction_id": None,
                "fields": {},
                "filters": {"min_amount": 100.01},
                "calculation": "none",
                "handoff": "none",
                "reply": "I will list purchases over $100.",
            },
        ),
        (
            "How many Dining purchases are there?",
            {
                "operation": "read",
                "transaction_id": None,
                "fields": {},
                "filters": {"category": "Dining"},
                "calculation": "count",
                "handoff": "none",
                "reply": "I will count Dining purchases.",
            },
        ),
    ]
    messages = [
        {"role": "system", "content": context},
    ]
    for example_message, example_response in examples:
        messages.extend([
            {"role": "user", "content": example_message},
            {
                "role": "assistant",
                "content": json.dumps(
                    example_response,
                    separators=(",", ":"),
                ),
            },
        ])
    messages.append({"role": "user", "content": message})
    if error:
        messages.append({
            "role": "user",
            "content": f"Invalid response: {error}. Return corrected JSON only.",
        })
    return messages


def _transaction_context(transactions):
    return [
        {
            "id": item["id"],
            "date": item["date"],
            "merchant": item["merchant"],
            "description": item["description"],
            "amount": item["amount"],
            "category": item["category_name"],
        }
        for item in transactions[:12]
    ]


def _category_error(fields, filters, categories):
    ids = {item["id"] for item in categories}
    names = {item["name"].casefold() for item in categories}
    for source in (fields, filters):
        if source.get("category_id") is not None and source["category_id"] not in ids:
            return "category_id must match an available category"
        if source.get("category") is not None and source["category"].strip().casefold() not in names:
            return "category must match an available category"
    return None


def _normalize_read_query(data, message, categories):
    if data["operation"] != "read":
        return data

    normalized = {
        **data,
        "filters": dict(data["filters"]),
    }
    if LIST_INTENT.search(message) and not RANKING_INTENT.search(message):
        normalized["calculation"] = "none"

    date_filters = _date_filters(message)
    if date_filters:
        for key in DATE_FILTERS:
            normalized["filters"].pop(key, None)
        normalized["filters"].update(date_filters)

    amount_filters = _amount_filters(message)
    for key in ("min_amount", "max_amount"):
        normalized["filters"].pop(key, None)
    normalized["filters"].update(amount_filters)

    category = _category_in_message(message, categories)
    if category is not None:
        normalized["filters"].pop("category_id", None)
        normalized["filters"]["category"] = category
    else:
        _remove_unmentioned_category(
            normalized["filters"],
            message,
            categories,
        )
    return normalized


def _date_filters(message):
    matches = []
    for pattern in (DAY_MONTH, MONTH_DAY):
        for match in pattern.finditer(message):
            month = MONTHS[match.group("month").casefold()]
            day = int(match.group("day"))
            year = match.group("year")
            try:
                value = _resolve_date(month, day, year)
            except ValueError:
                continue
            matches.append((match.start(), value))
    dates = []
    for _position, value in sorted(matches):
        iso_date = value.isoformat()
        if iso_date not in dates:
            dates.append(iso_date)
    if not dates:
        return {}
    if len(dates) > 1:
        if DATE_RANGE_INTENT.search(message):
            return {
                "date_from": min(dates),
                "date_to": max(dates),
            }
        return {"dates": dates}

    value = dates[0]
    if re.search(r"\bsince\b", message, re.IGNORECASE):
        return {"since": value}
    if re.search(r"\b(?:after|from)\b", message, re.IGNORECASE):
        return {"date_from": value}
    if re.search(r"\b(?:before|until)\b", message, re.IGNORECASE):
        return {"date_to": value}
    return {"date": value}


def _resolve_date(month, day, year):
    if year is not None:
        return date(int(year), month, day)
    today = date.today()
    value = date(today.year, month, day)
    return value if value <= today else date(today.year - 1, month, day)


def _amount_filters(message):
    if match := AMOUNT_BETWEEN.search(message):
        first = _amount(match.group(1))
        second = _amount(match.group(2))
        return {
            "min_amount": min(first, second),
            "max_amount": max(first, second),
        }

    filters = {}
    if match := MIN_AMOUNT.search(message):
        amount = _amount(match.group(2))
        filters["min_amount"] = (
            amount
            if match.group(1).casefold() == "at least"
            else round(amount + 0.01, 2)
        )
    if match := MAX_AMOUNT.search(message):
        amount = _amount(match.group(2))
        filters["max_amount"] = (
            amount
            if match.group(1).casefold() == "at most"
            else round(amount - 0.01, 2)
        )
    return filters


def _amount(value):
    return float(value.replace(",", ""))


def _category_in_message(message, categories):
    category_names = {item["name"]: item["name"] for item in categories}
    for name, pattern in CATEGORY_ALIASES.items():
        if name in category_names and pattern.search(message):
            return name
    for category in sorted(
        categories,
        key=lambda item: len(item["name"]),
        reverse=True,
    ):
        name = re.escape(category["name"])
        patterns = (
            rf"\b{name}\s+(?:purchases?|transactions?|spend|spending|expenses?)\b",
            rf"\b(?:category|on|for|in)\s+{name}\b",
        )
        if any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns):
            return category["name"]
    return None


def _remove_unmentioned_category(filters, message, categories):
    category_name = filters.get("category")
    if category_name is None and filters.get("category_id") is not None:
        category_name = next(
            (
                item["name"]
                for item in categories
                if item["id"] == filters["category_id"]
            ),
            None,
        )
    if category_name is None or _words_overlap(category_name, message):
        return
    filters.pop("category", None)
    filters.pop("category_id", None)


def _words_overlap(value, message):
    words = {
        word
        for word in re.findall(r"[a-z0-9]+", value.casefold())
        if len(word) >= 3
    }
    message_words = set(re.findall(r"[a-z0-9]+", message.casefold()))
    return bool(words & message_words)


def _semantic_error(data, message):
    has_date_filter = any(
        data["filters"].get(key) is not None
        for key in DATE_FILTERS
    )
    if has_date_filter and not DATE_INTENT.search(message):
        return (
            "date filters require a date or time period in the user request; "
            "remove date_from, date_to, and since"
        )
    return None


def _iso_date(value):
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _invalid_calculation(value):
    if isinstance(value, str):
        return value not in CALCULATIONS
    return (
        not isinstance(value, list)
        or not value
        or len(value) > 4
        or len(value) != len(set(value))
        or any(item not in CALCULATIONS - {"none"} for item in value)
    )


def _positive_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _one_line(value, maximum=None):
    return (
        isinstance(value, str)
        and bool(value.strip())
        and "\n" not in value
        and "\r" not in value
        and (maximum is None or len(value) <= maximum)
    )
