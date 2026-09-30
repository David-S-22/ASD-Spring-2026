"""Choosing a transaction ID after an ambiguous update or delete.

Regression for the clarification loop: answering "29" to "Choose a
transaction ID" used to re-run the same ambiguous plan because a bare
number is never treated as a grounded transaction ID.
"""

from itertools import cycle
from unittest.mock import Mock

from pytest import fixture, mark

import janelle.backend.app as backend_app
from janelle.backend.Helpers import normalize_transaction_id_answer
from janelle.backend.services import transaction_orchestrator


CATEGORIES = [{"id": 80, "name": "Dining", "type": "want"}]
MERIVALE = [
    {
        "id": transaction_id,
        "date": f"2026-08-{day:02d}T00:00:00",
        "merchant": "Merivale",
        "description": description,
        "amount": amount,
        "category_id": 80,
        "version": f"2026-08-{day:02d}T12:00:00.000001",
    }
    for transaction_id, day, description, amount in (
        (27, 9, "Dinner", 84.5),
        (28, 16, "Lunch", 42.0),
        (29, 30, "Drinks", 76.0),
    )
]
DELETE_MERIVALE = {
    "operation": "delete",
    "transaction_id": None,
    "fields": {},
    "filters": {"merchant": "Merivale"},
    "calculation": "none",
    "handoff": "none",
    "reply": "Prepared safely.",
    "fallback": False,
    "planning_error": None,
    "retryable": False,
}


def response_with_json(payload):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


@fixture
def client():
    with backend_app.app.test_client() as test_client:
        yield test_client


@fixture
def merivale_database(monkeypatch):
    """Each chat request reads categories, the full list, then the filtered query."""
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=cycle(
            response_with_json(rows)
            for rows in (CATEGORIES, MERIVALE, MERIVALE)
        )),
    )


@fixture
def use_plan(monkeypatch):
    def install(**overrides):
        planner = Mock(return_value={**DELETE_MERIVALE, **overrides})
        monkeypatch.setattr(
            transaction_orchestrator.ollama_service, "create_plan", planner
        )
        return planner

    return install


# --- answer normalisation and grounded ID mentions --------------------------


@mark.parametrize(
    ("answer", "expected"),
    [
        (" 29 ", "transaction ID 29"),
        ("#29", "transaction ID 29"),
        ("ID: 29", "transaction ID 29"),
        ("the transaction no. 29.", "transaction ID 29"),
        ("29th Aug", "29th Aug"),
        ("29 and 28", "29 and 28"),
        ("delete 29", "delete 29"),
    ],
)
def test_only_bare_transaction_id_answers_become_explicit(answer, expected):
    assert normalize_transaction_id_answer(answer) == expected


@mark.parametrize(
    ("message", "expected"),
    [
        ("delete merivale.\nAdditional details: transaction ID 29", {29}),
        ("Update transaction id=28 to $50", {28}),
        ("Delete #27 and #28", {27, 28}),
        ("Spent $29 at Merivale.\nAdditional details: 29", set()),
    ],
)
def test_grounded_transaction_ids_only_accept_explicit_forms(message, expected):
    assert transaction_orchestrator.grounded_transaction_ids(message) == expected


# --- orchestrator backstop --------------------------------------------------


@mark.parametrize(
    ("message", "targets"),
    [
        ("delete merivale.\nAdditional details: transaction ID 29", 29),
        ("delete merivale #28 or #29", None),
        ("delete merivale.\nAdditional details: transaction ID 99", None),
    ],
)
def test_delete_plan_without_id_targets_only_a_single_mentioned_match(
    client, merivale_database, use_plan, message, targets
):
    """The planner ignored the ID and only returned the merchant filter."""
    use_plan()

    result = client.post("/chat", json={"message": message}).get_json()

    if targets is None:
        assert result["requires_clarification"] is True
        assert result["preview"] is None
    else:
        assert result["requires_clarification"] is False
        assert result["preview"]["operation"] == "delete"
        assert result["preview"]["transaction_id"] == targets
        assert result["preview"]["before"]["id"] == targets


def test_read_plan_is_not_given_a_transaction_id(
    client, merivale_database, use_plan
):
    planner = use_plan(operation="read")

    result = client.post("/chat", json={"message": "show merivale #29"}).get_json()

    assert result["requires_clarification"] is False
    assert planner.return_value["transaction_id"] is None


# --- HTMX card --------------------------------------------------------------


def test_ui_marks_id_clarification_then_grounds_the_bare_answer(
    client, merivale_database, use_plan
):
    planner = use_plan()

    asked = client.post("/ui/chat", data={"message": "delete merivale"})

    assert asked.status_code == 200
    assert "Needs clarification" in asked.text
    assert asked.text.count('name="clarification_kind"') == 1
    assert 'value="transaction_id"' in asked.text
    assert "for example 29" in asked.text

    answered = client.post(
        "/ui/chat",
        data={
            "original_message": "delete merivale",
            "clarification": "29",
            "clarification_kind": "transaction_id",
        },
    )

    assert answered.status_code == 200
    assert planner.call_args.args[0] == (
        "delete merivale.\nAdditional details: transaction ID 29"
    )
    assert "Ready for your review" in answered.text
    assert "Needs clarification" not in answered.text
    assert "$76.00" in answered.text


def test_ui_free_text_answer_without_kind_is_not_rewritten(
    client, merivale_database, use_plan
):
    planner = use_plan(
        operation="create",
        filters={},
        fields={
            "date": "2026-09-02",
            "merchant": "Cat Cafe",
            "description": "Coffee",
            "amount": 25.0,
            "category": "Dining",
        },
    )

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
