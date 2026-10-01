"""Planner parsing, validation and grounding in ollama_service."""

import json
from datetime import date
from unittest.mock import Mock

import requests
from pytest import fixture, mark

from janelle.backend.services import ollama_service


VALID_RESPONSE = {
    "operation": "read",
    "transaction_id": None,
    "fields": {},
    "filters": {"merchant": "Merivale"},
    "calculation": ["count", "average"],
    "handoff": "none",
    "reply": "I will calculate that from matching transactions.",
}
DINING = [{"id": 80, "name": "Dining", "type": "want"}]


def ollama_response(payload):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "message": {
            "content": (
                payload if isinstance(payload, str) else json.dumps(payload)
            )
        }
    }
    return response


@fixture
def ollama(monkeypatch):
    """Fake Ollama; call with the replies (payloads or exceptions) in order."""
    post = Mock()
    monkeypatch.setattr(ollama_service.requests, "post", post)

    def respond(*replies):
        post.side_effect = [
            reply if isinstance(reply, Exception) else ollama_response(reply)
            for reply in replies
        ]
        return post

    return respond


def past_date(month, day):
    """The most recent occurrence of a day/month, as the planner grounds it."""
    today = date.today()
    value = date(today.year, month, day)
    return value if value <= today else date(today.year - 1, month, day)


# --- retry state machine ----------------------------------------------------


def test_parser_accepts_valid_first_response(ollama):
    post = ollama(VALID_RESPONSE)

    result = ollama_service.parse_chat("Show Merivale", [], [])

    assert result == {**VALID_RESPONSE, "fallback": False}
    assert post.call_count == 1
    payload = post.call_args.kwargs["json"]
    assert payload["options"]["temperature"] == 0
    assert f"Today: {date.today().isoformat()}." in payload["messages"][0]["content"]


def test_parser_retries_once_with_validation_error(ollama):
    post = ollama({"operation": "delete"}, VALID_RESPONSE)

    result = ollama_service.parse_chat("Show Merivale", [], [])

    assert result["fallback"] is False
    assert post.call_count == 2
    retry_messages = post.call_args_list[1].kwargs["json"]["messages"]
    assert "missing keys" in retry_messages[-1]["content"]


def test_parser_fails_closed_after_two_invalid_responses(ollama):
    post = ollama("not json", "not json")

    result = ollama_service.parse_chat("Delete everything", [], [])

    assert result == {**ollama_service.FALLBACK, "fallback": True}
    assert post.call_count == 2


def test_parser_fails_closed_when_ollama_is_unavailable(ollama):
    post = ollama(requests.ConnectionError("unavailable"))

    result = ollama_service.parse_chat("Anything", [], [])

    assert result["fallback"] is True
    assert post.call_count == 1
    assert "AI service" in result["reply"]


# --- schema validation ------------------------------------------------------


@mark.parametrize(
    ("overrides", "expected_error"),
    [
        (
            {"operation": "delete", "filters": {}, "calculation": "none"},
            "delete requires transaction_id or filters",
        ),
        (
            {
                "operation": "update",
                "transaction_id": 27,
                "fields": {"status": "approved"},
                "calculation": "none",
            },
            "unsupported fields: status",
        ),
        (
            {"filters": {"dates": [{"date": "2026-06-10"}]}, "calculation": "none"},
            "dates must be a unique list of 1 to 31 ISO dates",
        ),
        (
            {"calculation": "cheapest"},
            "calculation must be count, sum, average, largest, "
            "smallest, none, or a unique list",
        ),
    ],
)
def test_chat_schema_rejects_unsafe_shapes(overrides, expected_error):
    assert ollama_service.validate_chat_response(
        {**VALID_RESPONSE, **overrides}
    ) == expected_error


def test_chat_schema_accepts_ranking_calculations():
    for calculation in ("largest", "smallest"):
        assert ollama_service.validate_chat_response(
            {**VALID_RESPONSE, "calculation": calculation}
        ) is None


# --- semantic date guard ----------------------------------------------------


def test_parser_retries_date_filters_not_requested_by_user(ollama):
    invented_dates = {
        **VALID_RESPONSE,
        "filters": {
            "merchant": "Anytime Fitness Ultimo",
            "date_from": "2026-08-24",
            "date_to": "2026-08-30",
        },
        "calculation": "none",
    }
    corrected = {
        **invented_dates,
        "filters": {"merchant": "Anytime Fitness Ultimo"},
    }
    post = ollama(invented_dates, corrected)

    result = ollama_service.parse_chat(
        "List all purchases with Anytime Fitness Ultimo", [], []
    )

    assert result == {**corrected, "fallback": False}
    assert post.call_count == 2
    retry_messages = post.call_args_list[1].kwargs["json"]["messages"]
    assert "date filters require a date" in retry_messages[-1]["content"]


@mark.parametrize(
    ("message", "filters"),
    [
        (
            "What did I spend at Merivale last week?",
            {
                "merchant": "Merivale",
                "date_from": "2026-08-24",
                "date_to": "2026-08-30",
            },
        ),
        (
            "List all purchases spent on the 10th June",
            {"date": past_date(6, 10).isoformat()},
        ),
    ],
)
def test_parser_accepts_date_filters_the_user_asked_for(ollama, message, filters):
    dated = {**VALID_RESPONSE, "filters": filters, "calculation": "none"}
    post = ollama(dated)

    result = ollama_service.parse_chat(message, [], [])

    assert result == {**dated, "fallback": False}
    assert post.call_count == 1


# --- read query normalisation -----------------------------------------------


@mark.parametrize(
    ("message", "planned_calculation", "expected_filters"),
    [
        ("List all purchases over $100", "sum", {"min_amount": 100.01}),
        (
            "List transactions between $20 and $100",
            "none",
            {"min_amount": 20.0, "max_amount": 100.0},
        ),
        ("List transactions under $20", "none", {"max_amount": 19.99}),
    ],
)
def test_parser_normalizes_list_intent_and_amount_bounds(
    ollama, message, planned_calculation, expected_filters
):
    ollama({**VALID_RESPONSE, "filters": {}, "calculation": planned_calculation})

    result = ollama_service.parse_chat(message, [], [])

    assert result["filters"] == expected_filters
    assert result["calculation"] == "none"
    assert result["fallback"] is False


def test_parser_normalizes_multiple_dates_and_removes_copied_category(ollama):
    ollama({
        **VALID_RESPONSE,
        "filters": {"date": "2026-07-15", "category": "Dining"},
        "calculation": "none",
    })

    result = ollama_service.parse_chat(
        "List all purchases spent on the 10th June and the 15th July",
        [],
        DINING,
    )

    assert result["filters"] == {
        "dates": [past_date(6, 10).isoformat(), past_date(7, 15).isoformat()],
    }
    assert result["calculation"] == "none"
    assert result["fallback"] is False


def test_parser_adds_explicit_named_category_to_read_query(ollama):
    ollama({**VALID_RESPONSE, "filters": {}, "calculation": "count"})

    result = ollama_service.parse_chat(
        "How many Dining purchases are there?", [], DINING
    )

    assert result["filters"] == {"category": "Dining"}
    assert result["calculation"] == "count"


@mark.parametrize(
    ("message", "expected"),
    [
        (
            "what is the smallest purchase i made in august",
            {
                "date_from": past_date(8, 1).isoformat(),
                "date_to": past_date(8, 1).replace(day=31).isoformat(),
            },
        ),
        (
            "What did I spend at Woolworths in August 2025?",
            {"date_from": "2025-08-01", "date_to": "2025-08-31"},
        ),
        (
            "how much did i spend in Feb 2024",
            {"date_from": "2024-02-01", "date_to": "2024-02-29"},
        ),
        ("what did i buy on 10 June", {"date": past_date(6, 10).isoformat()}),
        (
            "purchases on the 10th June and the 15th July",
            {"dates": [past_date(6, 10).isoformat(), past_date(7, 15).isoformat()]},
        ),
        ("how many transactions do i have", {}),
    ],
)
def test_extract_date_filters_from_month_wording(message, expected):
    assert ollama_service.extract_date_filters(message) == expected


@mark.parametrize(
    ("message", "planned", "expected"),
    [
        ("count my cheapest purchases", ["count", "largest"], ["count", "smallest"]),
        ("show my biggest purchases", "smallest", "largest"),
        ("biggest and smallest purchases", "largest", "largest"),
    ],
)
def test_ranking_direction_follows_the_message_not_the_model(
    message, planned, expected
):
    assert ollama_service.correct_ranking_direction(planned, message) == expected


# --- create grounding -------------------------------------------------------


@mark.parametrize(
    ("message", "expected_error"),
    [
        (
            "Add lunch on 2 September 2026 for $24.50",
            "merchant must be explicitly grounded in the user request",
        ),
        (
            "Add lunch at Atomic Cafe on 2 September 2026",
            "amount must be explicitly grounded in the user request",
        ),
    ],
)
def test_write_grounding_rejects_model_invented_create_fields(
    message, expected_error
):
    plan = {
        **VALID_RESPONSE,
        "operation": "create",
        "fields": {
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
        },
        "filters": {},
        "calculation": "none",
    }

    assert ollama_service.write_grounding_error(plan, message, []) == expected_error


def test_create_plan_keeps_only_fields_grounded_in_the_message(ollama):
    """Invented date/description are dropped; the message's own abbreviated
    date, quoted description, amount and category alias win."""
    ollama({
        "operation": "create",
        "transaction_id": None,
        "fields": {
            "date": "2026-09-02",
            "merchant": "Cat cafe",
            "description": "visit",
            "amount": None,
            "category": "Uncategorised",
        },
        "filters": {},
        "calculation": "none",
        "handoff": "none",
        "reply": "I prepared this transaction for review.",
    })

    result = ollama_service.create_plan(
        "add new transaction for Cat cafe for $25. "
        'Additional details: 29th Aug, description is "Big Chungus Cat"',
        [{"id": 1, "name": "Uncategorised", "type": None}, *DINING],
    )

    assert result["fallback"] is False
    assert result["fields"] == {
        "merchant": "Cat cafe",
        "description": "Big Chungus Cat",
        "amount": 25.0,
        "category": "Dining",
        "date": past_date(8, 29).isoformat(),
    }


def test_create_category_is_explicit_only_with_category_syntax():
    explicit = ollama_service.explicit_category_in_message

    assert explicit("Add lunch for $24.50 in Dining", DINING) == "Dining"
    assert explicit("Add dinner at Dining Room", DINING) is None
    assert explicit("Add dinner at a restaurant", DINING) is None
    assert ollama_service.category_in_message(
        "Add a purchase from Cat Cafe", DINING
    ) == "Dining"
