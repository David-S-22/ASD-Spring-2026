"""Choosing a transaction ID after an ambiguous update or delete.

Regression for the clarification loop: answering "29" to "Choose a
transaction ID" used to re-run the same ambiguous plan because a bare
number is never treated as a grounded transaction ID.
"""

from unittest.mock import Mock

from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark

import janelle.backend.app as backend_app
from janelle.backend.Helpers import normalize_transaction_id_answer
from janelle.backend.services import transaction_orchestrator


CATEGORIES = [{"id": 80, "name": "Dining", "type": "want"}]
MERIVALE = [
    {
        "id": 27,
        "date": "2026-08-09T00:00:00",
        "merchant": "Merivale",
        "description": "Dinner",
        "amount": 84.5,
        "category_id": 80,
        "version": "2026-08-09T12:00:00.000001",
    },
    {
        "id": 28,
        "date": "2026-08-16T00:00:00",
        "merchant": "Merivale",
        "description": "Lunch",
        "amount": 42.0,
        "category_id": 80,
        "version": "2026-08-16T12:00:00.000001",
    },
    {
        "id": 29,
        "date": "2026-08-30T00:00:00",
        "merchant": "Merivale",
        "description": "Drinks",
        "amount": 76.0,
        "category_id": 80,
        "version": "2026-08-30T12:00:00.000001",
    },
]


@fixture
def client():
    with backend_app.app.test_client() as test_client:
        yield test_client


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def plan(**overrides):
    result = {
        "operation": "read",
        "transaction_id": None,
        "fields": {},
        "filters": {},
        "calculation": "none",
        "handoff": "none",
        "reply": "Prepared safely.",
        "fallback": False,
        "planning_error": None,
        "retryable": False,
    }
    result.update(overrides)
    return result


def use_plan(monkeypatch: MonkeyPatch, result):
    planner = Mock(return_value=result)
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service,
        "create_plan",
        planner,
    )
    return planner


def merivale_database(monkeypatch: MonkeyPatch):
    """Categories, the full list, then the merchant-filtered query."""
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(MERIVALE),
            response_with_json(MERIVALE),
        ]),
    )


# --- answer normalisation ---------------------------------------------------


@mark.parametrize(
    "answer",
    [
        "29",
        " 29 ",
        "#29",
        "id 29",
        "ID: 29",
        "transaction 29",
        "Transaction ID 29",
        "transaction #29",
        "the transaction id 29.",
        "number 29",
        "no. 29",
        "tx 29",
    ],
)
def test_bare_transaction_id_answers_become_explicit(answer):
    assert normalize_transaction_id_answer(answer) == "transaction ID 29"


@mark.parametrize(
    "answer",
    [
        "29th Aug",
        "the one for $76",
        "29 and 28",
        "delete 29",
        "amount 29",
        "",
    ],
)
def test_other_answers_are_left_alone(answer):
    assert normalize_transaction_id_answer(answer) == answer


# --- grounded ID mentions ---------------------------------------------------


@mark.parametrize(
    ("message", "expected"),
    [
        ("delete merivale.\nAdditional details: transaction ID 29", {29}),
        ("Delete #27", {27}),
        ("Update transaction id=28 to $50", {28}),
        ("delete merivale.\nAdditional details: 29", set()),
        ("Spent $29 at Merivale", set()),
        ("Delete #27 and #28", {27, 28}),
        ("", set()),
    ],
)
def test_grounded_transaction_ids_only_accept_explicit_forms(message, expected):
    assert transaction_orchestrator.grounded_transaction_ids(message) == expected


# --- orchestrator backstop --------------------------------------------------


def test_delete_plan_without_id_targets_the_single_mentioned_transaction(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    merivale_database(monkeypatch)
    # The planner ignored the ID and only returned the merchant filter.
    use_plan(monkeypatch, plan(
        operation="delete",
        filters={"merchant": "Merivale"},
    ))

    response = client.post(
        "/chat",
        json={"message": "delete merivale.\nAdditional details: transaction ID 29"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["requires_clarification"] is False
    assert result["preview"]["operation"] == "delete"
    assert result["preview"]["transaction_id"] == 29
    assert result["preview"]["before"]["id"] == 29


def test_delete_plan_without_id_still_clarifies_when_two_ids_are_named(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    merivale_database(monkeypatch)
    use_plan(monkeypatch, plan(
        operation="delete",
        filters={"merchant": "Merivale"},
    ))

    response = client.post(
        "/chat",
        json={"message": "delete merivale #28 or #29"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["requires_clarification"] is True
    assert result["preview"] is None


def test_read_plan_is_not_given_a_transaction_id(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    merivale_database(monkeypatch)
    planner = use_plan(monkeypatch, plan(
        operation="read",
        filters={"merchant": "Merivale"},
    ))

    response = client.post(
        "/chat",
        json={"message": "show merivale #29"},
    )

    assert response.status_code == 200
    assert response.get_json()["requires_clarification"] is False
    assert planner.return_value["transaction_id"] is None


def test_mentioned_id_outside_the_filter_still_clarifies(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    """A grounded ID is only used when it is one of the filtered rows."""
    merivale_database(monkeypatch)
    use_plan(monkeypatch, plan(
        operation="delete",
        filters={"merchant": "Merivale"},
    ))

    response = client.post(
        "/chat",
        json={"message": "delete merivale.\nAdditional details: transaction ID 99"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["requires_clarification"] is True
    assert result["preview"] is None


# --- HTMX card --------------------------------------------------------------


def test_ui_clarification_lists_matches_and_marks_answer_as_an_id(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    merivale_database(monkeypatch)
    use_plan(monkeypatch, plan(
        operation="delete",
        filters={"merchant": "Merivale"},
    ))

    response = client.post("/ui/chat", data={"message": "delete merivale"})

    assert response.status_code == 200
    assert "Needs clarification" in response.text
    for transaction_id in (27, 28, 29):
        assert f"#{transaction_id}" in response.text
    assert "Use #" not in response.text
    assert response.text.count('name="clarification_kind"') == 1
    assert 'value="transaction_id"' in response.text
    assert 'name="original_message"' in response.text
    assert "for example 29" in response.text


def test_ui_bare_id_answer_is_grounded_before_planning(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    merivale_database(monkeypatch)
    planner = use_plan(monkeypatch, plan(
        operation="delete",
        filters={"merchant": "Merivale"},
    ))

    response = client.post(
        "/ui/chat",
        data={
            "original_message": "delete merivale",
            "clarification": "29",
            "clarification_kind": "transaction_id",
        },
    )

    assert response.status_code == 200
    assert planner.call_args.args[0] == (
        "delete merivale.\nAdditional details: transaction ID 29"
    )
    assert "Ready for your review" in response.text
    assert "Needs clarification" not in response.text
    assert "$76.00" in response.text


def test_ui_free_text_answer_without_kind_is_not_rewritten(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(return_value=response_with_json(CATEGORIES)),
    )
    planner = use_plan(monkeypatch, plan(
        operation="create",
        fields={
            "date": "2026-09-02",
            "merchant": "Cat Cafe",
            "description": "Coffee",
            "amount": 25.0,
            "category": "Dining",
        },
    ))

    response = client.post(
        "/ui/chat",
        data={
            "original_message": "Add a transaction at Cat Cafe for coffee",
            "clarification": "25",
        },
    )

    assert response.status_code == 200
    assert planner.call_args.args[0] == (
        "Add a transaction at Cat Cafe for coffee.\nAdditional details: 25"
    )
