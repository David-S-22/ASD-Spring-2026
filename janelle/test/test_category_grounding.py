import json
import logging
from unittest.mock import Mock

from flask.testing import FlaskClient
from pytest import MonkeyPatch, fixture

import janelle.backend.app as backend_app
import janelle.backend.services.transaction_orchestrator as transaction_orchestrator
from janelle.backend import config
from janelle.backend.services import category_grounding, rag_answer
from janelle.backend.services.rag_client import RAGError


CATEGORIES = [
    {"id": 1, "name": "Uncategorised", "type": None},
    {"id": 31, "name": "Fitness", "type": "want"},
    {"id": 81, "name": "Groceries", "type": "need"},
]
CREATE_FIELDS = {
    "date": "2026-09-24",
    "merchant": "Anytime Fitness",
    "description": "Membership",
    "amount": 17.5,
}
MESSAGE = "Add $17.50 Anytime Fitness membership on 24 Sep 2026"


def grounded(answer="Fitness", confidence="high", **overrides):
    result = {
        "status": "grounded",
        "answer": answer,
        "confidence": confidence,
        "insufficient_context": False,
        "uncited": False,
        "derived_from_votes": False,
        "citations": [
            {
                "marker": 1,
                "id": "tx-7",
                "collection": "transactions-records",
                "source": "transaction 7",
                "excerpt": "Transaction 7 on 2026-06-24: Anytime Fitness ...",
                "distance": 0.31,
                "category_id": 31,
                "category": "Fitness",
                "date": "2026-06-24",
                "merchant": "Anytime Fitness Ultimo",
                "amount": 17.5,
            },
            {
                "marker": 2,
                "id": "transactions_categories.md_2",
                "collection": "transactions",
                "source": "categories.md",
                "excerpt": "Fitness: club direct debits such as Anytime Fitness.",
                "distance": 0.52,
            },
        ],
        "retrieved": 9,
        "survivors": 2,
        "best_distance": 0.31,
        "model_probability": 0.93,
        "model": "qwen2.5:3b",
        "thresholds": {
            "insufficient_above": 1.2,
            "high_below": 0.6,
            "medium_below": 0.9,
            "probability_high_at_least": 0.8,
            "probability_medium_at_least": 0.5,
        },
    }
    result.update(overrides)
    return result


def insufficient():
    return {
        "status": "insufficient",
        "answer": None,
        "confidence": "insufficient",
        "insufficient_context": True,
        "uncited": False,
        "derived_from_votes": False,
        "citations": [],
        "retrieved": 4,
        "survivors": 0,
        "best_distance": 1.4,
        "model": "qwen2.5:3b",
        "thresholds": {
            "insufficient_above": 1.2,
            "high_below": 0.6,
            "medium_below": 0.9,
        },
    }


def context():
    categories = [dict(item) for item in CATEGORIES]
    return {
        "categories": categories,
        "category_names": {c["id"]: c["name"] for c in categories},
        "category_ids": {c["name"].casefold(): c["id"] for c in categories},
        "request_id": "req-1",
        "phase": "initial",
        "iteration": 1,
    }


@fixture
def client():
    transaction_orchestrator.reset_transaction_requests()
    with backend_app.app.test_client() as test_client:
        yield test_client
    transaction_orchestrator.reset_transaction_requests()


@fixture
def rag_on(monkeypatch: MonkeyPatch):
    monkeypatch.setattr(config, "RAG_ENABLED", True)


def response_with_json(payload, status=200):
    response = Mock()
    response.status_code = status
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def use_extraction(monkeypatch: MonkeyPatch, fields):
    monkeypatch.setattr(
        transaction_orchestrator.ollama_service,
        "create_plan",
        Mock(return_value={
            "operation": "create",
            "transaction_id": None,
            "fields": dict(fields),
            "filters": {},
            "calculation": "none",
            "handoff": "none",
            "reply": "Prepared safely.",
            "fallback": False,
            "planning_error": None,
            "retryable": False,
        }),
    )


def use_grounded_answer(monkeypatch: MonkeyPatch, result=None, error=None):
    mock = Mock(return_value=result)
    if error is not None:
        mock = Mock(side_effect=error)
    monkeypatch.setattr(rag_answer, "grounded_answer", mock)
    return mock


def workflow_records(caplog, event):
    return [
        record
        for record in (
            json.loads(item.getMessage().split("AI_WORKFLOW ", 1)[1])
            for item in caplog.records
            if "AI_WORKFLOW " in item.getMessage()
        )
        if record["event"] == event
    ]


# --- unit level -------------------------------------------------------------


def test_disabled_switch_returns_disabled_without_calling_rag(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    answer = use_grounded_answer(monkeypatch, grounded())

    category_id, grounding = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id is None
    assert grounding == {"status": "disabled"}
    answer.assert_not_called()


def test_question_is_built_from_merchant_and_description_only(
    monkeypatch: MonkeyPatch,
    rag_on,
):
    answer = use_grounded_answer(monkeypatch, grounded())

    category_grounding.grounded_category_suggestion(CREATE_FIELDS, context())

    question = answer.call_args.args[0]
    assert question == "Merchant: Anytime Fitness; Description: Membership"
    assert "17.5" not in question
    assert "2026" not in question


def test_rag_error_degrades_to_unavailable(monkeypatch: MonkeyPatch, rag_on):
    use_grounded_answer(monkeypatch, error=RAGError("rag_http_error"))

    category_id, grounding = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id is None
    assert grounding == {"status": "unavailable", "error": "rag_http_error"}


def test_insufficient_is_passed_through(monkeypatch: MonkeyPatch, rag_on):
    use_grounded_answer(monkeypatch, insufficient())

    category_id, grounding = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id is None
    assert grounding["status"] == "insufficient"
    assert grounding["citations"] == []


def test_grounded_answer_resolves_category_id_by_casefold(
    monkeypatch: MonkeyPatch,
    rag_on,
):
    use_grounded_answer(monkeypatch, grounded(answer="fitness"))

    category_id, grounding = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id == 31
    assert grounding["status"] == "grounded"


def test_unresolvable_answer_becomes_unavailable(
    monkeypatch: MonkeyPatch,
    rag_on,
):
    use_grounded_answer(monkeypatch, grounded(answer="Retired category"))

    category_id, grounding = category_grounding.grounded_category_suggestion(
        CREATE_FIELDS,
        context(),
    )

    assert category_id is None
    assert grounding["status"] == "unavailable"
    assert grounding["error"] == "no_category_resolved"


# --- through the create flow -----------------------------------------------


def test_chat_grounded_suggestion_sets_id_and_carries_grounding(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_on,
):
    get = Mock(side_effect=[response_with_json(CATEGORIES)])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, CREATE_FIELDS)
    use_grounded_answer(monkeypatch, grounded())

    response = client.post("/chat", json={"message": MESSAGE})

    assert response.status_code == 200
    result = response.get_json()
    selection = result["category_selection"]
    assert selection["suggested_category_id"] == 31
    assert selection["suggested_category_name"] == "Fitness"
    assert selection["grounding"]["status"] == "grounded"
    assert selection["grounding"]["confidence"] == "high"
    assert len(selection["grounding"]["citations"]) == 2
    assert selection["grounding"]["citations"][1]["collection"] == "transactions"
    assert result["reply"] == (
        "I suggest Fitness. Use Fitness, or choose another category."
    )
    # The Release 0 correction vote did not run.
    assert get.call_count == 1


def test_chat_unavailable_runs_release_0_correction_vote(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_on,
):
    get = Mock(side_effect=[
        response_with_json(CATEGORIES),
        response_with_json([
            {"user_category_id": 81, "user_category_name": "Groceries"},
        ]),
    ])
    monkeypatch.setattr(backend_app.requests, "get", get)
    use_extraction(monkeypatch, CREATE_FIELDS)
    use_grounded_answer(monkeypatch, error=RAGError("rag_http_error"))

    response = client.post("/chat", json={"message": MESSAGE})

    assert response.status_code == 200
    selection = response.get_json()["category_selection"]
    assert selection["suggested_category_id"] == 81
    assert selection["grounding"] == {
        "status": "unavailable",
        "error": "rag_http_error",
    }
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["params"] == {
        "merchant": "Anytime Fitness",
        "limit": 10,
    }


def test_chat_insufficient_asks_the_user_to_choose(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_on,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
        ]),
    )
    use_extraction(monkeypatch, CREATE_FIELDS)
    use_grounded_answer(monkeypatch, insufficient())

    response = client.post("/chat", json={"message": MESSAGE})

    assert response.status_code == 200
    result = response.get_json()
    assert result["reply"] == (
        "I couldn't find past transactions or notes similar enough to "
        "suggest a category. Choose a category to continue."
    )
    selection = result["category_selection"]
    assert selection["suggested_category_id"] is None
    assert selection["grounding"]["status"] == "insufficient"
    assert selection["grounding"]["confidence"] == "insufficient"
    assert selection["grounding"]["citations"] == []


def test_chat_category_echoes_grounding_from_pending_request(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_on,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json(CATEGORIES),
            response_with_json([]),
        ]),
    )
    use_extraction(monkeypatch, CREATE_FIELDS)
    use_grounded_answer(monkeypatch, grounded(confidence="medium"))

    first = client.post("/chat", json={"message": MESSAGE}).get_json()
    second = client.post(
        "/chat/category",
        json={
            "request_id": first["agent"]["request_id"],
            "category_id": 31,
        },
    )

    assert second.status_code == 200
    selection = second.get_json()["category_selection"]
    assert selection["source"] == "ai_suggestion"
    assert selection["selected_category_id"] == 31
    assert selection["grounding"] == first["category_selection"]["grounding"]


def test_chat_disabled_switch_leaves_release_0_payload_identical(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setattr(config, "RAG_ENABLED", False)
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
        ]),
    )
    use_extraction(monkeypatch, {**CREATE_FIELDS, "category": "Fitness"})
    answer = use_grounded_answer(monkeypatch, grounded())

    response = client.post("/chat", json={"message": MESSAGE})

    assert response.get_json()["category_selection"] == {
        "source": "ai_suggestion",
        "suggested_category_id": 31,
        "suggested_category_name": "Fitness",
        "selected_category_id": None,
        "selected_category_name": None,
        "requires_user_response": True,
    }
    answer.assert_not_called()


def test_ui_chat_renders_correction_citation_without_amount(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_on,
):
    """Correction documents carry no amount; the card must still render."""
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[response_with_json(CATEGORIES)]),
    )
    use_extraction(monkeypatch, CREATE_FIELDS)
    use_grounded_answer(monkeypatch, grounded(citations=[
        {
            "marker": 1,
            "id": "corr-3",
            "collection": "transactions-records",
            "source": "correction 3",
            "excerpt": "Transaction 26 (Anytime Fitness Ultimo, 'Direct debit') "
                       "was recategorised from Uncategorised to Fitness on 2026-08-20.",
            "distance": 0.29,
            "category_id": 31,
            "category": "Fitness",
            "date": "2026-08-20",
            "merchant": "Anytime Fitness Ultimo",
        },
        {
            "marker": 2,
            "id": "tx-7",
            "collection": "transactions-records",
            "source": "transaction 7",
            "excerpt": "Transaction 7 ...",
            "distance": 0.31,
            "category_id": 31,
            "category": "Fitness",
            "date": "2026-06-24",
            "merchant": "Anytime Fitness Ultimo",
            "amount": 17.5,
        },
        {
            "marker": 3,
            "id": "transactions_categories.md_2",
            "collection": "transactions",
            "source": "categories.md",
            "excerpt": "Fitness: club direct debits.",
            "distance": 0.52,
        },
    ]))

    response = client.post("/ui/chat", data={"message": MESSAGE})

    assert response.status_code == 200
    text = response.text
    assert "HIGH confidence" in text
    assert "20 Aug 2026 · Anytime Fitness Ultimo · Fitness" in text
    assert "(correction)" in text
    assert "24 Jun 2026 · Anytime Fitness Ultimo · $17.50 · Fitness" in text
    # Record rows no longer show the transaction or correction id.
    assert "transaction 7" not in text
    assert "correction 3" not in text
    assert "guide categories.md:" in text
    assert "Accept suggestion" in text


def test_grounding_log_record_is_redacted(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_on,
    caplog,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[response_with_json(CATEGORIES)]),
    )
    use_extraction(monkeypatch, CREATE_FIELDS)
    use_grounded_answer(monkeypatch, grounded())

    with caplog.at_level(logging.INFO, logger=client.application.logger.name):
        response = client.post("/chat", json={"message": MESSAGE})

    records = workflow_records(caplog, "RAG_GROUNDING")
    assert len(records) == 1
    record = records[0]
    assert record["request_id"] == response.get_json()["agent"]["request_id"]
    assert record["status"] == "grounded"
    assert record["confidence"] == "high"
    assert record["collections"] == ["transactions-records", "transactions"]
    assert record["retrieved"] == 9
    assert record["survivors"] == 2
    assert record["best_distance"] == 0.31
    assert record["model_probability"] == 0.93
    assert record["citations"] == 2
    assert record["derived_from_votes"] is False
    assert record["uncited"] is False
    assert record["error"] is None
    assert record["duration_ms"] >= 0
    assert "excerpt" not in json.dumps(record)
    assert "Anytime Fitness" not in caplog.text
    assert "Membership" not in caplog.text
    assert MESSAGE not in caplog.text


def test_grounding_log_records_unavailable_with_safe_code(
    client: FlaskClient,
    monkeypatch: MonkeyPatch,
    rag_on,
    caplog,
):
    monkeypatch.setattr(
        backend_app.requests,
        "get",
        Mock(side_effect=[
            response_with_json(CATEGORIES),
            response_with_json([]),
        ]),
    )
    use_extraction(monkeypatch, CREATE_FIELDS)
    use_grounded_answer(monkeypatch, error=RAGError("rag_timeout"))

    with caplog.at_level(logging.INFO, logger=client.application.logger.name):
        client.post("/chat", json={"message": MESSAGE})

    records = workflow_records(caplog, "RAG_GROUNDING")
    assert len(records) == 1
    assert records[0]["status"] == "unavailable"
    assert records[0]["error"] == "rag_timeout"
    assert records[0]["confidence"] is None
