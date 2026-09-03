import json
from unittest.mock import Mock

from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark, raises

import janelle.backend.app as backend_app
import janelle.backend.services.transaction_orchestrator as transaction_orchestrator


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


@fixture
def client():
    transaction_orchestrator.reset_transaction_requests()
    with backend_app.app.test_client() as test_client:
        yield test_client
    transaction_orchestrator.reset_transaction_requests()


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


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


def use_extraction(monkeypatch: MonkeyPatch, result):
    planned = {
        **result,
        "planning_error": (
            result.get("planning_error")
            or ("invalid_plan" if result.get("fallback") else None)
        ),
        "retryable": result.get("retryable", False),
    }
    planner = Mock(return_value=planned)
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service,
        "create_plan",
        planner,
    )
    return planner


def test_chat_create_previews_then_apply_performs_exactly_one_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    created = {
        "id": 90,
        "date": "2026-09-01T00:00:00",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 80,
    }
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(CATEGORIES),
        response_with_json(created),
    ])
    post = Mock(return_value=response_with_json(created, status=201))
    monkeypatch.setattr(backend_app.requests, "get", get)
    monkeypatch.setattr(backend_app.requests, "post", post)
    planner = use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))

    preview_response = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50 in Dining"
            ),
        },
    )

    assert preview_response.status_code == 200
    preview_result = preview_response.get_json()
    assert preview_result["requires_confirmation"] is True
    assert [
        item["stage"] for item in preview_result["agent"]["trace"]
    ] == ["PLAN", "ACT", "OBSERVE", "ADAPT"]
    assert preview_result["agent"]["models"] == {
        "planner": "qwen2.5:3b"
    }
    assert "reviewer_available" not in preview_result["agent"]
    assert "reviewer_error" not in preview_result["agent"]
    assert preview_result["preview"]["before"] is None
    assert preview_result["preview"]["after"] == {
        "id": None,
        "date": "2026-09-01",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 80,
        "category_name": "Dining",
    }
    post.assert_not_called()

    apply_response = client.post(
        "/chat/apply",
        json=preview_result["preview"],
    )

    assert apply_response.status_code == 200
    apply_result = apply_response.get_json()
    assert apply_result["transaction"]["id"] == 90
    assert apply_result["verified"] is True
    assert apply_result["reply"] == "Your transaction was added successfully."
    assert planner.call_count == 1
    post.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions",
        json={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category_id": 80,
        },
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_delayed_category_selection_cannot_replace_applying_preview(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
            response_with_json(CATEGORIES),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))
    suggestion = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50"
            ),
        },
    ).get_json()
    request_id = suggestion["agent"]["request_id"]
    preview = client.post(
        "/chat/category",
        json={"request_id": request_id, "category_id": 80},
    ).get_json()["preview"]
    replay, stored = transaction_orchestrator.begin_apply(request_id, preview)

    assert replay is False
    assert stored == preview
    with raises(transaction_orchestrator.chat_service.ChatError) as error:
        transaction_orchestrator.register_selected_preview(
            request_id,
            {
                **preview,
                "fields": {
                    **preview["fields"],
                    "category_id": 81,
                },
            },
        )
    assert error.value.code == "agent_request_unavailable"


def test_chat_create_without_category_returns_ai_suggestion(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Unknown merchant",
            "description": "Card purchase",
            "amount": 12.34,
            "category": "Dining",
        },
    ))

    response = client.post(
        "/chat",
        json={
            "message": (
                "Add a card purchase at Unknown merchant on "
                "1 September 2026 for $12.34"
            ),
        },
    )

    assert response.status_code == 200
    result = response.get_json()
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


def test_chat_prefers_recent_user_category_correction_for_merchant(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([
                {
                    "user_category_id": 81,
                    "user_category_name": "Groceries",
                },
            ]),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))

    response = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50"
            ),
        },
    )

    assert response.status_code == 200
    selection = response.get_json()["category_selection"]
    assert selection["suggested_category_id"] == 81
    assert selection["suggested_category_name"] == "Groceries"


def test_chat_create_missing_fields_requests_targeted_clarification(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "merchant": "Atomic Cafe",
            "description": "Lunch",
        },
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


def test_chat_invalid_ai_category_lists_available_choices(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Unknown category",
        },
    ))

    response = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50"
            ),
        },
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["category_selection"]["suggested_category_id"] is None
    assert result["category_selection"]["requires_user_response"] is True
    assert [item["name"] for item in result["categories"]] == [
        "Uncategorised",
        "Dining",
        "Groceries",
    ]


def test_chat_accepts_ai_category_before_building_create_preview(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
            response_with_json(CATEGORIES),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))

    suggestion = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50"
            ),
        },
    ).get_json()
    response = client.post(
        "/chat/category",
        json={
            "request_id": suggestion["agent"]["request_id"],
            "category_id": 80,
        },
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["requires_confirmation"] is True
    assert result["preview"]["fields"]["category_id"] == 80
    assert "suggested_category_id" not in result["preview"]
    assert result["category_selection"]["source"] == "ai_suggestion"


def test_chat_category_override_is_authoritative_and_replay_safe(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    created = {
        "id": 90,
        "date": "2026-09-01T00:00:00",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 81,
    }
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json([]),
        response_with_json(CATEGORIES),
        response_with_json(CATEGORIES),
        response_with_json(created),
    ])
    post = Mock(return_value=response_with_json(created, status=201))
    monkeypatch.setattr(backend_app.requests, "get", get)
    monkeypatch.setattr(backend_app.requests, "post", post)
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))

    suggestion = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50"
            ),
        },
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
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions",
        json={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category_id": 81,
            "suggested_category_id": 80,
        },
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_chat_rejects_tampered_server_issued_preview(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    post = Mock()
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(return_value=response_with_json(CATEGORIES)),
    )
    monkeypatch.setattr(backend_app.requests, "post", post)
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))

    preview = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50 in Dining"
            ),
        },
    ).get_json()["preview"]
    preview["fields"]["amount"] = 1

    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 422
    assert response.get_json()["code"] == "invalid_preview"
    post.assert_not_called()


def test_chat_does_not_retry_indeterminate_committed_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    unexpected = {
        "id": 90,
        "date": "2026-09-01T00:00:00",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 99.0,
        "category_id": 80,
    }
    post = Mock(return_value=response_with_json(unexpected, status=201))
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(CATEGORIES),
        ]),
    )
    monkeypatch.setattr(backend_app.requests, "post", post)
    planner = use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))
    preview = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50 in Dining"
            ),
        },
    ).get_json()["preview"]

    first = client.post("/chat/apply", json=preview)
    replay = client.post("/chat/apply", json=preview)

    assert first.status_code == 200
    result = first.get_json()
    assert result["verified"] is False
    assert result["write_outcome_unknown"] is True
    assert result["fallback"] is True
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
    post = Mock(return_value=response_with_json(
        {
            "error": "amount is invalid",
            "code": "invalid_amount",
        },
        status=422,
    ))
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(CATEGORIES),
        ]),
    )
    monkeypatch.setattr(backend_app.requests, "post", post)
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))
    preview = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 1 September 2026 "
                "for $24.50 in Dining"
            ),
        },
    ).get_json()["preview"]

    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 422
    assert response.get_json() == {
        "error": "amount is invalid",
        "code": "invalid_amount",
    }
    assert post.call_count == 1


def test_chat_update_shows_before_after_and_rechecks_before_apply(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    updated = {
        **current,
        "amount": 90.0,
    }
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(current),
        response_with_json(CATEGORIES),
        response_with_json(current),
        response_with_json(updated),
    ])
    patch = Mock(return_value=response_with_json(updated))
    monkeypatch.setattr(backend_app.requests, "get", get)
    monkeypatch.setattr(backend_app.requests, "patch", patch)
    use_extraction(monkeypatch, extraction(
        operation="update",
        transaction_id=27,
        fields={"amount": 90.0},
    ))

    preview_response = client.post(
        "/chat",
        json={"message": "Change transaction 27 to $90"},
    )

    preview = preview_response.get_json()["preview"]
    assert preview["before"]["amount"] == 84.5
    assert preview["after"]["amount"] == 90.0
    assert preview["changes"] == {
        "amount": {"before": 84.5, "after": 90.0}
    }
    patch.assert_not_called()

    apply_response = client.post("/chat/apply", json=preview)

    assert apply_response.status_code == 200
    assert apply_response.get_json()["verified"] is True
    assert (
        apply_response.get_json()["reply"]
        == "Your transaction was updated successfully."
    )
    patch.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions/27",
        json={"amount": 90.0},
        headers={
            "X-Expected-Transaction": (
                transaction_orchestrator.chat_service.expected_transaction_header(
                    preview["before"]
                )
            ),
        },
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_chat_replans_recoverable_action_validation_error(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(current),
            response_with_json(current),
        ]),
    )
    plans = Mock(side_effect=[
        {
            **extraction(
                operation="update",
                transaction_id=27,
                fields={
                    "category_id": 80,
                    "category": "Groceries",
                },
            ),
            "planning_error": None,
            "retryable": False,
        },
        {
            **extraction(
                operation="update",
                transaction_id=27,
                fields={"category_id": 81},
            ),
            "planning_error": None,
            "retryable": False,
        },
    ])
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service,
        "create_plan",
        plans,
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


def test_chat_discards_model_id_not_grounded_in_user_request(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    atomic_cafe = {
        "id": 90,
        "date": "2026-09-01T00:00:00",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 80,
        "version": "2026-09-01T12:00:00.123456",
    }
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([
                MERIVALE_TRANSACTIONS[0],
                atomic_cafe,
            ]),
            response_with_json([atomic_cafe]),
        ]),
    )
    use_extraction(monkeypatch, extraction(
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


def test_chat_requires_grounded_id_and_filters_to_match(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    atomic_cafe = {
        "id": 90,
        "date": "2026-09-01T00:00:00",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 80,
        "version": "2026-09-01T12:00:00.123456",
    }
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([
                MERIVALE_TRANSACTIONS[0],
                atomic_cafe,
            ]),
            response_with_json([atomic_cafe]),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="delete",
        transaction_id=27,
        filters={"merchant": "Atomic Cafe"},
    ))

    response = client.post(
        "/chat",
        json={
            "message": (
                "Delete transaction 27 if it is the Atomic Cafe purchase"
            ),
        },
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["requires_clarification"] is True
    assert result["preview"] is None


@mark.parametrize(
    "message",
    [
        "Delete transaction ID: 27",
        "Delete transaction id=27",
        "Delete transaction #27",
        "Delete #27",
    ],
)
def test_transaction_id_grounding_accepts_explicit_punctuation(message):
    assert transaction_orchestrator.transaction_id_is_grounded(message, 27)


def test_chat_does_not_offer_update_confirmation_without_version(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = {
        key: value
        for key, value in MERIVALE_TRANSACTIONS[0].items()
        if key != "version"
    }
    patch = Mock()
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(current),
        ]),
    )
    monkeypatch.setattr(backend_app.requests, "patch", patch)
    use_extraction(monkeypatch, extraction(
        operation="update",
        transaction_id=27,
        fields={"amount": 90.0},
    ))

    response = client.post(
        "/chat",
        json={"message": "Change transaction 27 to $90"},
    )

    assert response.status_code == 502
    assert response.get_json()["code"] == "invalid_database_response"
    patch.assert_not_called()


def test_chat_apply_rejects_stale_update(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    changed = {**current, "amount": 85.0}
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(current),
        response_with_json(CATEGORIES),
        response_with_json(changed),
    ])
    patch = Mock()
    monkeypatch.setattr(backend_app.requests, "get", get)
    monkeypatch.setattr(backend_app.requests, "patch", patch)
    use_extraction(monkeypatch, extraction(
        operation="update",
        transaction_id=27,
        fields={"amount": 90.0},
    ))

    preview = client.post(
        "/chat",
        json={"message": "Change transaction 27 to $90"},
    ).get_json()["preview"]
    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 409
    assert response.get_json()["code"] == "stale_preview"
    patch.assert_not_called()


def test_chat_apply_rejects_changed_version_even_when_values_match(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    reversioned = {
        **current,
        "version": "2026-09-02T12:00:00.654321",
    }
    patch = Mock()
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(current),
            response_with_json(CATEGORIES),
            response_with_json(reversioned),
        ]),
    )
    monkeypatch.setattr(backend_app.requests, "patch", patch)
    use_extraction(monkeypatch, extraction(
        operation="update",
        transaction_id=27,
        fields={"amount": 90.0},
    ))

    preview = client.post(
        "/chat",
        json={"message": "Change transaction 27 to $90"},
    ).get_json()["preview"]
    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 409
    assert response.get_json()["code"] == "stale_preview"
    patch.assert_not_called()


def test_chat_delete_preview_contains_full_row_and_cancel_does_not_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    delete = Mock()
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(current),
        ]),
    )
    monkeypatch.setattr(backend_app.requests, "delete", delete)
    use_extraction(monkeypatch, extraction(
        operation="delete",
        transaction_id=27,
    ))

    response = client.post(
        "/chat",
        json={"message": "Delete transaction 27"},
    )

    preview = response.get_json()["preview"]
    assert preview["before"] == {
        **current,
        "category_name": "Dining",
    }
    assert preview["after"] is None
    assert response.get_json()["requires_confirmation"] is True
    delete.assert_not_called()


def test_chat_delete_apply_rechecks_and_performs_exactly_one_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(current),
        response_with_json(CATEGORIES),
        response_with_json(current),
        response_with_json(
            {
                "error": "transaction not found",
                "code": "transaction_not_found",
            },
            status=404,
        ),
    ])
    delete = Mock(return_value=response_with_json(None, status=204))
    monkeypatch.setattr(backend_app.requests, "get", get)
    monkeypatch.setattr(backend_app.requests, "delete", delete)
    use_extraction(monkeypatch, extraction(
        operation="delete",
        transaction_id=27,
    ))

    preview = client.post(
        "/chat",
        json={"message": "Delete transaction 27"},
    ).get_json()["preview"]
    response = client.post("/chat/apply", json=preview)

    assert response.status_code == 200
    assert response.get_json()["deleted"]["id"] == 27
    assert response.get_json()["verified"] is True
    assert (
        response.get_json()["reply"]
        == "Your transaction was deleted successfully."
    )
    delete.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions/27",
        headers={
            "X-Expected-Transaction": (
                transaction_orchestrator.chat_service.expected_transaction_header(
                    preview["before"]
                )
            ),
        },
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_chat_ambiguous_update_returns_clarification_without_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    spotify = [
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
    patch = Mock()
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(spotify),
            response_with_json(spotify),
        ]),
    )
    monkeypatch.setattr(backend_app.requests, "patch", patch)
    use_extraction(monkeypatch, extraction(
        operation="update",
        fields={"amount": 19.99},
        filters={"merchant": "Spotify AU"},
    ))
    response = client.post(
        "/chat",
        json={"message": "Update Spotify to $19.99"},
    )

    result = response.get_json()
    assert result["requires_clarification"] is True
    assert result["agent"]["status"] == "clarify"
    assert [row["id"] for row in result["matches"]] == [25, 26]
    assert result["preview"] is None
    patch.assert_not_called()


def test_chat_calculates_count_sum_and_average_from_database_rows(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(MERIVALE_TRANSACTIONS),
        response_with_json(MERIVALE_TRANSACTIONS),
    ])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, extraction(
        filters={"merchant": "Merivale"},
        calculation=["count", "sum", "average"],
    ))

    response = client.post(
        "/chat",
        json={"message": "How often and how much do I spend at Merivale?"},
    )

    result = response.get_json()
    assert response.status_code == 200
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
    assert get.call_args_list[-1].kwargs["params"] == {
        "merchant": "Merivale"
    }


def test_chat_ranks_largest_purchases_from_database_rows(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(MERIVALE_TRANSACTIONS),
    ])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, extraction(
        filters={
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
        },
        calculation="largest",
    ))

    response = client.post(
        "/chat",
        json={"message": "Show my biggest purchases in August"},
    )

    result = response.get_json()
    assert response.status_code == 200
    assert [transaction["id"] for transaction in result["transactions"]] == [
        27,
        29,
        28,
    ]
    assert result["analytics"]["calculations"] == ["largest"]
    assert result["analytics"]["count"] == 3
    assert result["reply"] == "Here are your 3 biggest matching purchases."
    assert get.call_args_list[-1].kwargs["params"] == {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
    }


def test_chat_totals_eating_out_during_previous_week(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    dining_transactions = [
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
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(dining_transactions),
    ])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, extraction(
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

    result = response.get_json()
    assert response.status_code == 200
    assert result["analytics"]["sum"] == 123.2
    assert "$123.20" in result["reply"]
    assert "from 24 Aug 2026 to 30 Aug 2026" in result["reply"]
    assert "from 26 Aug 2026" not in result["reply"]
    assert get.call_args_list[-1].kwargs["params"] == {
        "date_from": "2026-08-24",
        "date_to": "2026-08-30",
        "category_id": 80,
    }


def test_chat_totals_woolworths_in_august(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    woolworths = [{
        "id": 32,
        "date": "2026-08-22T00:00:00",
        "merchant": "Woolworths",
        "description": "Weekly groceries",
        "amount": 86.45,
        "category_id": 81,
    }]
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(woolworths),
        response_with_json(woolworths),
    ])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, extraction(
        filters={
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "merchant": "Woolworths",
        },
        calculation="sum",
    ))

    response = client.post(
        "/chat",
        json={"message": "What did I spend at Woolworths in August?"},
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["analytics"]["count"] == 1
    assert result["analytics"]["sum"] == 86.45
    assert result["reply"] == (
        "I calculated a total of $86.45 "
        "from 1 Aug 2026 to 31 Aug 2026."
    )
    assert get.call_args_list[-1].kwargs["params"] == {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "merchant": "Woolworths",
    }


@mark.parametrize("fragment", ["Anytime Fitness", "membership fee"])
def test_chat_resolves_partial_merchant_or_description(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    fragment,
):
    anytime_fitness = [
        {
            "id": 14,
            "date": "2026-07-08T00:00:00",
            "merchant": "Anytime Fitness Ultimo",
            "description": "Direct debit membership fee",
            "amount": 17.5,
            "category_id": 31,
        },
        {
            "id": 7,
            "date": "2026-06-24T00:00:00",
            "merchant": "Anytime Fitness Ultimo",
            "description": "Direct debit membership fee",
            "amount": 17.5,
            "category_id": 31,
        },
    ]
    categories = [
        *CATEGORIES,
        {"id": 31, "name": "Fitness", "type": "want"},
    ]
    get = Mock(side_effect=[
        response_with_json(categories),
        response_with_json(anytime_fitness),
        response_with_json(anytime_fitness),
    ])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, extraction(
        filters={"merchant": fragment},
        calculation="none",
    ))

    response = client.post(
        "/chat",
        json={"message": f"List purchases containing {fragment}"},
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["filters"] == {"q": fragment}
    assert [transaction["id"] for transaction in result["transactions"]] == [
        14,
        7,
    ]
    assert get.call_args_list[-1].kwargs["params"] == {"q": fragment}


def test_chat_normalizes_exact_date_filter(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    june_tenth = [
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
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(june_tenth),
    ])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, extraction(
        filters={"date": "2026-06-10"},
        calculation="none",
    ))

    response = client.post(
        "/chat",
        json={"message": "List all purchases spent on the 10th June"},
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["filters"] == {
        "date_from": "2026-06-10",
        "date_to": "2026-06-10",
    }
    assert [transaction["id"] for transaction in result["transactions"]] == [
        2,
        1,
    ]
    assert "on 10 Jun 2026" in result["reply"]
    assert get.call_args_list[-1].kwargs["params"] == result["filters"]


def test_chat_queries_multiple_discrete_dates(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    june_tenth = [
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
    july_fifteenth = [
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
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json(june_tenth),
        response_with_json(july_fifteenth),
    ])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, extraction(
        filters={
            "dates": ["2026-06-10", "2026-07-15"],
        },
        calculation="none",
    ))

    response = client.post(
        "/chat",
        json={
            "message": (
                "List all purchases spent on the 10th June "
                "and the 15th July"
            ),
        },
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["filters"] == {
        "dates": ["2026-06-10", "2026-07-15"],
    }
    assert [transaction["id"] for transaction in result["transactions"]] == [
        4,
        3,
        2,
        1,
    ]
    assert result["analytics"]["count"] == 4
    assert "on 10 Jun 2026 and 15 Jul 2026" in result["reply"]
    assert get.call_args_list[1].kwargs["params"] == {
        "date_from": "2026-06-10",
        "date_to": "2026-06-10",
    }
    assert get.call_args_list[2].kwargs["params"] == {
        "date_from": "2026-07-15",
        "date_to": "2026-07-15",
    }


def test_chat_invalid_model_result_is_safe_and_non_writing(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    post = Mock()
    patch = Mock()
    delete = Mock()
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
        ]),
    )
    monkeypatch.setattr(backend_app.requests, "post", post)
    monkeypatch.setattr(backend_app.requests, "patch", patch)
    monkeypatch.setattr(backend_app.requests, "delete", delete)
    use_extraction(monkeypatch, {
        "operation": "read",
        "transaction_id": None,
        "fields": {},
        "filters": {},
        "calculation": "none",
        "handoff": "none",
        "reply": "I could not safely understand that request. No changes were made.",
        "fallback": True,
    })

    response = client.post("/chat", json={"message": "Do something unsafe"})

    result = response.get_json()
    assert result["fallback"] is True
    assert result["requires_confirmation"] is False
    assert result["preview"] is None
    post.assert_not_called()
    patch.assert_not_called()
    delete.assert_not_called()


def test_chat_replans_one_invalid_plan_then_completes(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(MERIVALE_TRANSACTIONS),
        ]),
    )
    plans = Mock(side_effect=[
        {
            **extraction(fallback=True),
            "planning_error": "unsupported fields: status",
            "retryable": True,
        },
        {
            **extraction(calculation="count"),
            "planning_error": None,
            "retryable": False,
        },
    ])
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service,
        "create_plan",
        plans,
    )
    response = client.post(
        "/chat",
        json={"message": "How many transactions are there?"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["analytics"]["count"] == 3
    assert [item["stage"] for item in result["agent"]["trace"]] == [
        "PLAN",
        "ACT",
        "OBSERVE",
        "ADAPT",
        "PLAN",
        "ACT",
        "OBSERVE",
        "ADAPT",
    ]
    assert result["agent"]["trace"][3]["status"] == "replan"
    assert plans.call_count == 2


def test_chat_routes_reject_invalid_bodies_and_apply_fields(
    client: FlaskClient,
):
    form_response = client.post("/chat", data={"message": "hello"})
    missing_message = client.post("/chat", json={})
    unsupported_apply = client.post(
        "/chat/apply",
        json={
            "operation": "update",
            "transaction_id": 27,
            "fields": {"status": "approved"},
        },
    )

    assert form_response.status_code == 400
    assert form_response.get_json()["code"] == "invalid_json"
    assert missing_message.status_code == 422
    assert missing_message.get_json()["code"] == "invalid_message"
    assert unsupported_apply.status_code == 422
    assert unsupported_apply.get_json()["code"] == "invalid_request_id"


def test_ui_chat_panel_is_rendered_from_jinja(client: FlaskClient):
    response = client.get("/ui/chat")

    assert response.status_code == 200
    assert "Ask Tally" in response.text
    assert 'hx-post="/transactions-backend/ui/chat"' in response.text
    assert 'id="transaction-chat-response"' in response.text
    assert response.text.count("hx-on::before-request") == 3
    assert (
        "document.getElementById('transaction-chat-input').value = ''"
        in response.text
    )
    assert "hx-on:transaction-completed" in response.text


def test_ui_chat_renders_deterministic_read_result(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(MERIVALE_TRANSACTIONS),
            response_with_json(MERIVALE_TRANSACTIONS),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        filters={"merchant": "Merivale"},
        calculation=["count", "average"],
    ))

    response = client.post(
        "/ui/chat",
        data={"message": "How often do I spend at Merivale?"},
    )

    assert response.status_code == 200
    assert "I calculated 3 matching transactions" in response.text
    assert "3" in response.text
    assert "transactions" in response.text
    assert "Average $67.50" in response.text
    assert response.headers["HX-Trigger"] == "transaction-completed"


def test_ui_chat_renders_ranked_largest_purchases(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(MERIVALE_TRANSACTIONS),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        filters={
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
        },
        calculation="largest",
    ))

    response = client.post(
        "/ui/chat",
        data={"message": "Show my biggest purchases in August"},
    )

    assert response.status_code == 200
    assert "Biggest purchases" in response.text
    assert response.text.index("$84.50") < response.text.index("$76.00")
    assert response.text.index("$76.00") < response.text.index("$42.00")


def test_ui_chat_renders_all_transactions_for_list_request(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    harbourview = [
        {
            "id": transaction_id,
            "date": date,
            "merchant": "Harbourview Realty",
            "description": "Rent payment",
            "amount": 1100.0,
            "category_id": 30,
        }
        for transaction_id, date in (
            (6, "2026-06-24T00:00:00"),
            (5, "2026-06-10T00:00:00"),
            (1, "2026-06-10T00:00:00"),
        )
    ]
    categories = [
        *CATEGORIES,
        {"id": 30, "name": "Housing", "type": "need"},
    ]
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(categories),
            response_with_json(harbourview),
            response_with_json(harbourview),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        filters={"merchant": "Harbourview Realty"},
        calculation="none",
    ))

    response = client.post(
        "/ui/chat",
        data={
            "message": (
                "List all tranasctions I spent with Harbourview Realty"
            ),
        },
    )

    assert response.status_code == 200
    assert "Matching transactions" in response.text
    assert response.text.count("Harbourview Realty") == 3
    assert "#6" not in response.text
    assert "#5" not in response.text
    assert "#1" not in response.text
    assert response.text.count("$1,100.00") == 3
    assert response.text.count("Housing") == 3


def test_ui_chat_clarification_shows_candidate_transaction_ids(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    spotify = [
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
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(spotify),
            response_with_json(spotify),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="update",
        fields={"amount": 19.99},
        filters={"merchant": "Spotify AU"},
    ))

    response = client.post(
        "/ui/chat",
        data={"message": "Update Spotify AU to $19.99"},
    )

    assert response.status_code == 200
    assert "#25" in response.text
    assert "#26" in response.text
    assert "Your answer" in response.text
    assert 'name="clarification"' in response.text
    assert 'name="original_message"' in response.text


def test_ui_chat_clarification_carries_original_request_forward(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(return_value=response_with_json(CATEGORIES)),
    )
    planner = use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-02",
            "merchant": "Cat Cafe",
            "description": "Coffee",
            "amount": 25.0,
            "category": "Dining",
        },
    ))
    original = "Add a transaction at Cat Cafe for $25 in Dining"
    clarification = "Use 2 September 2026 and description Coffee"

    response = client.post(
        "/ui/chat",
        data={
            "original_message": original,
            "clarification": clarification,
        },
    )

    assert response.status_code == 200
    assert "Create preview" not in response.text
    assert "Ready for your review" in response.text
    assert "Cat Cafe" in response.text
    assert "Coffee" in response.text
    assert planner.call_args.args[0] == (
        f"{original}.\nAdditional details: {clarification}"
    )


def test_ui_chat_delete_preview_shows_id_and_destructive_warning(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(current),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="delete",
        transaction_id=27,
    ))

    response = client.post(
        "/ui/chat",
        data={"message": "Delete transaction 27"},
    )

    assert response.status_code == 200
    assert "This will permanently delete the transaction below." in response.text
    assert "Transaction to delete" in response.text
    assert "#27" in response.text
    assert "Want to change something?" not in response.text
    assert 'id="transaction-chat-adjustment"' not in response.text


def test_ui_chat_renders_jinja_confirmation_preview(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))

    response = client.post(
        "/ui/chat",
        data={
            "message": (
                "Add lunch at Atomic Cafe on 2 September 2026 "
                "for $24.50 in Dining"
            ),
        },
    )

    assert response.status_code == 200
    assert "Create preview" not in response.text
    assert "Transaction to create" in response.text
    assert "Atomic Cafe" in response.text
    assert "$24.50" in response.text
    assert 'hx-post="/transactions-backend/ui/chat/apply"' in response.text
    assert 'name="preview"' in response.text
    assert ">Confirm</button>" in response.text
    assert 'hx-get="/transactions-backend/ui/chat/clear"' in response.text
    assert "Cancel" in response.text
    assert "Ready for your review" in response.text
    assert (
        "Check the details below, then confirm when everything looks right."
        in response.text
    )
    assert "How Tally handled this" not in response.text
    assert "Want to change something?" in response.text
    assert 'id="transaction-chat-adjustment"' in response.text
    assert 'name="adjustment"' in response.text
    assert 'placeholder="Describe what you want to change"' in response.text
    assert ">Update preview</button>" in response.text
    assert (
        "Add lunch at Atomic Cafe on 2 September 2026 "
        "for $24.50 in Dining"
    ) not in response.text


def test_ui_chat_adjustment_uses_stored_request_context(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(CATEGORIES),
        ]),
    )
    original = (
        "Add lunch at Atomic Cafe on 2 September 2026 "
        "for $24.50 in Dining"
    )
    planner = use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))
    adjusted_plan = {
        **planner.return_value,
        "fields": {
            **planner.return_value["fields"],
            "amount": 30,
        },
    }
    planner.side_effect = [planner.return_value, adjusted_plan]
    initial = client.post(
        "/chat",
        json={"message": original},
    ).get_json()

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
    assert original not in response.text
    assert 'name="adjustment"' in response.text


def test_ui_chat_renders_category_suggestion_actions(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))

    response = client.post(
        "/ui/chat",
        data={
            "message": (
                "Add lunch at Atomic Cafe on 2 September 2026 "
                "for $24.50"
            ),
        },
    )

    assert response.status_code == 200
    assert "Suggested category" in response.text
    assert "Dining" in response.text
    assert "looks like the best fit" in response.text
    assert "Accept it or choose another category to continue" in response.text
    assert "Nothing will be saved until you confirm" in response.text
    assert "Tally suggests" not in response.text
    assert "The transaction has not been created" not in response.text
    assert 'hx-post="/transactions-backend/ui/chat/category"' in response.text
    assert 'name="request_id"' in response.text
    assert 'name="category_id"' in response.text
    assert 'name="request_context"' in response.text
    assert "Accept suggestion" in response.text
    assert "Use selected category" in response.text


def test_ui_chat_shows_selected_category_in_final_preview(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
            response_with_json(CATEGORIES),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category": "Dining",
        },
    ))
    suggestion = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 2 September 2026 "
                "for $24.50"
            ),
        },
    ).get_json()

    response = client.post(
        "/ui/chat/category",
        data={
            "request_id": suggestion["agent"]["request_id"],
            "category_id": "81",
            "request_context": (
                "Add lunch at Atomic Cafe on 2 September 2026 "
                "for $24.50"
            ),
        },
    )

    assert response.status_code == 200
    assert "Groceries" in response.text
    assert "AI suggested:" not in response.text
    assert "Your category:" not in response.text
    assert "Ready for your review" in response.text
    assert "Want to change something?" in response.text
    assert transaction_orchestrator.get_preview_request_context(
        suggestion["agent"]["request_id"]
    ) == (
        "Add lunch at Atomic Cafe on 2 September 2026 "
        "for $24.50"
    )


def test_ui_chat_apply_renders_success_and_refresh_trigger(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    created = {
        "id": 90,
        **preview_fields(),
    }
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(CATEGORIES),
        ]),
    )
    monkeypatch.setattr(
        backend_app.requests,
        "post",
        Mock(return_value=response_with_json(created, status=201)),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            **preview_fields(),
            "category": "Dining",
        },
    ))
    preview = client.post(
        "/chat",
        json={
            "message": (
                "Add lunch at Atomic Cafe on 2 September 2026 "
                "for $24.50 in Dining"
            ),
        },
    ).get_json()["preview"]

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


def preview_fields():
    return {
        "date": "2026-09-02",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 80,
    }
