import json
import logging
import re
from unittest.mock import Mock

from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark, raises

import janelle.backend.app as backend_app
import janelle.backend.services.transaction_orchestrator as transaction_orchestrator
from janelle.backend.services import transaction_source


DB_URL = backend_app.config.TRANSACTIONS_DB_URL
TIMEOUT = backend_app.config.DATABASE_TIMEOUT_SECONDS

CATEGORIES = [
    {"id": 1, "name": "Uncategorised", "type": None},
    {"id": 80, "name": "Dining", "type": "want"},
    {"id": 81, "name": "Groceries", "type": "need"},
]
MERIVALE_TRANSACTIONS = [
    {
        "id": 27,
        "date": "2026-08-09T00:00:00",
        "merchant": "Merivale",
        "description": "Dinner",
        "amount": 84.5,
        "category_id": 80,
        "version": "2026-08-09T12:00:00.123456",
    },
    {
        "id": 28,
        "date": "2026-08-16T00:00:00",
        "merchant": "Merivale",
        "description": "Lunch",
        "amount": 42.0,
        "category_id": 80,
        "version": "2026-08-16T12:00:00.123456",
    },
    {
        "id": 29,
        "date": "2026-08-30T00:00:00",
        "merchant": "Merivale",
        "description": "Dinner",
        "amount": 76.0,
        "category_id": 80,
        "version": "2026-08-30T12:00:00.123456",
    },
]
SPOTIFY_TRANSACTIONS = [
    {
        "id": 25,
        "date": "2026-07-15T00:00:00",
        "merchant": "Spotify AU",
        "description": "Subscription",
        "amount": 13.99,
        "category_id": 80,
        "version": "2026-07-15T12:00:00.123456",
    },
    {
        "id": 26,
        "date": "2026-08-20T00:00:00",
        "merchant": "Spotify AU",
        "description": "Subscription",
        "amount": 17.99,
        "category_id": 80,
        "version": "2026-08-20T12:00:00.123456",
    },
]
JUNE_TENTH = [
    {
        "id": 2,
        "date": "2026-06-10T00:00:00",
        "merchant": "Netflix",
        "description": "Netflix.com subscription",
        "amount": 20.99,
        "category_id": 81,
    },
    {
        "id": 1,
        "date": "2026-06-10T00:00:00",
        "merchant": "Harbourview Realty",
        "description": "Rent payment",
        "amount": 1100.0,
        "category_id": 80,
    },
]
JULY_FIFTEENTH = [
    {
        "id": 4,
        "date": "2026-07-15T00:00:00",
        "merchant": "DriveBox",
        "description": "Cloud storage subscription",
        "amount": 2.99,
        "category_id": 81,
    },
    {
        "id": 3,
        "date": "2026-07-15T00:00:00",
        "merchant": "Spotify AU",
        "description": "Spotify Premium subscription",
        "amount": 13.99,
        "category_id": 80,
    },
]

ATOMIC_CAFE_MESSAGE = "Add lunch at Atomic Cafe on 1 September 2026 for $24.50"
ATOMIC_CAFE_FIELDS = {
    "date": "2026-09-01",
    "merchant": "Atomic Cafe",
    "description": "Lunch",
    "amount": 24.5,
}
ATOMIC_CAFE_ROW = {
    "id": 90,
    "date": "2026-09-01T00:00:00",
    "merchant": "Atomic Cafe",
    "description": "Lunch",
    "amount": 24.5,
    "category_id": 80,
}


@fixture
def client():
    transaction_orchestrator.reset_transaction_requests()
    with backend_app.app.test_client() as test_client:
        yield test_client
    transaction_orchestrator.reset_transaction_requests()


# --- fakes -----------------------------------------------------------------


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def fake_database(monkeypatch: MonkeyPatch, *payloads):
    """Stub database GETs: the category list first, then each payload in turn.

    A payload that is already a response Mock (for non-200 replies) is used
    as-is; anything else is wrapped in a 200 JSON response.
    """
    responses = [response_with_json(CATEGORIES)]
    for payload in payloads:
        responses.append(
            payload if isinstance(payload, Mock)
            else response_with_json(payload)
        )
    get = Mock(side_effect=responses)
    monkeypatch.setattr(backend_app.requests, "get", get)
    return get


def stub_write(monkeypatch: MonkeyPatch, method, payload=None, status=200):
    write = Mock(return_value=response_with_json(payload, status))
    monkeypatch.setattr(backend_app.requests, method, write)
    return write


def extraction(**overrides):
    result = {
        "operation": "read",
        "transaction_id": None,
        "fields": {},
        "filters": {},
        "calculation": "none",
        "handoff": "none",
        "reply": "Prepared safely.",
        "fallback": False,
    }
    result.update(overrides)
    return result


def create_plan(**fields):
    return extraction(
        operation="create",
        fields={**ATOMIC_CAFE_FIELDS, "category": "Dining", **fields},
    )


UPDATE_PLAN = extraction(
    operation="update",
    transaction_id=27,
    fields={"amount": 90.0},
)


def planned(result):
    return {
        **result,
        "planning_error": (
            result.get("planning_error")
            or ("invalid_plan" if result.get("fallback") else None)
        ),
        "retryable": result.get("retryable", False),
    }


def use_plan(monkeypatch: MonkeyPatch, result):
    planner = Mock(return_value=planned(result))
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service, "create_plan", planner,
    )
    return planner


def use_plans(monkeypatch: MonkeyPatch, *results):
    planner = Mock(side_effect=[planned(result) for result in results])
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service, "create_plan", planner,
    )
    return planner


def preview_for(client: FlaskClient, message):
    return client.post("/chat", json={"message": message}).get_json()["preview"]


def expected_transaction_headers(before):
    return {
        "X-Expected-Transaction": (
            transaction_orchestrator.chat_service.expected_transaction_header(
                before
            )
        ),
    }


# --- write flows: preview, confirm, safety ----------------------------------


def test_chat_create_previews_then_apply_performs_exactly_one_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, CATEGORIES, ATOMIC_CAFE_ROW)
    post = stub_write(monkeypatch, "post", ATOMIC_CAFE_ROW, status=201)
    planner = use_plan(monkeypatch, create_plan())

    preview_response = client.post(
        "/chat",
        json={"message": f"{ATOMIC_CAFE_MESSAGE} in Dining"},
    )

    assert preview_response.status_code == 200
    result = preview_response.get_json()
    assert result["requires_confirmation"] is True
    assert [item["stage"] for item in result["agent"]["trace"]] == [
        "PLAN", "ACT", "OBSERVE", "ADAPT",
    ]
    assert result["preview"]["before"] is None
    assert result["preview"]["after"] == {
        "id": None,
        **ATOMIC_CAFE_FIELDS,
        "category_id": 80,
        "category_name": "Dining",
    }
    post.assert_not_called()

    apply_response = client.post("/chat/apply", json=result["preview"])

    assert apply_response.status_code == 200
    applied = apply_response.get_json()
    assert applied["transaction"]["id"] == 90
    assert applied["verified"] is True
    assert planner.call_count == 1
    post.assert_called_once_with(
        f"{DB_URL}/transactions",
        json={**ATOMIC_CAFE_FIELDS, "category_id": 80},
        timeout=TIMEOUT,
    )


def test_chat_update_shows_before_after_and_rechecks_version_before_apply(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    updated = {**current, "amount": 90.0}
    fake_database(monkeypatch, current, CATEGORIES, current, updated)
    patch = stub_write(monkeypatch, "patch", updated)
    use_plan(monkeypatch, UPDATE_PLAN)

    preview = preview_for(client, "Change transaction 27 to $90")

    assert preview["before"]["amount"] == 84.5
    assert preview["after"]["amount"] == 90.0
    assert preview["changes"] == {"amount": {"before": 84.5, "after": 90.0}}
    patch.assert_not_called()

    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 200
    assert response.get_json()["verified"] is True
    patch.assert_called_once_with(
        f"{DB_URL}/transactions/27",
        json={"amount": 90.0},
        headers=expected_transaction_headers(preview["before"]),
        timeout=TIMEOUT,
    )


def test_chat_delete_previews_full_row_then_apply_deletes_exactly_once(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    not_found = response_with_json(
        {"error": "transaction not found", "code": "transaction_not_found"},
        status=404,
    )
    fake_database(monkeypatch, current, CATEGORIES, current, not_found)
    delete = stub_write(monkeypatch, "delete", None, status=204)
    use_plan(monkeypatch, extraction(operation="delete", transaction_id=27))

    result = client.post(
        "/chat",
        json={"message": "Delete transaction 27"},
    ).get_json()

    preview = result["preview"]
    assert result["requires_confirmation"] is True
    assert preview["before"] == {**current, "category_name": "Dining"}
    assert preview["after"] is None
    delete.assert_not_called()

    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 200
    assert response.get_json()["deleted"]["id"] == 27
    assert response.get_json()["verified"] is True
    delete.assert_called_once_with(
        f"{DB_URL}/transactions/27",
        headers=expected_transaction_headers(preview["before"]),
        timeout=TIMEOUT,
    )


def test_chat_apply_rejects_stale_preview_when_version_changed(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    reversioned = {**current, "version": "2026-09-02T12:00:00.654321"}
    fake_database(monkeypatch, current, CATEGORIES, reversioned)
    patch = stub_write(monkeypatch, "patch")
    use_plan(monkeypatch, UPDATE_PLAN)

    preview = preview_for(client, "Change transaction 27 to $90")
    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 409
    assert response.get_json()["code"] == "stale_preview"
    patch.assert_not_called()


def test_chat_does_not_offer_update_confirmation_without_version(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = {
        key: value
        for key, value in MERIVALE_TRANSACTIONS[0].items()
        if key != "version"
    }
    fake_database(monkeypatch, current)
    patch = stub_write(monkeypatch, "patch")
    use_plan(monkeypatch, UPDATE_PLAN)

    response = client.post(
        "/chat",
        json={"message": "Change transaction 27 to $90"},
    )

    assert response.status_code == 502
    assert response.get_json()["code"] == "invalid_database_response"
    patch.assert_not_called()


def test_chat_apply_rejects_tampered_preview(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch)
    post = stub_write(monkeypatch, "post")
    use_plan(monkeypatch, create_plan())

    preview = preview_for(client, f"{ATOMIC_CAFE_MESSAGE} in Dining")
    preview["fields"]["amount"] = 1
    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 422
    assert response.get_json()["code"] == "invalid_preview"
    post.assert_not_called()


def test_chat_request_state_rejects_in_progress_and_unavailable_requests(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, [], CATEGORIES)
    use_plan(monkeypatch, create_plan())
    suggestion = client.post(
        "/chat",
        json={"message": ATOMIC_CAFE_MESSAGE},
    ).get_json()
    request_id = suggestion["agent"]["request_id"]
    preview = client.post(
        "/chat/category",
        json={"request_id": request_id, "category_id": 80},
    ).get_json()["preview"]
    replay, stored = transaction_orchestrator.begin_apply(request_id, preview)

    assert replay is False
    assert stored == preview

    in_progress = client.post("/chat/apply", json=preview)

    assert in_progress.status_code == 409
    assert in_progress.get_json()["code"] == "request_in_progress"

    with raises(transaction_orchestrator.chat_service.ChatError) as error:
        transaction_orchestrator.register_selected_preview(
            request_id,
            {**preview, "fields": {**preview["fields"], "category_id": 81}},
        )
    assert error.value.code == "agent_request_unavailable"

    unknown = client.post(
        "/chat/category",
        json={"request_id": "missing", "category_id": 80},
    )

    assert unknown.status_code == 409
    assert unknown.get_json()["code"] == "agent_request_unavailable"


def test_chat_does_not_retry_indeterminate_committed_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, CATEGORIES)
    post = stub_write(
        monkeypatch, "post", {**ATOMIC_CAFE_ROW, "amount": 99.0}, status=201,
    )
    planner = use_plan(monkeypatch, create_plan())
    preview = preview_for(client, f"{ATOMIC_CAFE_MESSAGE} in Dining")

    first = client.post("/chat/apply", json=preview)
    replay = client.post("/chat/apply", json=preview)

    assert first.status_code == 200
    result = first.get_json()
    assert result["verified"] is False
    assert result["write_outcome_unknown"] is True
    assert result["saved"] is False
    assert result["agent"]["status"] == "failed"
    assert "do not retry this confirmation" in result["reply"]
    assert replay.get_json() == result
    assert post.call_count == 1
    assert planner.call_count == 1


def test_chat_preserves_definite_database_write_rejection(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    rejection = {"error": "amount is invalid", "code": "invalid_amount"}
    fake_database(monkeypatch, CATEGORIES)
    post = stub_write(monkeypatch, "post", rejection, status=422)
    use_plan(monkeypatch, create_plan())
    preview = preview_for(client, f"{ATOMIC_CAFE_MESSAGE} in Dining")

    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 422
    assert response.get_json() == rejection
    assert post.call_count == 1


def test_chat_invalid_model_result_is_safe_and_non_writing(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch)
    writes = [
        stub_write(monkeypatch, method) for method in ("post", "patch", "delete")
    ]
    use_plan(monkeypatch, extraction(
        fallback=True,
        reply="I could not safely understand that request. No changes were made.",
    ))

    response = client.post("/chat", json={"message": "Do something unsafe"})

    result = response.get_json()
    assert result["fallback"] is True
    assert result["requires_confirmation"] is False
    assert result["preview"] is None
    for write in writes:
        write.assert_not_called()


def test_chat_replans_one_invalid_plan_then_completes(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, MERIVALE_TRANSACTIONS)
    plans = use_plans(
        monkeypatch,
        extraction(
            fallback=True,
            planning_error="unsupported fields: status",
            retryable=True,
        ),
        extraction(calculation="count"),
    )

    response = client.post(
        "/chat",
        json={"message": "How many transactions are there?"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["analytics"]["count"] == 3
    assert [item["stage"] for item in result["agent"]["trace"]] == [
        "PLAN", "ACT", "OBSERVE", "ADAPT",
        "PLAN", "ACT", "OBSERVE", "ADAPT",
    ]
    assert result["agent"]["trace"][3]["status"] == "replan"
    assert plans.call_count == 2


def test_chat_replans_recoverable_action_validation_error(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    fake_database(monkeypatch, current, current)
    plans = use_plans(
        monkeypatch,
        extraction(
            operation="update",
            transaction_id=27,
            fields={"category_id": 80, "category": "Groceries"},
        ),
        extraction(
            operation="update",
            transaction_id=27,
            fields={"category_id": 81},
        ),
    )

    response = client.post(
        "/chat",
        json={"message": "Move transaction 27 to Groceries"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["requires_confirmation"] is True
    assert result["preview"]["after"]["category_id"] == 81
    assert result["agent"]["trace"][3]["status"] == "replan"
    assert plans.call_count == 2


def test_chat_discards_model_transaction_id_not_grounded_in_user_request(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    atomic_cafe = {**ATOMIC_CAFE_ROW, "version": "2026-09-01T12:00:00.123456"}
    fake_database(
        monkeypatch,
        [MERIVALE_TRANSACTIONS[0], atomic_cafe],
        [atomic_cafe],
    )
    use_plan(monkeypatch, extraction(
        operation="update",
        transaction_id=27,
        fields={"amount": 90.0},
        filters={"merchant": "Atomic Cafe"},
    ))

    response = client.post(
        "/chat",
        json={"message": "Change my Atomic Cafe transaction to $90"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["preview"]["transaction_id"] == 90
    assert result["preview"]["before"]["merchant"] == "Atomic Cafe"


def test_chat_ambiguous_target_returns_clarification_without_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(
        monkeypatch,
        SPOTIFY_TRANSACTIONS, SPOTIFY_TRANSACTIONS,
        CATEGORIES, SPOTIFY_TRANSACTIONS, SPOTIFY_TRANSACTIONS,
    )
    patch = stub_write(monkeypatch, "patch")
    use_plan(monkeypatch, extraction(
        operation="update",
        fields={"amount": 19.99},
        filters={"merchant": "Spotify AU"},
    ))

    result = client.post(
        "/chat",
        json={"message": "Update Spotify to $19.99"},
    ).get_json()

    assert result["requires_clarification"] is True
    assert result["agent"]["status"] == "clarify"
    assert [row["id"] for row in result["matches"]] == [25, 26]
    assert result["preview"] is None

    card = client.post("/ui/chat", data={"message": "Update Spotify to $19.99"})

    assert card.status_code == 200
    assert "#25" in card.text
    assert "#26" in card.text
    assert 'name="clarification"' in card.text
    assert 'name="original_message"' in card.text
    patch.assert_not_called()


# --- category flow ------------------------------------------------------------


def test_chat_create_without_category_suggests_one_then_accepts_it(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, [], CATEGORIES)
    use_plan(monkeypatch, create_plan())

    suggestion = client.post("/chat", json={"message": ATOMIC_CAFE_MESSAGE})

    assert suggestion.status_code == 200
    result = suggestion.get_json()
    assert result["requires_clarification"] is True
    assert result["requires_confirmation"] is False
    assert result["preview"] is None
    assert result["category_selection"] == {
        "source": "ai_suggestion",
        "suggested_category_id": 80,
        "suggested_category_name": "Dining",
        "selected_category_id": None,
        "selected_category_name": None,
        "requires_user_response": True,
    }

    accepted = client.post(
        "/chat/category",
        json={"request_id": result["agent"]["request_id"], "category_id": 80},
    )

    assert accepted.status_code == 200
    accepted_result = accepted.get_json()
    assert accepted_result["requires_confirmation"] is True
    assert accepted_result["preview"]["fields"]["category_id"] == 80
    assert "suggested_category_id" not in accepted_result["preview"]
    assert accepted_result["category_selection"]["source"] == "ai_suggestion"


def test_chat_prefers_recent_user_category_correction_for_merchant(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(
        monkeypatch,
        [{"user_category_id": 81, "user_category_name": "Groceries"}],
    )
    use_plan(monkeypatch, create_plan())

    response = client.post("/chat", json={"message": ATOMIC_CAFE_MESSAGE})

    assert response.status_code == 200
    selection = response.get_json()["category_selection"]
    assert selection["suggested_category_id"] == 81
    assert selection["suggested_category_name"] == "Groceries"


def test_chat_invalid_ai_category_lists_available_choices(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, [])
    use_plan(monkeypatch, create_plan(category="Unknown category"))

    response = client.post("/chat", json={"message": ATOMIC_CAFE_MESSAGE})

    assert response.status_code == 200
    result = response.get_json()
    assert result["category_selection"]["suggested_category_id"] is None
    assert result["category_selection"]["requires_user_response"] is True
    assert [item["name"] for item in result["categories"]] == [
        "Uncategorised", "Dining", "Groceries",
    ]


def test_chat_category_override_is_authoritative_and_replay_safe(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    created = {**ATOMIC_CAFE_ROW, "category_id": 81}
    fake_database(monkeypatch, [], CATEGORIES, CATEGORIES, created)
    post = stub_write(monkeypatch, "post", created, status=201)
    use_plan(monkeypatch, create_plan())

    suggestion = client.post(
        "/chat",
        json={"message": ATOMIC_CAFE_MESSAGE},
    ).get_json()
    selection = client.post(
        "/chat/category",
        json={
            "request_id": suggestion["agent"]["request_id"],
            "category_id": 81,
        },
    ).get_json()
    preview = selection["preview"]

    assert preview["fields"]["category_id"] == 81
    assert preview["suggested_category_id"] == 80
    assert selection["category_selection"] == {
        "source": "user_override",
        "suggested_category_id": 80,
        "suggested_category_name": "Dining",
        "selected_category_id": 81,
        "selected_category_name": "Groceries",
        "requires_user_response": False,
    }

    first = client.post("/chat/apply", json=preview)
    replay = client.post("/chat/apply", json=preview)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.get_json() == first.get_json()
    post.assert_called_once_with(
        f"{DB_URL}/transactions",
        json={
            **ATOMIC_CAFE_FIELDS,
            "category_id": 81,
            "suggested_category_id": 80,
        },
        timeout=TIMEOUT,
    )


def test_chat_create_missing_fields_requests_targeted_clarification(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, [])
    use_plan(monkeypatch, extraction(
        operation="create",
        fields={"merchant": "Atomic Cafe", "description": "Lunch"},
    ))

    response = client.post(
        "/chat",
        json={"message": "Add lunch at Atomic Cafe"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["requires_clarification"] is True
    assert result["preview"] is None
    assert result["reply"] == (
        "What date and amount should I use for this transaction?"
    )


# --- read analytics -----------------------------------------------------------


def test_chat_calculates_count_sum_and_average_from_database_rows(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = fake_database(
        monkeypatch, MERIVALE_TRANSACTIONS, MERIVALE_TRANSACTIONS,
    )
    use_plan(monkeypatch, extraction(
        filters={"merchant": "Merivale"},
        calculation=["count", "sum", "average"],
    ))

    response = client.post(
        "/chat",
        json={"message": "How often and how much do I spend at Merivale?"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["requires_confirmation"] is False
    assert result["analytics"] == {
        "count": 3,
        "sum": 202.5,
        "sum_cents": 20250,
        "average": 67.5,
        "average_cents": 6750,
        "date_from": "2026-08-09",
        "date_to": "2026-08-30",
        "calculations": ["count", "sum", "average"],
    }
    assert "$202.50" in result["reply"]
    assert "$67.50" in result["reply"]
    assert get.call_args_list[-1].kwargs["params"] == {"merchant": "Merivale"}


def test_chat_ranks_largest_purchases_from_database_rows(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = fake_database(monkeypatch, MERIVALE_TRANSACTIONS)
    use_plan(monkeypatch, extraction(
        filters={"date_from": "2026-08-01", "date_to": "2026-08-31"},
        calculation="largest",
    ))

    response = client.post(
        "/chat",
        json={"message": "Show my biggest purchases in August"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert [row["id"] for row in result["transactions"]] == [27, 29, 28]
    assert result["analytics"]["calculations"] == ["largest"]
    assert result["analytics"]["count"] == 3
    assert get.call_args_list[-1].kwargs["params"] == {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
    }


def test_chat_totals_a_category_over_a_date_range(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    dining = [
        {
            "id": 30,
            "date": "2026-08-26T00:00:00",
            "merchant": "Chat Thai",
            "description": "Dinner",
            "amount": 47.2,
            "category_id": 80,
        },
        MERIVALE_TRANSACTIONS[2],
    ]
    get = fake_database(monkeypatch, dining)
    use_plan(monkeypatch, extraction(
        filters={
            "date_from": "2026-08-24",
            "date_to": "2026-08-30",
            "category": "Dining",
        },
        calculation="sum",
    ))

    response = client.post(
        "/chat",
        json={"message": "How much did eating out cost me last week?"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["analytics"]["sum"] == 123.2
    assert "$123.20" in result["reply"]
    assert "from 24 Aug 2026 to 30 Aug 2026" in result["reply"]
    assert get.call_args_list[-1].kwargs["params"] == {
        "date_from": "2026-08-24",
        "date_to": "2026-08-30",
        "category_id": 80,
    }


def test_chat_resolves_partial_merchant_as_text_search(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    gym = [
        {
            "id": 14,
            "date": "2026-07-08T00:00:00",
            "merchant": "Anytime Fitness Ultimo",
            "description": "Direct debit membership fee",
            "amount": 17.5,
            "category_id": 80,
        },
        {
            "id": 7,
            "date": "2026-06-24T00:00:00",
            "merchant": "Anytime Fitness Ultimo",
            "description": "Direct debit membership fee",
            "amount": 17.5,
            "category_id": 80,
        },
    ]
    get = fake_database(monkeypatch, gym, gym)
    use_plan(monkeypatch, extraction(filters={"merchant": "Anytime Fitness"}))

    response = client.post(
        "/chat",
        json={"message": "List purchases containing Anytime Fitness"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["filters"] == {"search_text": "Anytime Fitness"}
    assert [row["id"] for row in result["transactions"]] == [14, 7]
    assert get.call_args_list[-1].kwargs["params"] == {
        "search_text": "Anytime Fitness",
    }


def test_chat_queries_each_discrete_date_as_a_normalised_range(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = fake_database(monkeypatch, JUNE_TENTH, JULY_FIFTEENTH)
    use_plan(monkeypatch, extraction(
        filters={"dates": ["2026-06-10", "2026-07-15"]},
    ))

    response = client.post(
        "/chat",
        json={
            "message": (
                "List all purchases spent on the 10th June and the 15th July"
            ),
        },
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["filters"] == {"dates": ["2026-06-10", "2026-07-15"]}
    assert [row["id"] for row in result["transactions"]] == [4, 3, 2, 1]
    assert result["analytics"]["count"] == 4
    assert get.call_args_list[1].kwargs["params"] == {
        "date_from": "2026-06-10",
        "date_to": "2026-06-10",
    }
    assert get.call_args_list[2].kwargs["params"] == {
        "date_from": "2026-07-15",
        "date_to": "2026-07-15",
    }


READ_SCENARIOS = {
    "merchant_analytics": {
        "message": "How often and how much do I spend at Merivale?",
        "plan": {
            "filters": {"merchant": "Merivale"},
            "calculation": ["count", "sum", "average"],
        },
        "grounding_rows": [MERIVALE_TRANSACTIONS],
        "query_rows": [MERIVALE_TRANSACTIONS],
    },
    "discrete_dates": {
        "message": "List all purchases spent on the 10th June and 15th July",
        "plan": {
            "filters": {"dates": ["2026-06-10", "2026-07-15"]},
            "calculation": "none",
        },
        "grounding_rows": [],
        "query_rows": [JUNE_TENTH, JULY_FIFTEENTH],
    },
}


def run_read_scenario(client, monkeypatch, scenario, mcp_enabled):
    """Run one read scenario over MCP or the database and return the result.

    Both paths see the same rows: with MCP on the tool replays exactly what
    the database would have returned for each query.
    """
    monkeypatch.setattr(backend_app.config, "MCP_ENABLED", mcp_enabled)
    monkeypatch.setattr(
        backend_app.config, "MCP_TOOL_SUPPORTS_EXTENDED_FILTERS", True,
    )
    database_rows = list(scenario["grounding_rows"])
    if not mcp_enabled:
        database_rows += scenario["query_rows"]
    fake_database(monkeypatch, *database_rows)
    replies = list(scenario["query_rows"])
    monkeypatch.setattr(
        transaction_source.mcp_client,
        "call_tool",
        lambda name, arguments: (replies.pop(0), 5.0),
    )
    use_plan(monkeypatch, extraction(**scenario["plan"]))

    response = client.post("/chat", json={"message": scenario["message"]})

    assert response.status_code == 200
    return response.get_json()


@mark.parametrize("name", sorted(READ_SCENARIOS))
def test_read_results_are_identical_with_the_mcp_switch_on_or_off(
    name,
    client: FlaskClient,
):
    scenario = READ_SCENARIOS[name]

    with MonkeyPatch.context() as patch:
        database = run_read_scenario(client, patch, scenario, False)
    with MonkeyPatch.context() as patch:
        tool = run_read_scenario(client, patch, scenario, True)

    assert tool["reply"] == database["reply"]
    assert tool["analytics"] == database["analytics"]
    assert tool["transactions"] == database["transactions"]
    assert tool["filters"] == database["filters"]
    assert database["agent"]["tools"][0]["status"] == "skipped_disabled"
    assert [call["status"] for call in tool["agent"]["tools"]] == [
        "succeeded" for _ in scenario["query_rows"]
    ]


# --- request validation and logging ------------------------------------------


def test_chat_routes_reject_invalid_bodies_and_unsupported_fields(
    client: FlaskClient,
):
    form_body = client.post("/chat", data={"message": "hello"})
    missing_message = client.post("/chat", json={})
    unknown_field = client.post(
        "/chat",
        json={"message": "hello", "mode": "fast"},
    )
    unsupported_apply = client.post(
        "/chat/apply",
        json={
            "operation": "update",
            "transaction_id": 27,
            "fields": {"status": "approved"},
        },
    )

    assert form_body.status_code == 400
    assert form_body.get_json()["code"] == "invalid_json"
    assert missing_message.status_code == 422
    assert missing_message.get_json()["code"] == "invalid_message"
    assert unknown_field.status_code == 422
    assert unknown_field.get_json()["code"] == "unsupported_fields"
    assert unsupported_apply.status_code == 422
    assert unsupported_apply.get_json()["code"] == "invalid_request_id"


def test_chat_workflow_logs_are_redacted_and_never_break_the_request(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    caplog,
    capsys,
):
    private_message = "Count my private Release Evidence transactions"
    fake_database(
        monkeypatch, MERIVALE_TRANSACTIONS, CATEGORIES, MERIVALE_TRANSACTIONS,
    )
    use_plan(monkeypatch, extraction(calculation="count"))

    with caplog.at_level(logging.INFO, logger=client.application.logger.name):
        response = client.post("/chat", json={"message": private_message})

    assert response.status_code == 200
    records = [
        json.loads(record.getMessage().split("AI_WORKFLOW ", 1)[1])
        for record in caplog.records
        if "AI_WORKFLOW " in record.getMessage()
    ]
    assert [record["event"] for record in records] == [
        "MCP_TOOL",
        *["ai_workflow_stage"] * 4,
        "ai_workflow_complete",
    ]
    assert [record["stage"] for record in records[1:-1]] == [
        "PLAN", "ACT", "OBSERVE", "ADAPT",
    ]
    assert {record["request_id"] for record in records} == {
        response.get_json()["agent"]["request_id"]
    }
    assert records[-1]["status"] == "complete"
    assert private_message not in caplog.text

    monkeypatch.setattr(
        client.application.logger,
        "info",
        Mock(side_effect=OSError("logging failed")),
    )
    response = client.post(
        "/chat",
        json={"message": "How many transactions are there?"},
    )

    assert response.status_code == 200
    assert response.get_json()["analytics"]["count"] == 3
    assert "AI_WORKFLOW_LOG_FAILURE OSError" in capsys.readouterr().err


# --- HTMX cards ----------------------------------------------------------------


def test_ui_chat_panel_renders_and_clear_returns_empty_fragment(
    client: FlaskClient,
):
    panel = client.get("/ui/chat")
    clear = client.get("/ui/chat/clear")

    assert panel.status_code == 200
    assert 'hx-post="/transactions-backend/ui/chat"' in panel.text
    assert 'id="transaction-chat-response"' in panel.text
    assert "hx-on:transaction-completed" in panel.text
    assert clear.status_code == 200
    assert clear.text == ""


def test_ui_chat_renders_read_result_with_completion_trigger(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, MERIVALE_TRANSACTIONS, MERIVALE_TRANSACTIONS)
    use_plan(monkeypatch, extraction(
        filters={"merchant": "Merivale"},
        calculation=["count", "average"],
    ))

    response = client.post(
        "/ui/chat",
        data={"message": "How often do I spend at Merivale?"},
    )

    assert response.status_code == 200
    assert "3 matching transactions" in response.text
    assert "$67.50" in response.text
    assert response.headers["HX-Trigger"] == "transaction-completed"


def test_ui_chat_confirmation_preview_then_apply_renders_success(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, CATEGORIES, CATEGORIES, ATOMIC_CAFE_ROW)
    stub_write(monkeypatch, "post", ATOMIC_CAFE_ROW, status=201)
    use_plan(monkeypatch, create_plan())
    message = f"{ATOMIC_CAFE_MESSAGE} in Dining"

    card = client.post("/ui/chat", data={"message": message})

    assert card.status_code == 200
    assert "Atomic Cafe" in card.text
    assert "$24.50" in card.text
    assert 'hx-post="/transactions-backend/ui/chat/apply"' in card.text
    assert 'name="preview"' in card.text
    assert 'hx-get="/transactions-backend/ui/chat/clear"' in card.text
    assert 'name="adjustment"' in card.text

    preview = preview_for(client, message)
    response = client.post(
        "/ui/chat/apply",
        data={
            "preview": json.dumps(preview),
            "request_id": preview["request_id"],
        },
    )

    assert response.status_code == 200
    assert "Your transaction was added successfully." in response.text
    assert response.headers["HX-Trigger"] == (
        "transactionsChanged, transaction-completed"
    )


def test_ui_chat_adjustment_replans_from_stored_request_context(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, CATEGORIES)
    original = f"{ATOMIC_CAFE_MESSAGE} in Dining"
    planner = use_plans(monkeypatch, create_plan(), create_plan(amount=30))
    initial = client.post("/chat", json={"message": original}).get_json()

    response = client.post(
        "/ui/chat",
        data={
            "request_id": initial["agent"]["request_id"],
            "adjustment": "Change the amount to $30",
        },
    )

    assert response.status_code == 200
    assert planner.call_args_list[1].args[0] == (
        f"{original}\nRequested change: Change the amount to $30"
    )
    assert "$30.00" in response.text
    assert 'name="adjustment"' in response.text


def test_ui_chat_category_suggestion_then_selection_renders_preview(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    fake_database(monkeypatch, [], CATEGORIES)
    use_plan(monkeypatch, create_plan())

    suggestion = client.post("/ui/chat", data={"message": ATOMIC_CAFE_MESSAGE})

    assert suggestion.status_code == 200
    assert "Suggested category" in suggestion.text
    assert "Dining" in suggestion.text
    assert 'hx-post="/transactions-backend/ui/chat/category"' in suggestion.text
    for field in ("request_id", "category_id", "request_context"):
        assert f'name="{field}"' in suggestion.text
    request_id = re.search(
        r'name="request_id"\s+value="([^"]+)"', suggestion.text,
    ).group(1)

    response = client.post(
        "/ui/chat/category",
        data={
            "request_id": request_id,
            "category_id": "81",
            "request_context": ATOMIC_CAFE_MESSAGE,
        },
    )

    assert response.status_code == 200
    assert "Groceries" in response.text
    assert 'name="preview"' in response.text
    assert transaction_orchestrator.get_preview_request_context(
        request_id
    ) == ATOMIC_CAFE_MESSAGE
