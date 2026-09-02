import json
from datetime import date, timedelta
from unittest.mock import Mock

import requests

from janelle.backend import ollama_service


VALID_RESPONSE = {
    "operation": "read",
    "transaction_id": None,
    "fields": {},
    "filters": {"merchant": "Merivale"},
    "calculation": ["count", "average"],
    "handoff": "none",
    "reply": "I will calculate that from matching transactions.",
}


def ollama_response(payload):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "message": {"content": json.dumps(payload)}
    }
    return response


def test_parser_accepts_valid_first_response(monkeypatch):
    post = Mock(return_value=ollama_response(VALID_RESPONSE))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat("Show Merivale", [], [])

    assert result == {**VALID_RESPONSE, "fallback": False}
    assert post.call_count == 1


def test_parser_uses_date_aware_examples_for_common_questions(monkeypatch):
    post = Mock(return_value=ollama_response(VALID_RESPONSE))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    ollama_service.parse_chat(
        "Show my biggest purchases in August",
        [],
        [{"id": 80, "name": "Dining", "type": "want"}],
    )

    payload = post.call_args.kwargs["json"]
    messages = payload["messages"]
    today = date.today()
    last_week_end = today - timedelta(days=today.weekday() + 1)
    last_week_start = last_week_end - timedelta(days=6)
    august_year = today.year if today.month >= 8 else today.year - 1
    june_year = today.year if (today.month, today.day) >= (6, 10) else today.year - 1
    july_year = today.year if (today.month, today.day) >= (7, 15) else today.year - 1

    assert payload["model"] == "qwen2.5:3b"
    assert payload["options"]["temperature"] == 0
    assert f"Today: {today.isoformat()}." in messages[0]["content"]
    assert (
        f"Previous calendar week: {last_week_start.isoformat()} "
        f"to {last_week_end.isoformat()}."
    ) in messages[0]["content"]
    examples = {
        messages[index]["content"]: json.loads(messages[index + 1]["content"])
        for index in range(1, len(messages) - 1, 2)
    }
    woolworths_example = examples[
        "What did I spend at Woolworths in August?"
    ]
    assert woolworths_example["filters"] == {
        "date_from": f"{august_year}-08-01",
        "date_to": f"{august_year}-08-31",
        "merchant": "Woolworths",
    }
    assert woolworths_example["calculation"] == "sum"
    assert examples[
        "Show my biggest purchases in August"
    ]["calculation"] == "largest"
    dining_example = examples[
        "How much did eating out cost me last week?"
    ]
    assert dining_example["filters"] == {
        "date_from": last_week_start.isoformat(),
        "date_to": last_week_end.isoformat(),
        "category": "Dining",
    }
    assert dining_example["calculation"] == "sum"
    exact_date_example = examples[
        "List all purchases spent on the 10th June"
    ]
    assert exact_date_example["filters"] == {
        "date": f"{june_year}-06-10",
    }
    assert exact_date_example["calculation"] == "none"
    multi_date_example = examples[
        "List all purchases spent on the 10th June and the 15th July"
    ]
    assert multi_date_example["filters"] == {
        "dates": [
            f"{june_year}-06-10",
            f"{july_year}-07-15",
        ],
    }
    assert multi_date_example["calculation"] == "none"
    partial_example = examples[
        "List all purchases spent with Anytime Fitness"
    ]
    assert partial_example["filters"] == {"q": "Anytime Fitness"}
    assert partial_example["calculation"] == "none"
    amount_example = examples["List all purchases over $100"]
    assert amount_example["filters"] == {"min_amount": 100.01}
    assert amount_example["calculation"] == "none"
    category_example = examples["How many Dining purchases are there?"]
    assert category_example["filters"] == {"category": "Dining"}
    assert category_example["calculation"] == "count"


def test_parser_retries_once_with_validation_error(monkeypatch):
    post = Mock(side_effect=[
        ollama_response({"operation": "delete"}),
        ollama_response(VALID_RESPONSE),
    ])
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat("Show Merivale", [], [])

    assert result["fallback"] is False
    assert post.call_count == 2
    retry_messages = post.call_args_list[1].kwargs["json"]["messages"]
    assert "missing keys" in retry_messages[-1]["content"]


def test_parser_retries_date_filters_not_requested_by_user(monkeypatch):
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
    post = Mock(side_effect=[
        ollama_response(invented_dates),
        ollama_response(corrected),
    ])
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat(
        "List all purchases with Anytime Fitness Ultimo",
        [],
        [],
    )

    assert result == {**corrected, "fallback": False}
    assert post.call_count == 2
    retry_messages = post.call_args_list[1].kwargs["json"]["messages"]
    assert "date filters require a date" in retry_messages[-1]["content"]


def test_parser_accepts_date_filters_when_user_requests_period(monkeypatch):
    dated = {
        **VALID_RESPONSE,
        "filters": {
            "merchant": "Merivale",
            "date_from": "2026-08-24",
            "date_to": "2026-08-30",
        },
        "calculation": "sum",
    }
    post = Mock(return_value=ollama_response(dated))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat(
        "What did I spend at Merivale last week?",
        [],
        [],
    )

    assert result == {**dated, "fallback": False}
    assert post.call_count == 1


def test_parser_accepts_exact_date_filter(monkeypatch):
    exact_date = {
        **VALID_RESPONSE,
        "filters": {"date": "2026-06-10"},
        "calculation": "none",
    }
    post = Mock(return_value=ollama_response(exact_date))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat(
        "List all purchases spent on the 10th June",
        [],
        [],
    )

    assert result == {**exact_date, "fallback": False}
    assert post.call_count == 1


def test_parser_normalizes_multiple_dates_and_removes_copied_category(
    monkeypatch,
):
    model_response = {
        **VALID_RESPONSE,
        "filters": {
            "date": "2026-07-15",
            "category": "Dining",
        },
        "calculation": "none",
    }
    post = Mock(return_value=ollama_response(model_response))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat(
        "List all purchases spent on the 10th June and the 15th July",
        [],
        [{"id": 80, "name": "Dining", "type": "want"}],
    )

    assert result["filters"] == {
        "dates": ["2026-06-10", "2026-07-15"],
    }
    assert result["calculation"] == "none"
    assert result["fallback"] is False
    assert post.call_count == 1


def test_parser_normalizes_list_intent_and_amount_bounds(monkeypatch):
    model_response = {
        **VALID_RESPONSE,
        "filters": {},
        "calculation": "sum",
    }
    post = Mock(return_value=ollama_response(model_response))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat(
        "List all purchases over $100",
        [],
        [],
    )

    assert result["filters"] == {"min_amount": 100.01}
    assert result["calculation"] == "none"
    assert result["fallback"] is False


def test_parser_normalizes_between_and_under_amount_bounds(monkeypatch):
    post = Mock(return_value=ollama_response({
        **VALID_RESPONSE,
        "filters": {},
        "calculation": "none",
    }))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    between = ollama_service.parse_chat(
        "List transactions between $20 and $100",
        [],
        [],
    )
    under = ollama_service.parse_chat(
        "List transactions under $20",
        [],
        [],
    )

    assert between["filters"] == {
        "min_amount": 20.0,
        "max_amount": 100.0,
    }
    assert under["filters"] == {"max_amount": 19.99}


def test_parser_adds_explicit_named_category_to_read_query(monkeypatch):
    post = Mock(return_value=ollama_response({
        **VALID_RESPONSE,
        "filters": {},
        "calculation": "count",
    }))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat(
        "How many Dining purchases are there?",
        [],
        [{"id": 80, "name": "Dining", "type": "want"}],
    )

    assert result["filters"] == {"category": "Dining"}
    assert result["calculation"] == "count"
    assert result["fallback"] is False


def test_parser_fails_closed_after_two_invalid_responses(monkeypatch):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "message": {"content": "not json"}
    }
    monkeypatch.setattr(
        ollama_service.requests,
        "post",
        Mock(return_value=response),
    )

    result = ollama_service.parse_chat("Delete everything", [], [])

    assert result == {**ollama_service.FALLBACK, "fallback": True}


def test_parser_fails_closed_when_ollama_is_unavailable(monkeypatch):
    post = Mock(side_effect=requests.ConnectionError("unavailable"))
    monkeypatch.setattr(ollama_service.requests, "post", post)

    result = ollama_service.parse_chat("Anything", [], [])

    assert result["fallback"] is True
    assert post.call_count == 1
    assert "AI service" in result["reply"]


def test_chat_schema_rejects_unsafe_write_shapes():
    missing_target = {
        **VALID_RESPONSE,
        "operation": "delete",
        "filters": {},
        "calculation": "none",
    }
    unknown_field = {
        **VALID_RESPONSE,
        "operation": "update",
        "transaction_id": 27,
        "fields": {"status": "approved"},
        "filters": {},
        "calculation": "none",
    }

    assert ollama_service.validate_chat_response(missing_target) == (
        "delete requires transaction_id or filters"
    )
    assert ollama_service.validate_chat_response(unknown_field) == (
        "unsupported fields: status"
    )


def test_chat_schema_accepts_largest_calculation():
    largest = {
        **VALID_RESPONSE,
        "calculation": "largest",
    }

    assert ollama_service.validate_chat_response(largest) is None


def test_chat_schema_rejects_invalid_multi_date_filter():
    invalid_dates = {
        **VALID_RESPONSE,
        "filters": {"dates": [{"date": "2026-06-10"}]},
        "calculation": "none",
    }

    assert ollama_service.validate_chat_response(invalid_dates) == (
        "dates must be a unique list of 1 to 31 ISO dates"
    )
