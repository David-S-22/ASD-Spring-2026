from datetime import datetime
import pytest
import requests
import responses
from dateutil import parser

from backend.savings_service.helpers import (
    TRANSACTIONS_DB_URL,
    fetch_categories,
    fetch_feedbacks,
    fetch_goals,
    fetch_suggestions,
    object_to_hook,
    try_parse_bool,
)
from shared.backend import dto

TEST_DB_URL = "http://test-db:6002"
TEST_TX_URL = "http://test-tx:6001"


# ============================================================================
# try_parse_bool
# ============================================================================

def test_try_parse_bool_boolean_inputs():
    assert try_parse_bool(True) is True
    assert try_parse_bool(False) is False


@pytest.mark.parametrize(
    "val, expected",
    [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("  true  ", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("  false  ", False),
        ("maybe", None),
        ("1", None),
        ("0", None),
        ("", None),
        (None, None),
        (123, None),
    ],
)
def test_try_parse_bool_strings_and_other(val, expected):
    assert try_parse_bool(val) is expected


# ============================================================================
# object_to_hook DTO Deserialization
# ============================================================================

def test_object_to_hook_goal():
    d = {"id": 1, "name": "Trip", "cost": 1000, "date": "2026-11-01T00:00:00"}
    res = object_to_hook(d)
    assert isinstance(res, dto.Goal)
    assert res.id == 1
    assert res.name == "Trip"
    assert res.cost == 1000
    assert res.date == parser.parse("2026-11-01T00:00:00")


def test_object_to_hook_transaction_string_date():
    d = {
        "id": 10,
        "merchant": "Woolies",
        "amount": "45.50",
        "date": "2026-09-15T12:00:00",
        "description": "Groceries",
        "category_id": 81,
    }
    res = object_to_hook(d)
    assert isinstance(res, dto.Transaction)
    assert res.id == 10
    assert res.amount == 45.50
    assert res.merchant == "Woolies"
    assert res.date == parser.parse("2026-09-15T12:00:00")
    assert res.description == "Groceries"
    assert res.category_id == 81


def test_object_to_hook_transaction_datetime_date():
    dt = datetime(2026, 9, 15, 12, 0, 0)
    d = {
        "id": 11,
        "merchant": "Cafe",
        "amount": 5.0,
        "date": dt,
    }
    res = object_to_hook(d)
    assert isinstance(res, dto.Transaction)
    assert res.date == dt
    assert res.description == ""
    assert res.category_id == 0


def test_object_to_hook_suggestion():
    d = {
        "id": 5,
        "suggestion": "Save money",
        "accepted": "true",
        "feedback": "Great",
    }
    res = object_to_hook(d)
    assert isinstance(res, dto.Suggestion)
    assert res.id == 5
    assert res.suggestion == "Save money"
    assert res.accepted is True
    assert res.feedback == "Great"


def test_object_to_hook_feedback():
    d = {
        "id": 20,
        "feedback": "Limit dining",
        "suggestion_id": 5,
        "category_id": 80,
        "timeframe": "2 weeks",
    }
    res = object_to_hook(d)
    assert isinstance(res, dto.Feedback)
    assert res.id == 20
    assert res.feedback == "Limit dining"
    assert res.suggestion_id == 5
    assert res.category_id == 80
    assert res.timeframe == "2 weeks"


def test_object_to_hook_category():
    d_with_type = {"id": 80, "name": "Dining", "type": "want"}
    res = object_to_hook(d_with_type)
    assert isinstance(res, dto.Category)
    assert res.id == 80
    assert res.name == "Dining"
    assert res.type == "want"

    d_no_cost = {"id": 81, "name": "Groceries"}
    res2 = object_to_hook(d_no_cost)
    assert isinstance(res2, dto.Category)
    assert res2.id == 81
    assert res2.name == "Groceries"


def test_object_to_hook_unrecognized_dict():
    d = {"random_key": "some_value", "number": 42}
    res = object_to_hook(d)
    assert res == d


# ============================================================================
# fetch_goals
# ============================================================================

@responses.activate
def test_fetch_goals_success_with_params():
    responses.add(
        responses.GET,
        f"{TEST_DB_URL}/goals?active_only=true&top=3",
        json=[{"id": 1, "name": "Car", "cost": 5000, "date": "2026-12-01T00:00:00"}],
        status=200,
    )
    goals = fetch_goals(TEST_DB_URL, active_only=True, top=3)
    assert len(goals) == 1
    assert isinstance(goals[0], dto.Goal)
    assert goals[0].name == "Car"


@responses.activate
def test_fetch_goals_handles_http_error():
    responses.add(responses.GET, f"{TEST_DB_URL}/goals", status=500)
    goals = fetch_goals(TEST_DB_URL)
    assert goals == []


@responses.activate
def test_fetch_goals_handles_connection_exception():
    responses.add_callback(
        responses.GET,
        f"{TEST_DB_URL}/goals",
        callback=lambda req: (_ for _ in ()).throw(requests.exceptions.ConnectionError("Connection failed")),
    )
    goals = fetch_goals(TEST_DB_URL)
    assert goals == []


# ============================================================================
# fetch_suggestions
# ============================================================================

@responses.activate
def test_fetch_suggestions_success():
    responses.add(
        responses.GET,
        f"{TEST_DB_URL}/suggestions",
        json=[{"id": 1, "suggestion": "Cut coffee", "accepted": True}],
        status=200,
    )
    suggestions = fetch_suggestions(TEST_DB_URL)
    assert len(suggestions) == 1
    assert isinstance(suggestions[0], dto.Suggestion)
    assert suggestions[0].suggestion == "Cut coffee"


@responses.activate
def test_fetch_suggestions_handles_http_error():
    responses.add(responses.GET, f"{TEST_DB_URL}/suggestions", status=500)
    suggestions = fetch_suggestions(TEST_DB_URL)
    assert suggestions == []


@responses.activate
def test_fetch_suggestions_handles_connection_exception():
    responses.add_callback(
        responses.GET,
        f"{TEST_DB_URL}/suggestions",
        callback=lambda req: (_ for _ in ()).throw(requests.exceptions.ConnectionError("Connection failed")),
    )
    suggestions = fetch_suggestions(TEST_DB_URL)
    assert suggestions == []


# ============================================================================
# fetch_feedbacks
# ============================================================================

@responses.activate
def test_fetch_feedbacks_success():
    responses.add(
        responses.GET,
        f"{TEST_DB_URL}/feedbacks",
        json=[{"id": 1, "feedback": "Less eating out", "category_id": 80, "timeframe": "1 month"}],
        status=200,
    )
    feedbacks = fetch_feedbacks(TEST_DB_URL)
    assert len(feedbacks) == 1
    assert isinstance(feedbacks[0], dto.Feedback)
    assert feedbacks[0].feedback == "Less eating out"


@responses.activate
def test_fetch_feedbacks_handles_http_error():
    responses.add(responses.GET, f"{TEST_DB_URL}/feedbacks", status=500)
    feedbacks = fetch_feedbacks(TEST_DB_URL)
    assert feedbacks == []


@responses.activate
def test_fetch_feedbacks_handles_connection_exception():
    responses.add_callback(
        responses.GET,
        f"{TEST_DB_URL}/feedbacks",
        callback=lambda req: (_ for _ in ()).throw(requests.exceptions.ConnectionError("Connection failed")),
    )
    feedbacks = fetch_feedbacks(TEST_DB_URL)
    assert feedbacks == []


# ============================================================================
# fetch_categories
# ============================================================================

@responses.activate
def test_fetch_categories_success_and_filtering():
    # Includes Category DTO, raw dict with id+name, invalid item without id/name, and uncategorised item
    raw_data = [
        {"id": 80, "name": "Dining", "type": "want"},
        {"id": 81, "name": "Groceries", "type": "need"},
        {"id": 82, "name": "Bills", "cost": 100},  # unparsed dict with id+name to hit line 118
        {"id": 99, "name": "Uncategorised", "type": "other"},
        {"invalid": "item"},
    ]
    responses.add(
        responses.GET,
        f"{TEST_TX_URL}/categories",
        json=raw_data,
        status=200,
    )
    categories = fetch_categories(TEST_TX_URL)
    assert len(categories) == 3
    assert [c.name for c in categories] == ["Dining", "Groceries", "Bills"]


@responses.activate
def test_fetch_categories_default_url():
    responses.add(
        responses.GET,
        f"{TRANSACTIONS_DB_URL.rstrip('/')}/categories",
        json=[{"id": 1, "name": "Transport", "type": "need"}],
        status=200,
    )
    categories = fetch_categories(None)
    assert len(categories) == 1
    assert categories[0].name == "Transport"


@responses.activate
def test_fetch_categories_handles_http_error():
    responses.add(responses.GET, f"{TEST_TX_URL}/categories", status=500)
    categories = fetch_categories(TEST_TX_URL)
    assert categories == []


@responses.activate
def test_fetch_categories_handles_connection_exception():
    responses.add_callback(
        responses.GET,
        f"{TEST_TX_URL}/categories",
        callback=lambda req: (_ for _ in ()).throw(requests.exceptions.ConnectionError("Connection failed")),
    )
    categories = fetch_categories(TEST_TX_URL)
    assert categories == []
