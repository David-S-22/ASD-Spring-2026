import json
from unittest.mock import Mock

from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture, mark

import janelle.backend.app as backend_app
import janelle.backend.chat_service as chat_service


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
    },
    {
        "id": 28,
        "date": "2026-08-16T00:00:00",
        "merchant": "Merivale",
        "description": "Lunch",
        "amount": 42.0,
        "category_id": 80,
    },
    {
        "id": 29,
        "date": "2026-08-30T00:00:00",
        "merchant": "Merivale",
        "description": "Dinner",
        "amount": 76.0,
        "category_id": 80,
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
    monkeypatch.setattr(
        chat_service.ollama_service,
        "parse_chat",
        Mock(return_value=result),
    )


def test_chat_create_previews_then_apply_performs_exactly_one_write(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = Mock(side_effect=[
        response_with_json(MERIVALE_TRANSACTIONS),
        response_with_json(CATEGORIES),
        response_with_json(CATEGORIES),
    ])
    post = Mock(return_value=response_with_json({
        "id": 90,
        "date": "2026-09-01T00:00:00",
        "merchant": "Atomic Cafe",
        "description": "Lunch",
        "amount": 24.5,
        "category_id": 80,
    }, status=201))
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

    preview_response = client.post(
        "/chat",
        json={"message": "Add lunch at Atomic Cafe for $24.50"},
    )

    assert preview_response.status_code == 200
    preview_result = preview_response.get_json()
    assert preview_result["requires_confirmation"] is True
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
    assert apply_response.get_json()["transaction"]["id"] == 90
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


def test_chat_defaults_create_preview_to_uncategorised(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json([]),
            response_with_json(CATEGORIES),
        ]),
    )
    use_extraction(monkeypatch, extraction(
        operation="create",
        fields={
            "date": "2026-09-01",
            "merchant": "Unknown merchant",
            "description": "Card purchase",
            "amount": 12.34,
            "category": None,
        },
    ))

    response = client.post("/chat", json={"message": "Add this transaction"})

    assert response.status_code == 200
    assert response.get_json()["preview"]["fields"]["category_id"] == 1


def test_chat_update_shows_before_after_and_rechecks_before_apply(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    get = Mock(side_effect=[
        response_with_json(MERIVALE_TRANSACTIONS),
        response_with_json(CATEGORIES),
        response_with_json(current),
        response_with_json(CATEGORIES),
        response_with_json(current),
    ])
    patch = Mock(return_value=response_with_json({
        **current,
        "amount": 90.0,
    }))
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
    patch.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions/27",
        json={"amount": 90.0},
        timeout=backend_app.config.DATABASE_TIMEOUT_SECONDS,
    )


def test_chat_apply_rejects_stale_update(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    current = MERIVALE_TRANSACTIONS[0]
    changed = {**current, "amount": 85.0}
    get = Mock(side_effect=[
        response_with_json(MERIVALE_TRANSACTIONS),
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
            response_with_json(MERIVALE_TRANSACTIONS),
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
        response_with_json(MERIVALE_TRANSACTIONS),
        response_with_json(CATEGORIES),
        response_with_json(current),
        response_with_json(CATEGORIES),
        response_with_json(current),
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
    delete.assert_called_once_with(
        f"{backend_app.config.TRANSACTIONS_DB_URL}/transactions/27",
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
        },
        {
            "id": 26,
            "date": "2026-08-20T00:00:00",
            "merchant": "Spotify AU",
            "description": "Subscription",
            "amount": 17.99,
            "category_id": 80,
        },
    ]
    patch = Mock()
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(spotify),
            response_with_json(CATEGORIES),
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
    assert [row["id"] for row in result["matches"]] == [25, 26]
    assert result["preview"] is None
    patch.assert_not_called()


def test_chat_calculates_count_sum_and_average_from_database_rows(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    get = Mock(side_effect=[
        response_with_json(MERIVALE_TRANSACTIONS),
        response_with_json(CATEGORIES),
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
        response_with_json(MERIVALE_TRANSACTIONS),
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
        response_with_json(dining_transactions),
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
        response_with_json(woolworths),
        response_with_json(CATEGORIES),
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
        response_with_json(anytime_fitness),
        response_with_json(categories),
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
        response_with_json(june_tenth),
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
        response_with_json([*july_fifteenth, *june_tenth]),
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
    assert get.call_args_list[2].kwargs["params"] == {
        "date_from": "2026-06-10",
        "date_to": "2026-06-10",
    }
    assert get.call_args_list[3].kwargs["params"] == {
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
            response_with_json(MERIVALE_TRANSACTIONS),
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
    assert unsupported_apply.get_json()["code"] == "unsupported_fields"


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


def test_ui_chat_renders_deterministic_read_result(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(MERIVALE_TRANSACTIONS),
            response_with_json(CATEGORIES),
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


def test_ui_chat_renders_ranked_largest_purchases(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(MERIVALE_TRANSACTIONS),
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
            response_with_json(harbourview),
            response_with_json(categories),
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


def test_ui_chat_renders_jinja_confirmation_preview(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(MERIVALE_TRANSACTIONS),
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
        data={"message": "Add lunch at Atomic Cafe for $24.50"},
    )

    assert response.status_code == 200
    assert "Create preview" in response.text
    assert "Transaction to create" in response.text
    assert "Atomic Cafe" in response.text
    assert "$24.50" in response.text
    assert 'hx-post="/transactions-backend/ui/chat/apply"' in response.text
    assert 'name="preview"' in response.text
    assert ">Confirm</button>" in response.text
    assert 'hx-get="/transactions-backend/ui/chat/clear"' in response.text
    assert "Cancel" in response.text


def test_ui_chat_apply_renders_success_and_refresh_trigger(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    preview = {
        "operation": "create",
        "transaction_id": None,
        "fields": {
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category_id": 80,
        },
        "before": None,
        "after": {
            "id": None,
            "date": "2026-09-02",
            "merchant": "Atomic Cafe",
            "description": "Lunch",
            "amount": 24.5,
            "category_id": 80,
            "category_name": "Dining",
        },
        "changes": {},
    }
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(return_value=response_with_json(CATEGORIES)),
    )
    monkeypatch.setattr(
        backend_app.requests,
        "post",
        Mock(return_value=response_with_json({
            "id": 90,
            **preview["fields"],
        }, status=201)),
    )

    response = client.post(
        "/ui/chat/apply",
        data={"preview": json.dumps(preview)},
    )

    assert response.status_code == 200
    assert "confirmed create operation was saved" in response.text
    assert response.headers["HX-Trigger"] == "transactionsChanged"
